from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import toranomaki.sync as sync_module
from toranomaki.glossary import GlossaryError, Term, load_glossary
from toranomaki.sync import main, plan_hex, replacement_pairs

TERMS = [
    Term("prompts", ("プロンプツ",)),
    Term("不要", ("扶養",), context_only=True),
    Term("Cloud Spanner", ("クラウドスパナー", "スパナー")),
    Term("ローカル LLM", ("LL, MA",), context_only=True),
]


class FakeRun:
    def __init__(self, code: int = 0) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.code = code

    def __call__(self, args, stdin):
        self.calls.append((list(args), stdin))
        return subprocess.CompletedProcess(args, self.code, "", "err" if self.code else "")


def hex_settings(replacements=(), vocabulary=()) -> dict[str, Any]:
    return {
        "dictation_processing": {
            "default_mode": {"name": "Global", "replacements": list(replacements), "modes": []}
        },
        "vocabulary": list(vocabulary),
    }


def test_replacement_pairs_skip_context_only_and_sort_longest_first() -> None:
    assert replacement_pairs(TERMS) == [
        ("クラウドスパナー", "Cloud Spanner"),
        ("プロンプツ", "prompts"),
        ("スパナー", "Cloud Spanner"),
    ]


def test_hex_plan_adds_and_fixes_without_removing() -> None:
    run = FakeRun()
    settings = hex_settings(
        replacements=[
            {"matched_phrase": "えーと", "output": ""},  # 手で入れた項目は残す
            {"matched_phrase": "プロンプツ", "output": "promts"},  # 間違いは直す
        ],
        vocabulary=[{"term": "Cloud Spanner", "sounds_like": ["クラウドスパナー"]}],
    )
    change = plan_hex(TERMS, settings, Path("hex.com"), run)
    for action in change.actions:
        action()

    args, stdin = run.calls[0]
    assert args[1:] == ["settings", "apply", "-"]
    assert stdin is not None
    mode = json.loads(stdin)["dictation_processing.default_mode"]
    phrases = {r["matched_phrase"]: r["output"] for r in mode["replacements"]}
    assert phrases == {
        "えーと": "",
        "プロンプツ": "prompts",
        "クラウドスパナー": "Cloud Spanner",
        "スパナー": "Cloud Spanner",
    }
    assert "扶養" not in phrases  # context_only は置き換えに入れない
    assert mode["name"] == "Global"  # 他の項目はそのまま

    vocab_calls = [a[1:] for a, _ in run.calls[1:]]
    assert vocab_calls == [
        ["vocabulary", "add", "--sounds-like", "プロンプツ", "--", "prompts"],
        ["vocabulary", "add", "--sounds-like", "スパナー", "--", "Cloud Spanner"],
    ]


def test_hex_plan_is_empty_when_in_sync() -> None:
    settings = hex_settings(
        replacements=[{"matched_phrase": a, "output": t} for a, t in replacement_pairs(TERMS)],
        vocabulary=[
            {"term": t.term, "sounds_like": list(t.aliases)} for t in TERMS if not t.context_only
        ],
    )
    assert plan_hex(TERMS, settings, Path("hex.com"), FakeRun()).empty


def test_sync_reads_mixed_hex_vocabulary_formats() -> None:
    settings = hex_settings(
        vocabulary=["Rust", {"term": "Python", "sounds_like": ["パイソン"]}, {"term": "Go"}]
    )
    run = FakeRun()
    change = plan_hex([Term("Rust"), Term("Go")], settings, Path("hex.com"), run)
    assert change.empty
    assert "3/3" in change.notes[0]
    assert not run.calls


def test_sync_routes_aliases_and_removes_old_global_rule(tmp_path: Path) -> None:
    glossary = tmp_path / "glossary.yaml"
    glossary.write_text(
        """hex_modes:
  Zed: [Zed, 'Visual Studio Code']
terms:
  - term: Ruff
    aliases: [ルフ, パイスルフ, ラフ]
    context_only: true
    alias_modes: {ルフ: [Zed], パイスルフ: [], ラフ: global}
""",
        encoding="utf-8",
    )
    terms, modes = load_glossary(glossary)
    settings = hex_settings(
        replacements=[
            {"matched_phrase": "ルフ", "output": "Ruff"},
            {"matched_phrase": "えっと", "output": ""},
        ]
    )
    processing = settings["dictation_processing"]
    processing["modes"] = [{"name": "Zed", "applications": ["Zed"], "replacements": []}]
    run = FakeRun()
    change = plan_hex(terms, settings, Path("hex.com"), run, tmp_path, app_modes=modes)
    assert not list(tmp_path.glob("hex-app-modes-*.json"))
    assert not run.calls
    for action in change.actions:
        action()
    saved = next(tmp_path.glob("hex-app-modes-*.json"))
    assert json.loads(saved.read_text(encoding="utf-8")) == processing
    assert len(run.calls) == 1  # モードと共通置き換えを一度に適用し、vocabulary には送らない
    payload = run.calls[0][1]
    assert payload is not None
    updates = json.loads(payload)
    assert updates["dictation_processing.default_mode"]["replacements"] == [
        {"matched_phrase": "えっと", "output": ""},
        {"matched_phrase": "ラフ", "output": "Ruff"},
    ]
    assert updates["dictation_processing.modes"] == [
        {
            "name": "Zed",
            "applications": ["Zed", "Visual Studio Code"],
            "replacements": [{"matched_phrase": "ルフ", "output": "Ruff"}],
        }
    ]
    for key, value in updates.items():
        processing[key.split(".")[1]] = value
    assert plan_hex(terms, settings, Path("hex.com"), FakeRun(), app_modes=modes).empty


