from __future__ import annotations

from pathlib import Path

import pytest

from toranomaki.glossary import GlossaryError, Term, load_terms, parse_term

ROOT = Path(__file__).parents[1]


def test_parse_full_entry() -> None:
    term = parse_term(
        {"term": "不要", "aliases": ["扶養"], "context_only": True, "note": "文脈"}, "x"
    )
    assert term == Term("不要", ("扶養",), context_only=True, note="文脈")


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ("Kubernetes", Term("Kubernetes")),
        ({"term": " Go ", "aliases": "ゴー"}, Term("Go", ("ゴー",))),
        ({"term": "A", "aliases": ["", " b "]}, Term("A", ("b",))),
    ],
)
def test_parse_shorthand(item, expected) -> None:
    assert parse_term(item, "x") == expected


@pytest.mark.parametrize("item", [{}, {"term": ""}, {"term": "A", "alias": ["typo"]}, 3])
def test_parse_rejects_bad_entries(item) -> None:
    with pytest.raises(GlossaryError):
        parse_term(item, "x")


def test_load_terms(tmp_path: Path) -> None:
    path = tmp_path / "g.yaml"
    path.write_text('terms:\n  - term: "prompts"\n    aliases: ["プロンプツ"]\n', "utf-8")
    assert load_terms(path) == [Term("prompts", ("プロンプツ",))]


@pytest.mark.parametrize("content", ["terms: 1\n", "- a\n", "terms: [\n"])
def test_load_terms_rejects_bad_files(tmp_path: Path, content: str) -> None:
    path = tmp_path / "g.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(GlossaryError):
        load_terms(path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(GlossaryError, match="not found"):
        load_terms(tmp_path / "nope.yaml")


def test_template_glossary_is_valid_and_generic() -> None:
    terms = load_terms(ROOT / "templates" / "voice-glossary.yaml")
    assert any(t.context_only for t in terms)  # 一般語ガードの例を含む


def test_template_claude_section_imports_the_glossary() -> None:
    text = (ROOT / "templates" / "CLAUDE.voice.md").read_text(encoding="utf-8")
    assert "@~/.toranomaki/voice-glossary.yaml" in text
    assert "辞書に追加" in text
