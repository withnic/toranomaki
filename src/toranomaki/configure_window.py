"""Tkinter の辞書設定画面。"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from subprocess import SubprocessError
from tkinter import messagebox, ttk

import yaml

from toranomaki.configure import ScopeEditor, installed_apps, run_sync
from toranomaki.glossary import GLOBAL_SCOPE, GlossaryError, parse_glossary


def execute(target: Path) -> int:
    try:
        editor = ScopeEditor(target)
        root = tk.Tk()
        ScopeWindow(root, editor)
        root.mainloop()
    except (GlossaryError, OSError, UnicodeError, yaml.YAMLError, tk.TclError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


class ScopeWindow:
    def __init__(self, root: tk.Tk, editor: ScopeEditor) -> None:
        self.root = root
        self.editor = editor
        self.apps: list[str] = []
        self.alias_rows: dict[str, tuple[int, str]] = {}
        root.title("Toranomaki — アプリ別の置き換え")
        root.geometry("900x680")
        root.minsize(750, 575)
        root.protocol("WM_DELETE_WINDOW", self.close)
        main = ttk.Frame(root, padding=18)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="アプリ別の置き換え", font=("Yu Gothic UI", 18, "bold")).pack(
            anchor="w"
        )
        ttk.Label(main, text=str(editor.path)).pack(anchor="w", pady=(2, 12))
        tabs = ttk.Notebook(main)
        tabs.pack(fill="both", expand=True)
        modes = ttk.Frame(tabs, padding=12)
        aliases = ttk.Frame(tabs, padding=12)
        tabs.add(modes, text="アプリとモード")
        tabs.add(aliases, text="別名の適用先")
        self.build_modes(modes)
        self.build_aliases(aliases)
        footer = ttk.Frame(main)
        footer.pack(fill="x", pady=(12, 0))
        self.status = tk.StringVar(value="「Hex と同期」で保存済みの辞書との差分を確認できます。")
        ttk.Label(footer, textvariable=self.status).pack(side="left")
        ttk.Button(footer, text="Hex と同期", command=self.preview_sync).pack(side="right")
        ttk.Button(footer, text="辞書に保存", command=self.save).pack(side="right", padx=(0, 8))
        self.refresh_modes()
        self.refresh_aliases()
        root.after(100, self.discover_apps)

    def build_modes(self, page: ttk.Frame) -> None:
        heading = ttk.Frame(page)
        heading.pack(fill="x")
        ttk.Label(heading, text="登録済みモード").pack(side="left")
        self.mode_picker = ttk.Combobox(heading, state="readonly", width=24)
        self.mode_picker.pack(side="left", padx=8)
        self.mode_picker.bind("<<ComboboxSelected>>", self.load_mode)
        ttk.Button(heading, text="新しいモード", command=self.new_mode).pack(side="left")
        name_row = ttk.Frame(page)
        name_row.pack(fill="x", pady=(10, 12))
        ttk.Label(name_row, text="モード名").pack(side="left")
        self.mode_name = tk.StringVar()
        ttk.Entry(name_row, textvariable=self.mode_name, width=28).pack(side="left", padx=8)
        columns = ttk.Frame(page)
        columns.pack(fill="both", expand=True)
        left = ttk.Frame(columns)
        right = ttk.Frame(columns)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="スタートメニューのアプリ").pack(anchor="w")
        self.app_query = tk.StringVar()
        ttk.Entry(left, textvariable=self.app_query).pack(fill="x", pady=4)
        self.app_query.trace_add("write", self.filter_apps)
        self.app_list = tk.Listbox(left, height=9, exportselection=False, selectmode="extended")
        self.app_list.pack(fill="both", expand=True)
        self.app_list.bind("<Double-Button-1>", lambda _: self.add_apps())
        left_buttons = ttk.Frame(left)
        left_buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(left_buttons, text="選択を追加", command=self.add_apps).pack(side="left")
        ttk.Button(left_buttons, text="入力名を追加", command=self.add_app_name).pack(
            side="left", padx=6
        )
        ttk.Label(right, text="このモードの対象アプリ").pack(anchor="w")
        self.selected_apps = tk.Listbox(
            right, height=9, exportselection=False, selectmode="extended"
        )
        self.selected_apps.pack(fill="both", expand=True, pady=(4, 0))
        ttk.Button(right, text="選択を外す", command=self.remove_apps).pack(anchor="w", pady=(6, 0))
        ttk.Button(page, text="モードを更新", command=self.update_mode).pack(
            anchor="e", pady=(10, 0)
        )

    def build_aliases(self, page: ttk.Frame) -> None:
        ttk.Label(page, text="正しい表記・別名を検索（Ctrl または Shift で複数選択）").pack(
            anchor="w"
        )
        filters = ttk.Frame(page)
        filters.pack(fill="x", pady=(4, 8))
        self.alias_query = tk.StringVar()
        ttk.Entry(filters, textvariable=self.alias_query).pack(side="left", fill="x", expand=True)
        self.alias_query.trace_add("write", self.refresh_aliases)
        ttk.Label(filters, text="表示").pack(side="left", padx=(12, 4))
        self.scope_filter = ttk.Combobox(
            filters,
            state="readonly",
            values=(
                "すべての別名",
                "全アプリ適用を除く",
                "文脈で読み替えるだけ",
                "反映を見送った別名",
                "選択したモードだけ",
                "全アプリに適用",
            ),
            width=24,
        )
        self.scope_filter.current(0)
        self.scope_filter.pack(side="left")
        self.scope_filter.bind("<<ComboboxSelected>>", lambda _: self.refresh_aliases())
        table = ttk.Frame(page)
        table.pack(fill="both", expand=True)
        self.alias_table = ttk.Treeview(
            table,
            columns=("term", "alias", "scope"),
            show="headings",
            selectmode="extended",
            height=7,
        )
        for column, heading in (("term", "正しい表記"), ("alias", "別名"), ("scope", "適用先")):
            self.alias_table.heading(column, text=heading)
            self.alias_table.column(column, width=170)
        self.alias_table.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.alias_table.yview)
        scroll.pack(side="right", fill="y")
        self.alias_table.configure(yscrollcommand=scroll.set)
        self.alias_table.bind("<<TreeviewSelect>>", self.load_scope)
        fields = ttk.Frame(page)
        fields.pack(fill="x", pady=(10, 0))
        options = ttk.Frame(fields)
        options.pack(side="left", fill="y", padx=(0, 15))
        self.scope = tk.StringVar(value="inherit")
        for value, label in (
            ("inherit", "語の既定に従う"),
            ("global", "すべてのアプリ"),
            ("context", "文脈で読み替えるだけ"),
            ("modes", "選択したモードだけ"),
        ):
            ttk.Radiobutton(
                options, variable=self.scope, value=value, text=label, command=self.choose_scope
            ).pack(anchor="w")
        self.scope_modes = tk.Listbox(
            fields, height=4, exportselection=False, selectmode="extended"
        )
        self.scope_modes.pack(side="left", fill="both", expand=True)
        self.scope_modes.bind("<<ListboxSelect>>", lambda _: self.scope.set("modes"))
        self.update_scope_button = ttk.Button(
            fields, text="適用先を更新", command=self.update_scope
        )
        self.update_scope_button.pack(side="right", anchor="s", padx=(10, 0))
        self.scope_notice = tk.StringVar(value="一覧で別名を選んでください。")
        ttk.Label(page, textvariable=self.scope_notice, wraplength=660).pack(
            anchor="w", pady=(8, 0)
        )

    def discover_apps(self) -> None:
        try:
            self.apps = installed_apps()
        except (OSError, SubprocessError, ValueError):
            self.status.set("アプリ一覧を取得できませんでした。アプリ名は手入力できます。")
        self.filter_apps()

    def filter_apps(self, *_: str) -> None:
        query = self.app_query.get().strip().casefold()
        self.app_list.delete(0, tk.END)
        for app in self.apps:
            if query in app.casefold():
                self.app_list.insert(tk.END, app)

    def add_apps(self) -> None:
        for index in self.app_list.curselection():
            self.append_app(self.app_list.get(index))

    def add_app_name(self) -> None:
        name = self.app_query.get().strip()
        if name:
            self.append_app(name)

    def append_app(self, name: str) -> None:
        if name.casefold() not in {app.casefold() for app in self.selected_apps.get(0, tk.END)}:
            self.selected_apps.insert(tk.END, name)

    def remove_apps(self) -> None:
        for index in reversed(self.selected_apps.curselection()):
            self.selected_apps.delete(index)

    def new_mode(self) -> None:
        self.mode_picker.set("")
        self.mode_name.set("")
        self.selected_apps.delete(0, tk.END)

    def load_mode(self, _: tk.Event[ttk.Combobox]) -> None:
        name = self.mode_picker.get()
        self.mode_name.set(name)
        self.selected_apps.delete(0, tk.END)
        for app in self.editor.document["hex_modes"][name]:
            self.selected_apps.insert(tk.END, app)

    def update_mode(self) -> None:
        try:
            self.editor.set_mode(self.mode_name.get(), list(self.selected_apps.get(0, tk.END)))
        except GlossaryError as exc:
            messagebox.showerror("モードを更新できません", str(exc), parent=self.root)
            return
        self.refresh_modes()
        self.mode_picker.set(self.mode_name.get().strip())
        self.status.set("モードを更新しました。「辞書に保存」で書き込みます。")

    def refresh_modes(self) -> None:
        names = tuple(self.editor.document.get("hex_modes", {}))
        self.mode_picker.configure(values=names)
        self.scope_modes.delete(0, tk.END)
        for name in names:
            self.scope_modes.insert(tk.END, name)
        if self.alias_table.selection():
            self.load_scope()

    def refresh_aliases(self, *_args: str) -> None:
        chosen = self.alias_table.selection()
        rows = self.alias_table.get_children()
        if rows:
            self.alias_table.delete(*rows)
        self.alias_rows.clear()
        query = self.alias_query.get().strip().casefold()
        view = self.scope_filter.current()
        terms, _ = parse_glossary(self.editor.document, str(self.editor.path))
        for index, term in enumerate(terms):
            scopes = dict(term.alias_modes)
            for alias_number, alias in enumerate(term.aliases):
                if alias == term.term or (
                    query not in alias.casefold() and query not in term.term.casefold()
                ):
                    continue
                scope = scopes.get(alias)
                global_alias = scope == (GLOBAL_SCOPE,) or (scope is None and not term.context_only)
                contextual_alias = scope == () or (scope is None and term.context_only)
                matches_filter = (
                    True,
                    not global_alias,
                    contextual_alias,
                    contextual_alias and "反映を断られた" in term.note,
                    not global_alias and not contextual_alias,
                    global_alias,
                )
                if not matches_filter[max(0, view)]:
                    continue
                if scope is None:
                    label = "既定・文脈のみ" if term.context_only else "既定・全アプリ"
                elif scope == (GLOBAL_SCOPE,):
                    label = "すべてのアプリ"
                else:
                    label = ", ".join(scope) if scope else "文脈のみ"
                row = f"{index}:{alias_number}"
                self.alias_rows[row] = (index, alias)
                self.alias_table.insert("", tk.END, iid=row, values=(term.term, alias, label))
        restore = [row for row in chosen if row in self.alias_rows]
        if restore:
            self.alias_table.selection_set(*restore)

    def load_scope(self, _: tk.Event[ttk.Treeview] | None = None) -> None:
        selected = self.alias_table.selection()
        if not selected:
            return
        scopes = [
            self.editor.document["terms"][index].get("alias_modes", {}).get(alias)
            for index, alias in (self.alias_rows[row] for row in selected)
        ]
        scope = scopes[0]
        self.scope_modes.selection_clear(0, tk.END)
        if any(value != scope for value in scopes[1:]):
            self.scope.set("")
        elif scope is None:
            self.scope.set("inherit")
        elif scope == GLOBAL_SCOPE:
            self.scope.set("global")
        elif not scope:
            self.scope.set("context")
        else:
            self.scope.set("modes")
            for position, mode in enumerate(self.scope_modes.get(0, tk.END)):
                if mode in scope:
                    self.scope_modes.selection_set(position)

    def choose_scope(self) -> None:
        if self.scope.get() != "modes":
            return
        if self.scope_modes.size() == 1:
            self.scope_modes.selection_set(0)
        if not self.scope_modes.size():
            self.scope_notice.set(
                "モードがありません。「アプリとモード」で「モードを更新」を押して追加してください。"
            )
        elif not self.scope_modes.curselection():
            self.scope_notice.set("右の一覧で適用先のモードを選んでください。")

    def update_scope(self) -> None:
        selected = self.alias_table.selection()
        if not selected:
            self.scope_notice.set("先に上の一覧で変更する別名をクリックしてください。")
            return
        scope: str | list[str] | None
        match self.scope.get():
            case "global":
                scope = GLOBAL_SCOPE
            case "context":
                scope = []
            case "modes":
                self.choose_scope()
                scope = [
                    self.scope_modes.get(position) for position in self.scope_modes.curselection()
                ]
                if not scope:
                    return
            case "inherit":
                scope = None
            case _:
                self.scope_notice.set("選択した別名の適用先が異なります。適用先を選んでください。")
                return
        changed = 0
        for row in selected:
            index, alias = self.alias_rows[row]
            entry = self.editor.document["terms"][index]
            if entry.get("alias_modes", {}).get(alias) != scope:
                self.editor.set_scope(index, alias, scope)
                changed += 1
        if not changed:
            self.scope_notice.set("選択した別名の適用先はすでにこの設定です。")
            return
        self.refresh_aliases()
        self.scope_notice.set(f"{changed} 件の別名の適用先を変更しました。")
        self.status.set("適用先を更新しました。「辞書に保存」で書き込みます。")

    def save(self) -> None:
        try:
            backup = self.editor.save()
        except (OSError, GlossaryError, yaml.YAMLError) as exc:
            messagebox.showerror("保存できません", str(exc), parent=self.root)
            return
        self.status.set(
            "辞書に保存しました。「Hex と同期」で差分を確認できます。" if backup else "変更なし"
        )

    def close(self) -> None:
        if not self.editor.dirty or messagebox.askokcancel(
            "保存していない変更", "辞書に保存せず閉じますか？", parent=self.root
        ):
            self.root.destroy()

    def preview_sync(self) -> None:
        if self.editor.dirty:
            messagebox.showinfo(
                "Hex と同期", "先に「辞書に保存」を押してください。", parent=self.root
            )
            return
        try:
            preview = run_sync(self.editor.path)
        except OSError as exc:
            messagebox.showerror("同期を開始できません", str(exc), parent=self.root)
            return
        window = tk.Toplevel(self.root)
        window.title("Hex と同期")
        window.geometry("760x490")
        window.transient(self.root)
        window.grab_set()
        content = ttk.Frame(window, padding=12)
        content.pack(fill="both", expand=True)
        output = tk.Text(content, wrap="word", padx=8, pady=8)
        scroll = ttk.Scrollbar(content, orient="vertical", command=output.yview)
        output.configure(yscrollcommand=scroll.set)
        output.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        report_prefix = "vocabulary-candidates: "
        candidates: list[tuple[str, str]] = []
        for line in preview.stdout.splitlines():
            if line.startswith(report_prefix):
                candidates = [
                    (term, alias) for term, alias in json.loads(line[len(report_prefix) :])
                ]

        def show_result(text: str) -> None:
            output.configure(state="normal")
            output.delete("1.0", tk.END)
            output.insert(
                "1.0",
                "".join(
                    line
                    for line in text.splitlines(keepends=True)
                    if not line.startswith(report_prefix)
                ),
            )
            output.configure(state="disabled")

        show_result(preview.stdout)
        selected_aliases: tuple[tuple[str, str], ...] = ()
        alias_list: tk.Listbox | None = None
        check_selection: ttk.Button | None = None
        if candidates:
            choices = ttk.Frame(window, padding=(12, 0, 12, 8))
            choices.pack(fill="x")
            ttk.Label(choices, text="登録元が不明な認識用別名（外すものだけ選択）").pack(anchor="w")
            alias_list = tk.Listbox(
                choices,
                height=min(len(candidates), 5),
                selectmode="multiple",
                exportselection=False,
            )
            alias_list.pack(fill="x", pady=(4, 0))
            for term, alias in candidates:
                alias_list.insert(tk.END, f"{alias} → {term}")
        buttons = ttk.Frame(window, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="閉じる", command=window.destroy).pack(side="right")

        def apply_preview() -> None:
            apply_button.state(["disabled"])
            try:
                current = run_sync(self.editor.path, remove_aliases=selected_aliases)
                if current.returncode or current.stdout != preview.stdout:
                    show_result(
                        "差分が変わりました。閉じてもう一度同期を開いてください。\n\n"
                        + current.stdout
                    )
                    return
                result = run_sync(self.editor.path, apply=True, remove_aliases=selected_aliases)
            except OSError as exc:
                show_result(f"同期を実行できません: {exc}")
                return
            show_result(result.stdout)
            if alias_list is not None and check_selection is not None:
                alias_list.configure(state="disabled")
                check_selection.state(["disabled"])
            self.status.set(
                "Hex に反映しました。" if result.returncode == 0 else "同期に失敗しました。"
            )

        def update_apply_button() -> None:
            enabled = preview.returncode == 0 and "(dry-run) 反映するには" in preview.stdout
            apply_button.state(["!disabled"] if enabled else ["disabled"])

        def preview_selection() -> None:
            nonlocal preview, selected_aliases
            if alias_list is None:
                return
            selected_aliases = tuple(candidates[index] for index in alias_list.curselection())
            try:
                preview = run_sync(self.editor.path, remove_aliases=selected_aliases)
            except OSError as exc:
                show_result(f"同期を実行できません: {exc}")
                return
            show_result(preview.stdout)
            update_apply_button()

        apply_button = ttk.Button(buttons, text="Hex に反映", command=apply_preview)
        apply_button.pack(side="right", padx=(0, 8))
        update_apply_button()
        if alias_list is not None:
            alias_list.bind("<<ListboxSelect>>", lambda _: apply_button.state(["disabled"]))
            check_selection = ttk.Button(
                buttons, text="選択を差分に追加", command=preview_selection
            )
            check_selection.pack(side="left")