def test_sync_rejects_overlapping_app_modes() -> None:
    settings = hex_settings()
    settings["dictation_processing"]["modes"] = [{"name": "Manual", "applications": ["zed"]}]
    with pytest.raises(GlossaryError, match="競合"):
        plan_hex([], settings, Path("hex.com"), FakeRun(), app_modes={"Programming": ("Zed",)})


def test_cli_apply_reports_hex_failure(tmp_path: Path) -> None:
    glossary = tmp_path / "g.yaml"
    glossary.write_text('terms:\n  - term: "prompts"\n    aliases: ["プロンプツ"]\n', "utf-8")
    (tmp_path / "settings.json").write_text(json.dumps(hex_settings()), encoding="utf-8")
    argv = ["--glossary", str(glossary), "--hex-dir", str(tmp_path), "--apply"]
    assert main(argv, run=FakeRun(code=3)) == 1


def test_cli_prefers_new_glossary_and_falls_back_to_legacy(tmp_path, monkeypatch, capsys) -> None:
    new = tmp_path / "new.yaml"
    legacy = tmp_path / "legacy.yaml"
    monkeypatch.setattr(sync_module, "DEFAULT_GLOSSARY", new)
    monkeypatch.setattr(sync_module, "LEGACY_GLOSSARY", legacy)
    argv = ["--hex-dir", str(tmp_path)]

    assert main(argv + ["--glossary", str(legacy)], run=FakeRun()) == 2
    legacy.write_text("terms: []", encoding="utf-8")
    assert main(argv, run=FakeRun()) == 0
    assert f"glossary: {legacy}" in capsys.readouterr().out

    new.write_text("terms: []", encoding="utf-8")
    assert main(argv, run=FakeRun()) == 0
    assert f"glossary: {new}" in capsys.readouterr().out
    assert main(argv + ["--glossary", str(legacy)], run=FakeRun()) == 0
    assert f"glossary: {legacy}" in capsys.readouterr().out


def test_hex_vocabulary_skips_spellings_with_commas() -> None:
    run = FakeRun()
    change = plan_hex([Term("A B", ("x, y", "z"))], hex_settings(), Path("hex.com"), run)
    for action in change.actions:
        action()
    assert run.calls[-1][0][1:] == ["vocabulary", "add", "--sounds-like", "z", "--", "A B"]


def _glossary(tmp_path: Path) -> Path:
    path = tmp_path / "g.yaml"
    path.write_text('terms:\n  - term: "prompts"\n    aliases: ["プロンプツ"]\n', "utf-8")
    return path


def test_cli_dry_run_writes_nothing(tmp_path: Path, capsys) -> None:
    hex_dir = tmp_path / "hex"
    hex_dir.mkdir()
    (hex_dir / "settings.json").write_text(json.dumps(hex_settings()), encoding="utf-8")
    run = FakeRun()
    assert main(["--glossary", str(_glossary(tmp_path)), "--hex-dir", str(hex_dir)], run=run) == 0
    assert run.calls == []
    out = capsys.readouterr().out
    assert "replacements 追加: プロンプツ → prompts" in out and "dry-run" in out


def test_missing_hex_is_skipped(tmp_path: Path, capsys) -> None:
    argv = ["--glossary", str(_glossary(tmp_path)), "--hex-dir", str(tmp_path / "no-hex")]
    assert main(argv, run=FakeRun()) == 0
    assert "skip: Hex" in capsys.readouterr().out


def test_toranomaki_cli_runs_sync(tmp_path: Path, capsys) -> None:
    from toranomaki.main import main as toranomaki_main

    argv = ["sync", "--glossary", str(_glossary(tmp_path)), "--hex-dir", str(tmp_path / "no-hex")]
    assert toranomaki_main(argv) == 0
    assert "glossary:" in capsys.readouterr().out
