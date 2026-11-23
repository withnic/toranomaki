"""Toranomaki エントリポイント。"""

from __future__ import annotations

import argparse
import sys

from toranomaki import configure, merge, sync


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="toranomaki", description="Toranomaki: 共通の音声辞書を Hex へ配る"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    configure.add_arguments(
        commands.add_parser("configure", help="open the app and alias scope editor")
    )
    merge.add_arguments(
        commands.add_parser("merge", help="merge YAML or Markdown into the glossary")
    )
    sync.add_arguments(
        commands.add_parser(
            "sync",
            help="push the shared voice glossary to Hex (dry-run by default)",
        )
    )
    sync.add_restore_arguments(
        commands.add_parser(
            "hex-restore",
            help="restore Hex vocabulary (contents and order) from a backup (dry-run by default)",
        )
    )
    args = parser.parse_args(argv)
    if args.command == "configure":
        try:
            from toranomaki import configure_window
        except ImportError:
            print("error: 設定画面には Tkinter を使える Python が必要です", file=sys.stderr)
            return 2
        return configure_window.execute(args.target)
    if args.command == "merge":
        return merge.execute(args)
    if args.command == "sync":
        return sync.execute(args)
    if args.command == "hex-restore":
        return sync.execute_restore(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
