"""ローカルの YAML / Markdown を正本に差分マージする。"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import yaml

from toranomaki.glossary import DEFAULT_GLOSSARY, GlossaryError, Term, parse_term
from toranomaki.sync import DEFAULT_BACKUP_DIR, prune_backups

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
BACKUP_PREFIX = "voice-glossary-"


def _yaml(text: str, source: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GlossaryError(f"{source}: 不正な YAML: {exc}") from exc


def _entries(document: Any, source: str) -> list[Any]:
    if not isinstance(document, dict) or not isinstance(document.get("terms"), list):
        raise GlossaryError(f"{source}: terms のリストが必要です")
    return document["terms"]


def _parse_entry(entry: Any, source: str, *, keep_scopes: bool = False) -> Term:
    if isinstance(entry, dict):
        aliases = entry.get("aliases", [])
        if (
            not isinstance(entry.get("term"), str)
            or not (
                isinstance(aliases, str)
                or isinstance(aliases, list)
                and all(isinstance(a, str) for a in aliases)
            )
            or any(not isinstance(entry.get(key, False), bool) for key in ("pin", "context_only"))
            or not isinstance(entry.get("note", ""), str)
        ):
            raise GlossaryError(
                f"{source}: term / aliases / pin / context_only / note の型が不正です"
            )
        fields = ("term", "aliases", "context_only", "pin", "note")
        if keep_scopes:
            fields += ("alias_modes",)
        entry = {key: entry[key] for key in fields if key in entry}
    return parse_term(entry, source)


def _source_terms(text: str, source: str) -> list[Term]:
    marker = ""
    language = ""
    start = 0
    body: list[str] = []
    blocks: list[tuple[str, str]] = []
    for line_number, line in enumerate(text.splitlines(keepends=True), 1):
        match = FENCE.fullmatch(line.rstrip("\r\n"))
        if marker:
            if match and match[1].startswith(marker) and not match[2].strip():
                if language in {"yaml", "yml"}:
                    blocks.append((f"{source}:{start}", "".join(body)))
                marker = ""
            elif language in {"yaml", "yml"}:
                body.append(line)
        elif match:
            marker, language = match[1], match[2].strip().lower()
            start = line_number
            body = []
    if marker and language in {"yaml", "yml"}:
        raise GlossaryError(f"{source}:{start}: YAML コードブロックが閉じていません")
    if not blocks:
        blocks = [(source, text)]

    terms: list[Term] = []
    found = False
    for location, block in blocks:
        document = _yaml(block, location)
        if isinstance(document, dict) and "terms" in document:
            found = True
            for index, entry in enumerate(_entries(document, location), 1):
                terms.append(_parse_entry(entry, f"{location}: terms[{index}]"))
    if not found:
        raise GlossaryError(f"{source}: 有効な terms リストが見つかりません")
    return terms


class _Aliases(list[str]):
    """YAML 出力でインライン配列にする別名リスト。"""


class _GlossaryDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow, indentless=False)


def _represent_aliases(dumper: yaml.SafeDumper, aliases: _Aliases) -> yaml.nodes.SequenceNode:
    return yaml.nodes.SequenceNode(
        "tag:yaml.org,2002:seq",
        [dumper.represent_scalar("tag:yaml.org,2002:str", a, style='"') for a in aliases],
        flow_style=True,
    )


_GlossaryDumper.add_representer(_Aliases, _represent_aliases)


def _output_entry(term: Term, original: Any) -> Any:
    if not isinstance(original, dict) and not (
        term.aliases or term.context_only or term.pin or term.note
    ):
        return term.term
    result: dict[str, Any] = {"term": term.term}
    if isinstance(original, dict):
        result.update(original)
    result["term"] = term.term
    for key, value in (
        ("aliases", _Aliases(term.aliases)),
        ("context_only", term.context_only),
        ("pin", term.pin),
        ("note", term.note),
    ):
        if value:
            result[key] = value
        else:
            result.pop(key, None)
    return result


def _merge(entries: list[Any], incoming: list[Term], target: str) -> tuple[list[str], list[str]]:
    positions: dict[str, int] = {}
    terms: dict[str, Term] = {}
    owners: dict[str, set[str]] = {}
    for index, entry in enumerate(entries):
        term = _parse_entry(entry, f"{target}: terms[{index + 1}]", keep_scopes=True)
        positions.setdefault(term.term, index)
        terms.setdefault(term.term, term)
        for alias in term.aliases:
            owners.setdefault(alias, set()).add(term.term)

    changes: list[str] = []
    warnings: list[str] = []
    for term in incoming:
        name = term.term
        current = terms.get(name)
        aliases = list(current.aliases) if current else []
        added: list[str] = []
        for alias in term.aliases:
            if alias in aliases:
                continue
            conflicts = owners.get(alias, set()) - {name}
            if conflicts:
                warning = f"{name}: 別名 {alias!r} は {', '.join(sorted(conflicts))} に登録済み"
                if warning not in warnings:
                    warnings.append(warning)
                continue
            aliases.append(alias)
            added.append(alias)
            owners.setdefault(alias, set()).add(name)
        merged = replace(term, aliases=tuple(aliases))
        if current is None:
            positions[name] = len(entries)
            entries.append(_output_entry(merged, None))
            changes.append(f"語を追加: {name}" + ("（pin: true）" if merged.pin else ""))
        else:
            note = current.note
            if term.note and term.note not in note:
                note = f"{note} / {term.note}" if note else term.note
            merged = replace(
                merged,
                context_only=current.context_only or term.context_only,
                pin=current.pin,
                note=note,
                alias_modes=current.alias_modes,
            )
            if merged == current:
                continue
            index = positions[name]
            original = entries[index]
            entries[index] = _output_entry(merged, original)
            if isinstance(original, str) and isinstance(entries[index], dict):
                changes.append(f"マッピングに昇格: {name}")
        if added:
            changes.append(f"{name}: 別名を追加 {', '.join(added)}")
        if merged.context_only and (current is None or not current.context_only):
            changes.append(f"{name}: context_only: true")
        if merged.note and (current is None or merged.note != current.note):
            changes.append(f"{name}: note を更新: {merged.note}")
        terms[name] = merged
    return changes, warnings


def _write(target: Path, original: bytes, text: str) -> Path:
    pending: Path | None = None
    try:
        with NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            pending = Path(handle.name)
            handle.write(text.encode("utf-8"))
        if target.read_bytes() != original:
            raise GlossaryError(f"{target}: 確認後に辞書が変更されました。やり直してください")
        DEFAULT_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        backup = DEFAULT_BACKUP_DIR / f"{BACKUP_PREFIX}{datetime.now():%Y%m%d-%H%M%S-%f}.yaml"
        with backup.open("xb") as handle:
            handle.write(original)
        if target.read_bytes() != original:
            raise GlossaryError(f"{target}: 確認後に辞書が変更されました。やり直してください")
        pending.replace(target)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
    return backup


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("sources", nargs="+", help="YAML / Markdown files, or - for stdin")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--target", type=Path, default=DEFAULT_GLOSSARY)


def execute(args: argparse.Namespace) -> int:
    try:
        if args.sources.count("-") > 1:
            raise GlossaryError("標準入力 '-' は一度だけ指定してください")
        target = args.target.expanduser().resolve()
        if not target.is_file():
            raise GlossaryError(f"{target}: 辞書がありません。README の初期設定を参照してください")
        original = target.read_bytes()
        text = original.decode("utf-8-sig")
        document = _yaml(text, str(target))
        entries = _entries(document, str(target))
        sources: list[Term] = []
        if "-" in args.sources:
            reconfigure = getattr(sys.stdin, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8")
        for source in args.sources:
            try:
                source_text = (
                    sys.stdin.read()
                    if source == "-"
                    else Path(source).expanduser().read_text(encoding="utf-8-sig")
                )
            except (OSError, UnicodeError) as exc:
                raise GlossaryError(f"{source}: 読み込めません: {exc}") from exc
            sources.extend(_source_terms(source_text.removeprefix("\ufeff"), source))
        changes, warnings = _merge(entries, sources, str(target))
        for warning in warnings:
            print(f"警告: {warning}（スキップ）", file=sys.stderr)
        if not changes:
            print("変更なし")
            return 0
        for change in changes:
            print(change)
        if not args.apply:
            print("(dry-run) 反映するには --apply を付けて実行してください")
            return 0
        for index, entry in enumerate(entries):
            entries[index] = _output_entry(
                _parse_entry(entry, str(target), keep_scopes=True), entry
            )
        header = re.match(r"(?:[ \t]*(?:#[^\r\n]*)?\r?\n)*", text)
        output = (header[0] if header else "") + yaml.dump(
            document, Dumper=_GlossaryDumper, allow_unicode=True, sort_keys=False, width=100000
        )
        backup = _write(target, original, output)
    except (GlossaryError, OSError, UnicodeError, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"バックアップ: {backup}")
    try:
        prune_backups(DEFAULT_BACKUP_DIR, pattern=f"{BACKUP_PREFIX}*.yaml")
    except OSError as exc:
        print(f"警告: 古いバックアップを整理できません: {exc}", file=sys.stderr)
    return 0
