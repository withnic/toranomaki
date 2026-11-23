from __future__ import annotations

from pathlib import Path

import pytest

from toranomaki import merge
from toranomaki.configure import ScopeEditor
from toranomaki.glossary import GlossaryError, load_glossary


def test_scope_editor_saves_modes_and_preserves_external_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(merge, "DEFAULT_BACKUP_DIR", tmp_path / "backups")
    path = tmp_path / "glossary.yaml"
    original = "# 辞書\nterms: [{term: Ruff, aliases: [ルフ], context_only: true}]\n"
    path.write_text(original, encoding="utf-8")
    editor = ScopeEditor(path)
    assert editor.save() is None
    editor.set_mode("Programming", ["Zed", "Visual Studio Code"])
    with pytest.raises(GlossaryError, match="割り当て済み"):
        editor.set_mode("Other", ["zed"])
    editor.set_scope(0, "ルフ", ["Programming"])
    backup = editor.save()
    assert backup is not None
    assert backup.read_text(encoding="utf-8") == original
    terms, modes = load_glossary(path)
    assert modes == {"Programming": ("Zed", "Visual Studio Code")}
    assert terms[0].alias_modes == (("ルフ", ("Programming",)),)
    assert editor.save() is None

    editor.set_scope(0, "ルフ", [])
    changed = "# 別セッションから変更\n" + path.read_text(encoding="utf-8")
    path.write_text(changed, encoding="utf-8")
    with pytest.raises(GlossaryError, match="変更されました"):
        editor.save()
    assert path.read_text(encoding="utf-8") == changed
