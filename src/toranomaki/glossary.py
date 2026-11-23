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
_KEYS = {"term", "aliases", "context_only", "note", "pin"}


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
    return Term(
        term=str(item["term"]).strip(),
        aliases=tuple(str(a).strip() for a in aliases if str(a).strip()),
        context_only=bool(item.get("context_only", False)),
        note=str(item.get("note") or "").strip(),
        pin=bool(item.get("pin", False)),
    )


def load_terms(path: Path) -> list[Term]:
    if not path.is_file():
        raise GlossaryError(f"glossary not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise GlossaryError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("terms") or [], list):
        raise GlossaryError(f"{path}: expected a mapping with a 'terms' list")
    return [parse_term(item, str(path)) for item in raw.get("terms") or []]
