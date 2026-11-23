from __future__ import annotations

import io
from pathlib import Path

import pytest
import yaml

from toranomaki import merge
from toranomaki.main import main


@pytest.fixture
def target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(merge, "DEFAULT_BACKUP_DIR", tmp_path / "backups")
    path = tmp_path / "target.yaml"
    path.write_text(
        "# 辞書\n\nterms:\n  - Kubernetes\n  - term: Ruff\n    aliases: ルフ\n"
        "    context_only: true\n    pin: false\n    note: 既存\n",
        encoding="utf-8",
    )
    return path


def test_merge_markdown_yaml_and_stdin(
    target: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original = target.read_bytes()
    markdown = target.with_suffix(".md")
    markdown.write_text(
        "説明\n```   YAML  \nsettings: demo\n```\n"
        "~~~yml\nterms:\n  - term: ' Kubernetes '\n    aliases: クバネティス\n    pin: true\n~~~\n"
        "```yaml\nterms: [Go]\n```\n",
        encoding="utf-8",
    )
    source = target.with_name("source.yaml")
    source.write_text(
        "terms:\n  - term: Ruff\n    aliases: [ルフ, ラフ, ラフ]\n    note: 追加\n"
        "    context_only: false\n    pin: true\n"
        "  - term: Rust\n    aliases: [ルフ, ラスト]\n    pin: true\n",
        encoding="utf-8",
    )
    argv = ["merge", str(markdown), str(source), "-", "--target", str(target)]
    for apply in (False, True):
        monkeypatch.setattr("sys.stdin", io.StringIO("terms: [ruff]\n"))
        assert main([*argv, "--apply"] if apply else argv) == 0
        result = capsys.readouterr()
        assert "昇格" in result.out
        assert "Rust" in result.err and "Ruff" in result.err
        if not apply:
            assert target.read_bytes() == original
            assert not merge.DEFAULT_BACKUP_DIR.exists()

    rendered = target.read_text(encoding="utf-8")
    assert rendered.startswith("# 辞書\n\nterms:")
    assert 'aliases: ["ルフ", "ラフ"]' in rendered
    assert "false" not in rendered
    assert yaml.safe_load(rendered)["terms"] == [
        {"term": "Kubernetes", "aliases": ["クバネティス"]},
        {"term": "Ruff", "aliases": ["ルフ", "ラフ"], "context_only": True, "note": "既存 / 追加"},
        "Go",
        {"term": "Rust", "aliases": ["ラスト"], "pin": True},
        "ruff",
    ]
    backups = list(merge.DEFAULT_BACKUP_DIR.iterdir())
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    monkeypatch.setattr("sys.stdin", io.StringIO("terms: [ruff]\n"))
    assert main([*argv, "--apply"]) == 0
    assert "変更なし" in capsys.readouterr().out
    assert list(merge.DEFAULT_BACKUP_DIR.iterdir()) == backups
    assert target.read_text(encoding="utf-8") == rendered


@pytest.mark.parametrize(
    "malformed",
    [
        "```yaml\nterms: [Go]\n```\n```yml\nterms: [\n```\n",
        "```yaml\nsettings: example\n```\n",
        "terms: {term: Go}\n",
        'terms: [{term: Go, context_only: "false"}]\n',
        "```yaml\nterms: [Go]\n",
    ],
)
def test_invalid_input_never_writes(
    target: Path, malformed: str, capsys: pytest.CaptureFixture[str]
) -> None:
    valid = target.with_name("valid.yaml")
    valid.write_text("terms: [Go]", encoding="utf-8")
    invalid = target.with_name("invalid.md")
    invalid.write_text(malformed, encoding="utf-8")
    original = target.read_bytes()
    assert main(["merge", str(valid), str(invalid), "--target", str(target), "--apply"]) == 2
    assert "invalid.md" in capsys.readouterr().err
    assert target.read_bytes() == original
    assert not merge.DEFAULT_BACKUP_DIR.exists()


def test_backup_retention_is_separate_from_hex(target: Path) -> None:
    directory = merge.DEFAULT_BACKUP_DIR
    directory.mkdir()
    hex_backup = directory / "hex-vocabulary-20200101-000000-000000.json"
    hex_backup.write_text("{}", encoding="utf-8")
    source = target.with_name("source.yaml")
    for index in range(5):
        source.write_text(f"terms: [term-{index}]\n", encoding="utf-8")
        assert main(["merge", str(source), "--target", str(target), "--apply"]) == 0
    assert len(list(directory.glob("voice-glossary-*.yaml"))) == 3
    assert hex_backup.is_file()
