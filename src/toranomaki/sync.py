"""共通の音声辞書（~/.toranomaki/voice-glossary.yaml）を Hex へ配る（`toranomaki sync`）。

辞書は Claude Code と Codex が会話中に育てる唯一の正本。Hex は自分たちで管理していないアプリなので、
公式 CLI を通して Hex の形式へ書き出す:

- replacements（機械的な置き換え）: context_only でない aliases → {"matched_phrase", "output"}
- vocabulary（認識寄せ・AI 書き直し用）: context_only でない term と aliases → {term, sounds_like}
  pin: true の語は vocabulary の先頭へ並べ替える

context_only の語（「扶養」→「不要」など一般語と衝突するもの）は、どちらにも入れない。
既存の項目は消さず、追加と修正だけを行う（並べ替え・復元は事前にバックアップする）。

自分で作るツールは、この辞書を直接読めばよい（書き出さない）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from toranomaki.glossary import DEFAULT_GLOSSARY, LEGACY_GLOSSARY, GlossaryError, Term, load_terms

HEX_DIR = Path(os.environ.get("APPDATA", "")) / "hex"
# 並べ替え・復元の前に取る Hex vocabulary のバックアップ。新しい方から KEEP_BACKUPS 個を残す
DEFAULT_BACKUP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "toranomaki" / "backups"
BACKUP_PREFIX = "hex-vocabulary-"
KEEP_BACKUPS = 3
# Hex は vocabulary を先頭から「, 」でつないで 500 文字に収まる分だけ Whisper の前置きに使う
# （src/dictation/vocabulary.rs の prompt_chars("whisper")）。超えた後ろの語は認識寄せに使われない
HEX_PROMPT_CHARS = 500
HEX_PROMPT_WARN_AT = 450

Runner = Callable[[Sequence[str], str | None], "subprocess.CompletedProcess[str]"]


class VocabularyEntry(TypedDict):
    term: str
    sounds_like: list[str]


@dataclass
class Change:
    target: str
    summary: list[str] = field(default_factory=list)
    actions: list[Callable[[], None]] = field(default_factory=list)
    # 変更には数えない情報（枠の使用量など）。変更がなくても表示する
    notes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.summary


def replacement_pairs(terms: Sequence[Term]) -> list[tuple[str, str]]:
    """機械的に置き換えてよい（誤認識, 正しい語）の組。長い誤認識から順に並べる。"""
    pairs: dict[str, str] = {}
    for t in terms:
        if t.context_only:
            continue
        for alias in t.aliases:
            if alias and alias != t.term:
                pairs[alias] = t.term
    return sorted(pairs.items(), key=lambda kv: len(kv[0]), reverse=True)


# --- Hex ---


def plan_hex(
    terms: Sequence[Term],
    settings: dict[str, Any],
    hex_cli: Path,
    run: Runner,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
) -> Change:
    change = Change("Hex")
    mode = dict(settings["dictation_processing"]["default_mode"])
    existing = [dict(r) for r in mode.get("replacements") or []]
    by_phrase = {r.get("matched_phrase"): r for r in existing}
    added = []
    for alias, term in replacement_pairs(terms):
        current = by_phrase.get(alias)
        if current is None:
            added.append({"matched_phrase": alias, "output": term})
            change.summary.append(f"replacements 追加: {alias} → {term}")
        elif current.get("output") != term:
            change.summary.append(
                f"replacements 修正: {alias} → {current.get('output')} を {term} に"
            )
            current["output"] = term
    if change.summary:
        mode["replacements"] = existing + added
        payload = json.dumps({"dictation_processing.default_mode": mode}, ensure_ascii=False)
        change.actions.append(
            lambda: _check(run([str(hex_cli), "settings", "apply", "-"], payload), "settings apply")
        )

    # 追加後の vocabulary の並びを Hex と同じ規則で再現する
    # （新しい語は末尾、既存の語は位置そのまま）
    after: list[VocabularyEntry] = [
        {"term": v["term"], "sounds_like": list(v.get("sounds_like") or [])}
        for v in settings.get("vocabulary") or []
    ]
    vocab = {v["term"]: set(v["sounds_like"]) for v in after}
    for t in terms:
        if t.context_only:
            # 一般語と衝突する読み替え（扶養→不要 等）は Claude 向け。認識寄せに入れると逆効果
            continue
        # Hex の --sounds-like はカンマ区切りなので、カンマを含む表記は送れない
        spellings = [a for a in t.aliases if a != t.term and "," not in a]
        skipped = [a for a in t.aliases if "," in a]
        missing = [a for a in spellings if a not in vocab.get(t.term, set())]
        if t.term in vocab and not missing:
            continue
        verb = "追加" if t.term not in vocab else "表記を追加"
        line = f"vocabulary {verb}: {t.term}" + (f"（{', '.join(missing)}）" if missing else "")
        if skipped:
            line += f" ※カンマを含むため送らない: {skipped}"
        change.summary.append(line)
        change.actions.append(_vocab_add(hex_cli, run, t.term, missing))
        entry = next((v for v in after if v["term"] == t.term), None)
        if entry is None:
            after.append({"term": t.term, "sounds_like": missing})
        else:
            entry["sounds_like"] += missing

    _plan_hex_order(change, terms, after, hex_cli, run, backup_dir)
    change.notes += hex_prompt_notes(desired_order(terms, [e["term"] for e in after]))
    return change


def hex_prompt_usage(names: Sequence[str]) -> tuple[int, int]:
    """(認識寄せに使われる文字数, 使われる語数)。Hex の prompt_terms と同じ数え方。"""
    chars = 0
    for index, name in enumerate(names):
        added = (2 if index else 0) + len(name)
        if chars + added > HEX_PROMPT_CHARS:
            return chars, index
        chars += added
    return chars, len(names)


def hex_prompt_notes(names: Sequence[str]) -> list[str]:
    used, fit = hex_prompt_usage(names)
    notes = [f"認識寄せの枠: {used}/{HEX_PROMPT_CHARS} 文字（{fit}/{len(names)} 語が使われる）"]
    if fit < len(names):
        notes.append(
            f"⚠ 枠から外れて認識寄せに使われない語: {list(names[fit:])}"
            "（置き換えは効く。優先したい語は辞書で pin: true）"
        )
    elif used > HEX_PROMPT_WARN_AT:
        notes.append(f"⚠ 枠の残りが {HEX_PROMPT_CHARS - used} 文字。この先に足す語は外れやすい")
    return notes


def pinned_terms(terms: Sequence[Term], names: Sequence[str]) -> list[str]:
    """Hex の vocabulary にある語のうち、辞書で pin した語（辞書の順）。"""
    present = set(names)
    return list(
        dict.fromkeys(t.term for t in terms if t.pin and not t.context_only and t.term in present)
    )


def desired_order(terms: Sequence[Term], names: Sequence[str]) -> list[str]:
    """pin した語を辞書の順で先頭に、残りは今の並びのまま。

    Hex は vocabulary を先頭から 500 文字分しか認識寄せに使わない（溢れた後ろの語は使われない）。
    """
    pinned = pinned_terms(terms, names)
    return pinned + [n for n in names if n not in set(pinned)]


def _plan_hex_order(
    change: Change,
    terms: Sequence[Term],
    entries: list[VocabularyEntry],
    hex_cli: Path,
    run: Runner,
    backup_dir: Path,
) -> None:
    names = [e["term"] for e in entries]
    desired = desired_order(terms, names)
    prefix = next((i for i, (a, b) in enumerate(zip(names, desired, strict=True)) if a != b), None)
    if prefix is None:
        return
    spellings = {e["term"]: e["sounds_like"] for e in entries}
    # 並べ替えは「消してすぐ入れ直す」と末尾に回ることを使う。
    # ずれ始めた位置から後ろを、望む順に入れ直す
    redo = desired[prefix:]
    broken = [n for n in redo if any("," in s for s in spellings[n])]
    if broken:
        change.summary.append(f"vocabulary 並べ替えを中止: カンマを含む表記は入れ直せない {broken}")
        return
    change.summary.append(
        f"vocabulary 並べ替え: pin した語 {pinned_terms(terms, names)} を先頭へ"
        f"（{len(redo)} 語を入れ直し、事前にバックアップ）"
    )
    change.actions.append(lambda: _backup_expecting(hex_cli, run, backup_dir, names))
    for name in redo:
        args = [str(hex_cli), "vocabulary", "remove", "--", name]
        change.actions.append(lambda args=args: _check(run(args, None), "vocabulary remove"))
        change.actions.append(_vocab_add(hex_cli, run, name, spellings[name]))


def _vocab_add(
    hex_cli: Path, run: Runner, term: str, spellings: Sequence[str]
) -> Callable[[], None]:
    args = [str(hex_cli), "vocabulary", "add"]
    if spellings:
        args += ["--sounds-like", ",".join(spellings)]
    args += ["--", term]
    return lambda: _check(run(args, None), "vocabulary add")


def hex_vocabulary(hex_cli: Path, run: Runner) -> list[dict[str, Any]]:
    """起動中の Hex から vocabulary を並び順どおりに読む（公式 CLI の版付き JSON）。"""
    result = run([str(hex_cli), "vocabulary", "list", "--json"], None)
    _check(result, "vocabulary list")
    reply = json.loads(result.stdout)
    if reply.get("status") != "vocabulary" or not isinstance(reply.get("entries"), list):
        raise RuntimeError(f"unexpected reply from hex vocabulary list: {result.stdout[:200]}")
    return [
        {"term": e["term"], "sounds_like": list(e.get("sounds_like") or [])}
        for e in reply["entries"]
    ]


def backup_hex_vocabulary(
    hex_cli: Path, run: Runner, backup_dir: Path, keep: int = KEEP_BACKUPS
) -> Path:
    entries = hex_vocabulary(hex_cli, run)
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"{BACKUP_PREFIX}{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    path.write_text(
        json.dumps({"entries": entries}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  バックアップ: {path}（戻すには toranomaki hex-restore {path} --apply）")
    removed = prune_backups(backup_dir, keep)
    if removed:
        print(f"  古いバックアップを {len(removed)} 個削除（新しい {keep} 個を残す）")
    return path


def prune_backups(
    backup_dir: Path, keep: int = KEEP_BACKUPS, *, pattern: str = f"{BACKUP_PREFIX}*.json"
) -> list[Path]:
    """新しい順に keep 個だけ残し、それより古いバックアップを消す。

    対象は toranomaki が作った hex-vocabulary-*.json だけ。ファイル名の日時で並べる
    （更新日時はコピーなどで変わるため使わない）。
    """
    backups = sorted(backup_dir.glob(pattern), key=lambda p: p.name)
    old = backups[: max(len(backups) - max(keep, 1), 0)]
    for path in old:
        path.unlink()
    return old


def _backup_expecting(hex_cli: Path, run: Runner, backup_dir: Path, names: Sequence[str]) -> None:
    """バックアップを取り、Hex の実際の並びが予測どおりかを確かめる（違えば並べ替えを中止）。"""
    path = backup_hex_vocabulary(hex_cli, run, backup_dir)
    actual = [e["term"] for e in json.loads(path.read_text(encoding="utf-8"))["entries"]]
    if actual != list(names):
        raise RuntimeError(
            "Hex の vocabulary が予測した並びと違うため、並べ替えを中止しました"
            "（何も消していません）。"
            "もう一度 toranomaki sync を実行してください"
        )


def plan_hex_restore(
    backup: list[dict[str, Any]],
    current: list[dict[str, Any]],
    hex_cli: Path,
    run: Runner,
    backup_dir: Path,
) -> Change:
    """vocabulary をバックアップと同じ中身・並びに戻す（今の状態も先にバックアップする）。"""
    change = Change("Hex vocabulary 復元")
    if backup == current:
        return change
    broken = [e["term"] for e in backup if any("," in s for s in e["sounds_like"])]
    if broken:
        change.summary.append(f"復元を中止: カンマを含む表記は入れ直せない {broken}")
        return change
    change.summary.append(
        f"今の {len(current)} 語を消し、バックアップの {len(backup)} 語を同じ順で入れ直す"
    )

    def save_backup() -> None:
        backup_hex_vocabulary(hex_cli, run, backup_dir)

    change.actions.append(save_backup)
    for e in current:
        args = [str(hex_cli), "vocabulary", "remove", "--", e["term"]]
        change.actions.append(lambda args=args: _check(run(args, None), "vocabulary remove"))
    for e in backup:
        change.actions.append(_vocab_add(hex_cli, run, e["term"], e["sounds_like"]))
    return change


def _check(result: subprocess.CompletedProcess[str], what: str) -> None:
    if result.returncode != 0:
        raise RuntimeError(
            f"hex {what} failed ({result.returncode}): {result.stderr or result.stdout}"
        )


def _run(args: Sequence[str], stdin: str | None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), input=stdin, capture_output=True, text=True, encoding="utf-8", check=False
    )


# --- CLI ---


def add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    p.add_argument("--glossary", type=Path, help="override ~/.toranomaki/voice-glossary.yaml")
    p.add_argument("--hex-dir", type=Path, default=HEX_DIR)
    p.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)


def main(argv: Sequence[str] | None = None, run: Runner = _run) -> int:
    description = (__doc__ or "").partition("\n")[0]
    p = argparse.ArgumentParser(prog="toranomaki sync", description=description)
    add_arguments(p)
    return execute(p.parse_args(argv), run)


def add_restore_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("backup", type=Path, help="toranomaki sync が保存した hex-vocabulary-*.json")
    p.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    p.add_argument("--hex-dir", type=Path, default=HEX_DIR)
    p.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)


def execute_restore(args: argparse.Namespace, run: Runner = _run) -> int:
    hex_cli = args.hex_dir / "bin" / "hex.com"
    try:
        raw = json.loads(args.backup.read_text(encoding="utf-8"))
        backup = [
            {"term": e["term"], "sounds_like": list(e.get("sounds_like") or [])}
            for e in raw["entries"]
        ]
        current = hex_vocabulary(hex_cli, run)
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    change = plan_hex_restore(backup, current, hex_cli, run, args.backup_dir)
    print(f"backup: {args.backup}（{len(backup)} 語）")
    return _report_and_apply([change], args.apply)


def execute(args: argparse.Namespace, run: Runner = _run) -> int:
    settings_path = args.hex_dir / "settings.json"
    glossary = args.glossary
    try:
        if glossary is None:
            glossary = DEFAULT_GLOSSARY
            if not glossary.exists() and LEGACY_GLOSSARY.is_file():
                glossary = LEGACY_GLOSSARY
        terms = load_terms(glossary)
        print(f"glossary: {glossary}（{len(terms)} 語）")
        if not settings_path.exists():
            print(f"skip: Hex（{settings_path} が見つからない）")
            return 0
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        hex_cli = args.hex_dir / "bin" / "hex.com"
        change = plan_hex(terms, settings, hex_cli, run, args.backup_dir)
    except (GlossaryError, OSError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return _report_and_apply([change], args.apply)


def _report_and_apply(changes: Sequence[Change], apply: bool) -> int:
    for change in changes:
        print(f"\n[{change.target}]" + (" 変更なし" if change.empty else ""))
        for line in change.summary:
            print(f"  {line}")
        for line in change.notes:
            print(f"  {line}")
    if not apply:
        if any(not c.empty for c in changes):
            print("\n(dry-run) 反映するには --apply を付けて実行してください")
        return 0
    for change in changes:
        try:
            for action in change.actions:
                action()
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"\n[{change.target}] 反映に失敗: {exc}", file=sys.stderr)
            return 1
        if not change.empty:
            print(f"\n[{change.target}] 反映しました")
    return 0
