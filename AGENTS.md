# Toranomaki のプロジェクト指示

## 概要

Toranomaki は、Claude Code と Codex が育てる **共通の音声辞書の形式**を決め、**Hex へ橋渡しする**道具（Python / uv）。
録音や音声認識は自前で持たず、[Hex](https://github.com/anomalyco/hex)（普段の音声入力）に任せる。

- 辞書の正本は `~/.toranomaki/voice-glossary.yaml`。Claude Code と Codex が会話中に誤認識を見つけて育てる。
  Claude Code のユーザー指示には `templates/CLAUDE.voice.md`、Codex のユーザー指示には `templates/AGENTS.voice.md` を使う。
  両方を使うときも辞書は同じファイルを使う。導入手順は README を参照する。
- リポジトリ直下の `CLAUDE.md` と `AGENTS.md` には同じプロジェクト指示を置く。指示を変更したら両方を確認する。
- `toranomaki sync` が正本を Hex の形式に変換して配る（Hex は自分で管理していないので書き出す）。
- 自分で作るツールは、辞書を直接読めばよい。Toranomaki からは書き出さない。
  形式を変えるときは、README の「この形式を自分のツールで読むとき」も合わせて直す（読む側との約束なので）。
- README・`templates/`・コード・テストには個人の語（ユーザーのプロジェクト名など）を入れない。例は一般的な語だけにする。
- Hex のコードは改造しない（本家の更新に追従し続けるのが重いため）。つなぐのは公式の CLI とローカル API だけ。

## コマンド

| 用途 | コマンド |
| :---- | :---- |
| 依存の同期 | `uv sync` |
| テスト | `uv run pytest -v` |
| Lint / Format | `uv run ruff check . && uv run ruff format --check .` |
| 型チェック | `uvx basedpyright`（Windows の仮想環境を明示する場合は `uvx basedpyright --pythonpath .venv/Scripts/python.exe`） |
| 辞書の差分を見る | `uv run toranomaki sync` |
| 辞書を反映する | `uv run toranomaki sync --apply` |
| Hex vocabulary を戻す | `uv run toranomaki hex-restore <バックアップ> [--apply]` |

変更を終える前に型チェックも実行する。未解消の指摘があれば理由を伝える。

## 守ること

1. **正本は 1 つ**: 辞書を足すのは `~/.toranomaki/voice-glossary.yaml` だけ。各ツール側の辞書を手で直さない
   （直したくなったら正本を直して sync する）。
2. **既定は dry-run**: 書き込みは `--apply` を付けたときだけ。各ツールにある既存の項目は消さず、追加と修正だけを行う。
3. **`context_only` は機械的に置き換えない**: 一般語と衝突する読み替え（「扶養」→「不要」など）は、
   Hex の replacements・vocabulary にも、直接読むツールの置き換え・認識寄せにも使わない。アシスタントが文脈で読み替えるときに使う。
4. **Hex には公式の口からだけ書く**: `hex settings apply`（全部成功か何もしないか）と `hex vocabulary add`。
   `settings.json` などのファイルを直接書き換えない。
5. **Hex vocabulary を消すときは必ずバックアップと照合を先に**: 並べ替え・復元は「消して入れ直す」ので、
   実行前に `hex vocabulary list --json` をバックアップし、実際の並びが予測と一致しなければ中止する。
   並べ替えは 1 語ずつ「消す→すぐ入れる」（全部消してから入れない）。復元だけは今の語を全部消してから
   バックアップを入れ直す（消す語と入れる語が一致しないため。復元前の状態も必ずバックアップする）。
   カンマを含む表記は入れ直せないので中止する。実機での確認結果は README の「動作確認の記録」。
6. **Whisper に事前に教える語には上限がある**: hotwords / vocabulary / initial_prompt は合わせて最大 223 トークン
   （日本語の語は 1 語で 5〜12 トークン）。Hex は vocabulary の先頭から 500 文字分だけ使う。置き換え（replacements）に上限はない。
7. **テストはオフラインで完結させる**: Hex を実際に動かさない（CLI 呼び出しはフェイクに差し替える）。
