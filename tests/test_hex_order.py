"""Hex vocabulary の並べ替えとバックアップ・復元。

Hex の add / remove / list / settings apply を再現するフェイクで、最後の並びまで確かめる。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from toranomaki.glossary import Term
from toranomaki.main import main as toranomaki_main
from toranomaki.sync import desired_order, plan_hex, plan_hex_restore


class FakeHex:
    """vocabulary を Hex と同じ規則で持つ（新しい語は末尾、既存の語は位置そのまま）。"""

    def __init__(self, entries) -> None:
        self.entries = [{"term": t, "sounds_like": list(s)} for t, s in entries]
        self.replacements: list[dict[str, str]] = []
        self.calls: list[list[str]] = []
        self.fail_on: str | None = None

    def __call__(self, args, stdin):
        args = list(args)[1:]
        self.calls.append(args)
        out = ""
        if self.fail_on and self.fail_on in args:
            return subprocess.CompletedProcess(args, 1, "", "boom")
        if args[:2] == ["vocabulary", "list"]:
            out = json.dumps({"version": 4, "status": "vocabulary", "entries": self.entries})
        elif args[:2] == ["vocabulary", "add"]:
            *options, separator, term = args[2:]
            assert separator == "--"
            spellings = []
            if options:
                flag, value = options
                assert flag == "--sounds-like"
                spellings = value.split(",")
            entry = next((e for e in self.entries if e["term"] == term), None)
            if entry is None:
                self.entries.append({"term": term, "sounds_like": spellings})
            else:
                entry["sounds_like"] += [s for s in spellings if s not in entry["sounds_like"]]
        elif args[:2] == ["settings", "apply"]:
            mode = json.loads(stdin)["dictation_processing.default_mode"]
            self.replacements = mode["replacements"]
        elif args[:2] == ["vocabulary", "remove"]:
            separator, term = args[2:]
            assert separator == "--"
            self.entries = [e for e in self.entries if e["term"] != term]
        return subprocess.CompletedProcess(args, 0, out, "")

    def settings(self):
        return {
            "dictation_processing": {"default_mode": {"replacements": list(self.replacements)}},
            "vocabulary": json.loads(json.dumps(self.entries)),
        }

    @property
    def order(self):
        return [e["term"] for e in self.entries]


START = [("A", ["a"]), ("B", ["b1", "b2"]), ("C", []), ("D", ["d"])]
GLOSSARY = [Term("A", ("a",)), Term("B", ("b1", "b2")), Term("C"), Term("D", ("d",))]


def run_plan(hex_: FakeHex, terms, tmp_path: Path):
    change = plan_hex(terms, hex_.settings(), Path("hex.com"), hex_, tmp_path / "bk")
    for action in change.actions:
        action()
    return change


def test_desired_order_puts_pins_first_in_glossary_order() -> None:
    terms = [Term("D", pin=True), Term("B", pin=True), Term("X", pin=True), Term("C")]
    assert desired_order(terms, ["A", "B", "C", "D"]) == ["D", "B", "A", "C"]


def test_no_pins_means_no_reorder(tmp_path: Path) -> None:
    hex_ = FakeHex(START)
    run_plan(hex_, GLOSSARY, tmp_path)  # 置き換えは足されるが
    assert all(c[0] != "vocabulary" for c in hex_.calls)  # vocabulary には触らない
    assert hex_.order == ["A", "B", "C", "D"]


def test_pin_moves_term_to_front_and_keeps_spellings(tmp_path: Path) -> None:
    hex_ = FakeHex(START)
    terms = [*GLOSSARY[:3], Term("D", ("d",), pin=True)]
    change = run_plan(hex_, terms, tmp_path)
    assert any("並べ替え" in line for line in change.summary)
    assert hex_.order == ["D", "A", "B", "C"]
    assert hex_.entries[2] == {"term": "B", "sounds_like": ["b1", "b2"]}  # 表記ごと入れ直す
    backups = list((tmp_path / "bk").glob("hex-vocabulary-*.json"))
    assert len(backups) == 1
    saved = json.loads(backups[0].read_text(encoding="utf-8"))["entries"]
    assert [e["term"] for e in saved] == ["A", "B", "C", "D"]  # 並べ替え前の状態
    assert run_plan(hex_, terms, tmp_path).empty  # 2 回目は何もしない


def test_new_term_and_pin_in_one_run(tmp_path: Path) -> None:
    hex_ = FakeHex(START)
    terms = [*GLOSSARY, Term("E", ("e",), pin=True)]
    run_plan(hex_, terms, tmp_path)
    assert hex_.order == ["E", "A", "B", "C", "D"]


@pytest.mark.parametrize("aliases", [(), ("アローエンピティ",)])
def test_sync_hyphenated_term(tmp_path: Path, aliases: tuple[str, ...]) -> None:
    hex_ = FakeHex([])
    terms = [Term("ordinary"), Term("--allow-empty", aliases)]
    run_plan(hex_, terms, tmp_path)
    options = ["--sounds-like", aliases[0]] if aliases else []
    assert ["vocabulary", "add", *options, "--", "--allow-empty"] in hex_.calls
    assert hex_.entries == [
        {"term": "ordinary", "sounds_like": []},
        {"term": "--allow-empty", "sounds_like": list(aliases)},
    ]
    assert run_plan(hex_, terms, tmp_path).empty


def test_reorder_and_restore_hyphenated_term(tmp_path: Path) -> None:
    hex_ = FakeHex([("--allow-empty", ["アローエンピティ"]), ("ordinary", [])])
    terms = [Term("--allow-empty", ("アローエンピティ",)), Term("ordinary", pin=True)]
    run_plan(hex_, terms, tmp_path)
    assert hex_.order == ["ordinary", "--allow-empty"]
    assert run_plan(hex_, terms, tmp_path).empty
    backup_path = next((tmp_path / "bk").glob("hex-vocabulary-*.json"))
    backup = json.loads(backup_path.read_text(encoding="utf-8"))["entries"]
    remove = ["vocabulary", "remove", "--", "--allow-empty"]
    add = ["vocabulary", "add", "--sounds-like", "アローエンピティ", "--", "--allow-empty"]
    index = hex_.calls.index(remove)
    assert hex_.calls[index + 1] == add

    hex_.calls.clear()
    change = plan_hex_restore(backup, hex_.entries, Path("hex.com"), hex_, tmp_path)
    for action in change.actions:
        action()
    assert remove in hex_.calls
    assert add in hex_.calls
    assert hex_.entries == backup
    assert run_plan(hex_, [terms[0], Term("ordinary")], tmp_path).empty


def test_comma_spelling_aborts_reorder(tmp_path: Path) -> None:
    hex_ = FakeHex([("A", ["x, y"]), ("B", [])])
    change = run_plan(hex_, [Term("A"), Term("B", pin=True)], tmp_path)
    assert any("中止" in line for line in change.summary)
    assert hex_.order == ["A", "B"]


def test_reorder_aborts_if_hex_differs_from_prediction(tmp_path: Path) -> None:
    hex_ = FakeHex(START)
    change = plan_hex(
        [*GLOSSARY[:3], Term("D", ("d",), pin=True)],
        hex_.settings(),
        Path("hex.com"),
        hex_,
        tmp_path / "bk",
    )
    hex_.entries.append({"term": "Z", "sounds_like": []})  # 予測後に Hex 側が変わった
    try:
        for action in change.actions:
            action()
    except RuntimeError as exc:
        assert "中止" in str(exc)
    else:
        raise AssertionError("expected abort")
    assert hex_.order == ["A", "B", "C", "D", "Z"]  # 何も消していない


def test_restore_brings_back_contents_and_order(tmp_path: Path) -> None:
    hex_ = FakeHex([("D", ["d"]), ("X", []), ("A", ["a"])])
    backup = [{"term": t, "sounds_like": s} for t, s in START]
    change = plan_hex_restore(backup, hex_.entries, Path("hex.com"), hex_, tmp_path)
    for action in change.actions:
        action()
    assert hex_.entries == backup
    assert list(tmp_path.glob("hex-vocabulary-*.json"))  # 復元前の状態もバックアップ


def test_hex_restore_cli_dry_run(tmp_path: Path, monkeypatch, capsys) -> None:
    hex_ = FakeHex([("A", ["a"])])
    backup = tmp_path / "b.json"
    backup.write_text(json.dumps({"entries": [{"term": "B", "sounds_like": []}]}), "utf-8")
    import toranomaki.sync as sync_mod

    monkeypatch.setattr(sync_mod, "_run", hex_)
    monkeypatch.setattr(sync_mod.execute_restore, "__defaults__", (hex_,))
    code = toranomaki_main(["hex-restore", str(backup), "--hex-dir", str(tmp_path)])
    assert code == 0
    assert "dry-run" in capsys.readouterr().out
    assert hex_.order == ["A"]  # dry-run なので変えない


def test_prune_keeps_newest_and_ignores_other_files(tmp_path: Path) -> None:
    from toranomaki.sync import prune_backups

    names = [f"hex-vocabulary-2026112{d}-000000-000000.json" for d in range(10)]
    for n in names:
        (tmp_path / n).write_text("{}", encoding="utf-8")
    (tmp_path / "memo.json").write_text("{}", encoding="utf-8")  # toranomaki 以外のファイル
    removed = prune_backups(tmp_path, keep=3)
    assert [p.name for p in removed] == names[:7]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([*names[7:], "memo.json"])


def test_backup_prunes_old_ones(tmp_path: Path) -> None:
    from toranomaki.sync import backup_hex_vocabulary

    for d in range(5):
        (tmp_path / f"hex-vocabulary-2020010{d}-000000-000000.json").write_text("{}", "utf-8")
    new = backup_hex_vocabulary(Path("hex.com"), FakeHex(START), tmp_path, keep=2)
    left = sorted(p.name for p in tmp_path.iterdir())
    assert new.name in left and len(left) == 2  # 作ったばかりのものは必ず残る


def test_prompt_usage_matches_hex_counting() -> None:
    from toranomaki.sync import hex_prompt_usage

    assert hex_prompt_usage([]) == (0, 0)
    assert hex_prompt_usage(["ab", "cde"]) == (7, 2)  # "ab, cde"
    names = ["x" * 248, "y" * 248, "z"]  # 248 + 2 + 248 = 498、次の ", z" で 501 → 2 語まで
    assert hex_prompt_usage(names) == (498, 2)
    assert hex_prompt_usage(["x" * 500]) == (500, 1)  # ちょうど 500 は入る
    assert hex_prompt_usage(["x" * 501]) == (0, 0)


def test_notes_warn_and_list_overflowing_terms() -> None:
    from toranomaki.sync import hex_prompt_notes

    assert len(hex_prompt_notes(["a", "b"])) == 1  # 余裕があれば使用量だけ
    near = hex_prompt_notes(["x" * 460])
    assert "残りが 40 文字" in near[1]
    over = hex_prompt_notes(["x" * 300, "y" * 300])
    assert "1/2 語" in over[0] and "'" + "y" * 300 + "'" in over[1]


def test_usage_is_shown_even_without_changes(tmp_path: Path, capsys) -> None:
    from toranomaki.sync import _report_and_apply

    hex_ = FakeHex(START)
    run_plan(hex_, GLOSSARY, tmp_path)  # 置き換えを入れて同期済みにする
    change = plan_hex(GLOSSARY, hex_.settings(), Path("hex.com"), hex_, tmp_path)
    assert change.empty
    _report_and_apply([change], apply=False)
    out = capsys.readouterr().out
    assert "変更なし" in out and "認識寄せの枠: 10/500 文字（4/4 語" in out
