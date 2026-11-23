"""音声辞書の形式と読み込み。

正本は ``~/.toranomaki/voice-glossary.yaml``（Claude Code と Codex が会話中に育てる）。

    terms:
      - term: "Claude Code"          # 正しい表記（意図していた語）
        aliases: ["クロードコード"]    # 実際に出てきた誤認識
      - term: "不要"
        aliases: ["扶養"]
        context_only: true           # 一般語と衝突する。機械的に置き換えてはいけない
        note: "「扶養なら〜」= 不要なら"  # どういう文脈で読み替えたか（人と Claude 向けのメモ）
      - term: "Kubernetes"
        aliases: ["クバネティス"]
        pin: true                    # Hex の認識寄せで優先する（vocabulary の先頭に並べる）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_GLOSSARY = Path.home() / ".toranomaki" / "voice-glossary.yaml"
LEGACY_GLOSSARY = Path.home() / ".claude" / "voice-glossary.yaml"
GLOBAL_SCOPE = "global"
_KEYS = {"term", "aliases", "context_only", "note", "pin", "alias_modes"}


class GlossaryError(ValueError):
    """辞書ファイルの内容が不正。"""


@dataclass(frozen=True)
class Term:
    term: str
    aliases: tuple[str, ...] = ()
    context_only: bool = False
    note: str = ""
    # Hex の認識寄せの枠（先頭から 500 文字）で優先する。
    # toranomaki sync が vocabulary の先頭へ並べ替える
    pin: bool = False
    alias_modes: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def global_aliases(self) -> tuple[str, ...]:
        scopes = dict(self.alias_modes)
        default = () if self.context_only else (GLOBAL_SCOPE,)
        return tuple(
            alias for alias in self.aliases if scopes.get(alias, default) == (GLOBAL_SCOPE,)
        )


def _name_list(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise GlossaryError(f"{where}: 名前のリストが必要です")
    return tuple(dict.fromkeys(item.strip() for item in value))


def parse_term(item: Any, where: str) -> Term:
    if isinstance(item, str) and item.strip():
        return Term(term=item.strip())
    if not isinstance(item, dict) or not str(item.get("term") or "").strip():
        raise GlossaryError(f"{where}: each entry needs a 'term': {item!r}")
    unknown = set(item) - _KEYS
    if unknown:
        raise GlossaryError(f"{where}: unknown key(s) {sorted(unknown)} in {item!r}")
    aliases = item.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    aliases = tuple(str(a).strip() for a in aliases if str(a).strip())
    raw_modes = item.get("alias_modes", {})
    if not isinstance(raw_modes, dict):
        raise GlossaryError(f"{where}: alias_modes は別名とモードの対応表が必要です")
    modes = []
    for alias, names in raw_modes.items():
        if alias not in aliases or alias == str(item["term"]).strip():
            raise GlossaryError(f"{where}: alias_modes に未登録または同一表記の別名: {alias!r}")
        selected = (
            (GLOBAL_SCOPE,)
            if names == GLOBAL_SCOPE
            else _name_list(names, f"{where}: alias_modes[{alias!r}]")
        )
        if names != GLOBAL_SCOPE and GLOBAL_SCOPE in selected:
            raise GlossaryError(f"{where}: global はリストではなく文字列で指定してください")
        modes.append((alias, selected))
    return Term(
        term=str(item["term"]).strip(),
        aliases=aliases,
        context_only=bool(item.get("context_only", False)),
        note=str(item.get("note") or "").strip(),
        pin=bool(item.get("pin", False)),
        alias_modes=tuple(modes),
    )


def load_glossary(path: Path) -> tuple[list[Term], dict[str, tuple[str, ...]]]:
    if not path.is_file():
        raise GlossaryError(f"glossary not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise GlossaryError(f"{path}: invalid YAML: {exc}") from exc
    return parse_glossary(raw, str(path))


def parse_glossary(raw: Any, source: str) -> tuple[list[Term], dict[str, tuple[str, ...]]]:
    path = source
    if not isinstance(raw, dict) or not isinstance(raw.get("terms") or [], list):
        raise GlossaryError(f"{path}: expected a mapping with a 'terms' list")
    terms = [parse_term(item, str(path)) for item in raw.get("terms") or []]
    raw_modes = raw.get("hex_modes", {})
    if not isinstance(raw_modes, dict):
        raise GlossaryError(f"{path}: hex_modes はモード名とアプリの対応表が必要です")
    modes: dict[str, tuple[str, ...]] = {}
    for name, value in raw_modes.items():
        if (
            not isinstance(name, str)
            or not name.strip()
            or name != name.strip()
            or name == GLOBAL_SCOPE
        ):
            raise GlossaryError(f"{path}: 無効な Hex モード名: {name!r}")
        apps = _name_list(value, f"{path}: hex_modes[{name!r}]")
        if not apps:
            raise GlossaryError(f"{path}: Hex モード {name!r} にアプリがありません")
        modes[name] = apps
    for term in terms:
        for alias, names in term.alias_modes:
            for name in names:
                if name != GLOBAL_SCOPE and name not in modes:
                    raise GlossaryError(f"{path}: {alias!r} が未定義の Hex モード {name!r} を参照")
    return terms, modes


def load_terms(path: Path) -> list[Term]:
    return load_glossary(path)[0]
