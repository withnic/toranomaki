"""アプリ別の置き換えを共通辞書で設定する。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from toranomaki.glossary import DEFAULT_GLOSSARY, GLOBAL_SCOPE, GlossaryError, parse_glossary
from toranomaki.merge import import_for_review, save_glossary


def run_sync(
    target: Path, *, apply: bool = False, remove_aliases: tuple[tuple[str, str], ...] = ()
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-m",
        "toranomaki",
        "sync",
        "--glossary",
        str(target),
        "--vocabulary-report",
    ]
    for pair in remove_aliases:
        command.append("--remove-vocabulary-alias=" + json.dumps(pair, ensure_ascii=False))
    if apply:
        command.append("--apply")
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )


def installed_apps() -> list[str]:
    if os.name != "nt":
        return []
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::OutputEncoding = [Text.UTF8Encoding]::new(); "
            "@(Get-StartApps | Select-Object -ExpandProperty Name) | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=True,
    )
    names = json.loads(result.stdout)
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list):
        return []
    return sorted(
        {name for name in names if isinstance(name, str) and name.strip()}, key=str.casefold
    )


class ScopeEditor:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.original = self.path.read_bytes()
        raw = yaml.safe_load(self.original.decode("utf-8-sig"))
        if not isinstance(raw, dict) or not isinstance(raw.get("terms"), list):
            raise GlossaryError("辞書に terms のリストが必要です")
        self.document: dict[str, Any] = raw
        self.saved = deepcopy(self.document)
        self.imported_aliases: set[tuple[str, str]] = set()
        parse_glossary(self.document, str(self.path))

    @property
    def dirty(self) -> bool:
        return self.document != self.saved

    def set_mode(self, name: str, apps: list[str]) -> None:
        name = name.strip()
        if not name or name == GLOBAL_SCOPE or not apps:
            raise GlossaryError("モード名と対象アプリを指定してください（global は予約名です）")
        modes = self.document.get("hex_modes", {})
        occupied = {
            app.casefold()
            for existing, selected in modes.items()
            if existing != name
            for app in selected
        }
        if any(app.casefold() in occupied for app in apps):
            raise GlossaryError("別のモードに割り当て済みのアプリがあります")
        self.document.setdefault("hex_modes", {})[name] = apps.copy()

    def set_scope(self, index: int, alias: str, scope: str | list[str] | None) -> None:
        entry = self.document["terms"][index]
        if scope is None:
            if scopes := entry.get("alias_modes"):
                scopes.pop(alias, None)
                if not scopes:
                    entry.pop("alias_modes", None)
        else:
            entry.setdefault("alias_modes", {})[alias] = (
                scope.copy() if isinstance(scope, list) else scope
            )

    def save(self) -> Path | None:
        if not self.dirty:
            return None
        parse_glossary(self.document, str(self.path))
        backup = save_glossary(self.path, self.original, self.document)
        self.original = self.path.read_bytes()
        self.saved = deepcopy(self.document)
        return backup

    def stage_import(self, sources: Sequence[tuple[str, str]]) -> tuple[list[str], list[str], int]:
        draft = deepcopy(self.document)
        changes, warnings, added = import_for_review(draft, sources, str(self.path))
        parse_glossary(draft, str(self.path))
        self.document = draft
        self.imported_aliases.update(added)
        return changes, warnings, len(added)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", type=Path, default=DEFAULT_GLOSSARY)
