# Toranomaki

[![CI](https://github.com/withnic/toranomaki/actions/workflows/ci.yml/badge.svg)](https://github.com/withnic/toranomaki/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> **English summary**: Toranomaki keeps a shared voice-input glossary for Claude Code and Codex.
> When either assistant spots a speech recognition error in your instructions, it records the fix in
> `~/.toranomaki/voice-glossary.yaml`; `toranomaki sync` then pushes those fixes to
> [Hex](https://github.com/anomalyco/hex) as replacements and vocabulary.
> It is built for Japanese dictation, and the docs and templates are in Japanese.

Claude Code と Codex が育てる共通の音声辞書（`~/.toranomaki/voice-glossary.yaml`）の形式を決め、Hex へ橋渡しします。
録音や音声認識は持ちません（Hex に任せます）。

```text
~/.toranomaki/voice-glossary.yaml   ← 正本。Claude Code と Codex が会話中に誤認識を見つけて追記する
   ├─▶ Claude Code   ~/.claude/CLAUDE.md の @ 参照から読み込む
   ├─▶ Codex        ~/.codex/AGENTS.md の指示に従って辞書ファイルを読む
   ├─▶ Hex           置き換え（replacements）と vocabulary   ← toranomaki sync（Hex は自分で管理していないので書き出す）
   └─▶ 自分のツール   この形式のまま直接読む（下の「この形式を自分のツールで読むとき」）
```

自分で管理しているツールは、辞書を直接読む方が簡単で確実です（書き出しのずれが起きず、`sync` も要らない）。
書き出すのは、改造しない方針の Hex だけです。

## 音声入力を使うほど辞書が育つ

Hex のような音声入力で Claude Code や Codex に指示すると、誤認識（「プロンプツ」= prompts、「扶養」= 不要 など）が
混ざります。アシスタントが文脈で読み替えて辞書に記録し、Toranomaki がその辞書から Hex に反映します。

```text
話す（Hex）──▶ 誤認識まじりの文 ──▶ Claude Code / Codex が文脈で読み替えて作業する
                                         │ 新しい誤認識なら voice-glossary.yaml に追記（「辞書に追加: X → Y」）
                                         ▼
                              toranomaki sync --apply ──▶ Hex の置き換え・認識寄せに反映
                                                        （ほかのアプリへの入力にも効く）
```

辞書に記録した読み替えは、次の会話でも使えます。Hex に反映した置き換えは、ほかのアプリでの音声入力にも効きます。

- **渡す前に LLM で清書しない**。Claude Code では誤認識や独特の語順を含む生の発話を文脈から読めました。
  一方、ローカル LLM（7b〜32b）の清書は意味を変えたり内容を足したりしました。トークンもほぼ減りません
  （発話は数百トークン、1 往復は数万）。
- **一般語とぶつかる読み替えは機械的に置き換えない**: 「扶養」→「不要」を置き換えると、本当に「扶養」と
  言ったときに壊れます。`context_only: true` にして、アシスタントが文脈で読み替えるときにだけ使います。
- **Hex の vocabulary だけでは誤認識は直らない**: vocabulary は認識寄せ（Labs の vocabulary biasing）と
  AI 書き直し用で、どちらもオフだと何も起きません。確実に直すには置き換え（replacements）に入れます。

## 自分の環境に導入する

[Hex](https://github.com/anomalyco/hex)、[uv](https://docs.astral.sh/uv/)、Claude Code または Codex を用意します。

### 共通辞書を用意する

Windows PowerShell でリポジトリを取得し、辞書がまだなければ雛形をコピーします。

```powershell
git clone https://github.com/withnic/toranomaki.git
cd toranomaki
New-Item -ItemType Directory -Force "$HOME/.toranomaki" | Out-Null
if (-not (Test-Path "$HOME/.toranomaki/voice-glossary.yaml")) {
    $legacyGlossary = "$HOME/.claude/voice-glossary.yaml"
    if (Test-Path $legacyGlossary -PathType Leaf) {
        Copy-Item $legacyGlossary "$HOME/.toranomaki/voice-glossary.yaml"
    } else {
        Copy-Item templates/voice-glossary.yaml "$HOME/.toranomaki/voice-glossary.yaml"
    }
}
```

既存ユーザーの場合、この手順で旧辞書を新しい場所へコピーします。続けて下の手順で音声入力の節を更新し、
旧パスへの参照も差し替えてください。新しいセッションで辞書を読めることを確認したら、以後は新しいファイルに追記します。
`sync` は新しいファイルがまだない間、旧パスを使います。`--glossary` で指定したパスは常に優先します。

### 使うアシスタントに指示を入れる

| 使い方 | 追記するテンプレート | 追記先 |
|---|---|---|
| Claude Code のみ | [CLAUDE.voice.md](templates/CLAUDE.voice.md) | `~/.claude/CLAUDE.md` |
| Codex のみ | [AGENTS.voice.md](templates/AGENTS.voice.md) | `~/.codex/AGENTS.md` |
| 両方使う | 上の両方 | それぞれの指示ファイル。辞書は同じ1ファイル |

テンプレートの本文を追記してください。指示ファイルがなければ作成し、音声入力の節が既にあればその節を更新します。

- Claude Code はテンプレート末尾の `@~/.toranomaki/voice-glossary.yaml` から辞書を読み込みます。
- Codex はテンプレートの指示に従って辞書ファイルを開きます。カスタムの `CODEX_HOME` を使う場合はその配下に置きます。同じ場所に `AGENTS.override.md` がある場合、そちらが優先されます。 [Codex の指示ファイル](https://developers.openai.com/codex/guides/agents-md)
- 併用する場合、どちらかが辞書に追記した語をもう一方でも使えます。辞書の編集は片方ずつ行い、両方を開いているときは、もう一方にも更新された辞書を読み直すよう伝えてください。

新しいセッションを開き、「音声辞書を読んで、登録語を一つ教えて」と頼むと設定を確認できます。その後は普段どおり音声で指示してください。誤認識を新しく記録したときは「辞書に追加: X → Y」と伝えます。Hex への反映は下の「使い方」を参照してください。

## 使い方

```powershell
uv sync
uv run toranomaki sync           # 何が変わるかを見る（何も書き込まない）
uv run toranomaki sync --apply   # 反映する
```

- Hex は起動している必要があります（公式 CLI の `hex settings apply` と `hex vocabulary add` で書き込みます）。
- Hex の Labs で `vocabulary-biasing` をオンにすると、登録語が音声認識に使われます（`hex labs on vocabulary-biasing`）。

### アプリ別に文字置き換えを使う

Windows では `uv run toranomaki configure` で設定画面を開けます。Tkinter を使える Python が必要です。

1. **アプリとモード**で、モード名を入力し、スタートメニューの一覧からアプリを検索して選びます。一覧にないアプリ名は手入力できます。「モードを更新」で編集内容を取り込みます。
2. **別名の適用先**で別名を検索し、適用先を選んで「適用先を更新」を押します。Ctrl または Shift で複数の別名やモードを選べます。「表示」で全アプリ適用を除いたり、反映を見送った別名だけに絞ったりできます。
3. **辞書に保存**を押し、**Hex と同期**で差分を確認してから **Hex に反映** を押します。別の辞書を編集する場合は `configure --target <パス>` を使えます。

共通辞書の `hex_modes` にモード名と対象アプリを登録し、各語の `alias_modes` で別名ごとの適用先を選べます。
Zed だけで使う場合はアプリ欄を `[Zed]` にします。VS Code も使う場合は同じモードに追加できます。

```yaml
hex_modes:
  Programming: [Zed, "Visual Studio Code"]
terms:
  - term: "ruff"
    aliases: ["ルフ", "パイスルフ"]
    context_only: true
    alias_modes:
      "ルフ": [Programming]
      "パイスルフ": []
```

- モード名のリストは、そのモードでだけ置き換える指定です。空リストは文脈でだけ読み替える指定です。文字列の `global` は全アプリで置き換える指定です。個別指定のない別名には従来どおり `context_only` が効きます。
- Hex に同名のモードがあれば、そのモードを更新します。すでに `Zed` というモードを使っているなら、例の `Programming` を `Zed` に読み替えてください。別名のモードが同じアプリを対象にしている場合は競合として中止します。
- `toranomaki sync` で各モードの追加や解除を確認し、`--apply` で反映します。別名の適用先を明示すると、正本と同じ置き換えを共通設定や `hex_modes` に指定した以前のモードから解除できます。解除したい別名は、明示的に `[]` にしてください。変更前の音声入力設定はバックアップします。
- Windows でアプリ別に切り替わるのは文字置き換えです。別名をアプリ限定や文脈限定にしたとき、Toranomaki が登録したものは共通 Vocabulary から外す差分に含めます。登録元が不明な別名は、「Hex と同期」の一覧で外すものを選び、「選択を差分に追加」を押してください。対象語とほかの別名は維持し、変更前の Vocabulary はバックアップします。

## Web 版 Gemini などで集めた訂正を取り込む

音声認識の誤りを文脈から見つけられる AI は、辞書の「先生」になれます。Web 版 Gemini や ChatGPT などで個別に集めた訂正を `toranomaki merge` で共通辞書へ統合し、`sync` で Hex に還元できます。

1. [Web 版 Gemini](https://gemini.google.com/) で Google Workspace 連携を有効にし、Google ドライブに `voice-glossary-gemini (Toranomaki)` というドキュメントを用意します。[辞書の雛形](templates/voice-glossary.yaml) に沿った YAML を、言語タグが `yaml` のコードブロックに置きます。
2. Gemini の設定で「パーソナル インテリジェンス」→「Gemini への指示」を開き、[Gemini 用テンプレート](templates/GEMINI.voice.md) を貼り付けます。専用の会話にしたい場合は、Gem のカスタム指示と知識ファイルにも設定できます。
3. 普段どおり音声で指示し、誤認識を読み替えたら辞書用ドキュメントの更新を Gemini に頼みます。共有文書などで確認が求められたら編集内容を確認し、直接編集できない場合は Gemini が出力した YAML をコピーします。[Gemini の Workspace 操作](https://support.google.com/gemini/answer/17094507)
4. Google Docs から「ファイル → ダウンロード → Markdown（.md）」で保存するか、対象を選択して「Markdown としてコピー」を使います。[Google Docs の Markdown 機能](https://support.google.com/docs/answer/12014036)

```powershell
uv run toranomaki merge "$HOME/Downloads/voice-glossary-gemini.md"
uv run toranomaki merge "$HOME/Downloads/voice-glossary-gemini.md" chatgpt.yaml --apply
uv run toranomaki merge gemini.md --target ./custom-glossary.yaml
```

入力は YAML または `yaml` / `yml` コードブロックを含む Markdown です。複数入力は指定順に読み、`-` は標準入力を表します。既定のマージ先は `~/.toranomaki/voice-glossary.yaml` です。差分と衝突の警告を確認してから `--apply` を付けてもう一度実行してください。

正本で `context_only: true` にした語は、取り込み元で設定を外してもそのままです。Hex への反映を再開するときは、正本側の指定も見直してください。

| OS | クリップボードから差分を確認するコマンド |
|---|---|
| Windows PowerShell | `Get-Clipboard \| uv run toranomaki merge -` |
| macOS | `pbpaste \| uv run toranomaki merge -` |
| Linux（X11） | `xclip -o \| uv run toranomaki merge -` |
| Linux（Wayland） | `wl-paste \| uv run toranomaki merge -` |

変更を書き込むときは、既存の正本をバックアップします。Windows では `%LOCALAPPDATA%\toranomaki\backups\voice-glossary-*.yaml` に直近3世代を残します。Hex への反映は取り込み後に `uv run toranomaki sync` で確認し、`sync --apply` で実行します。

## 辞書の書き方

```yaml
terms:
  - term: "Claude Code"          # 正しい表記
    aliases: ["クロードコード"]    # 実際に出てきた誤認識
  - term: "不要"
    aliases: ["扶養"]
    context_only: true           # 一般語と衝突するので文脈でのみ読み替える
    note: "「扶養なら〜」= 不要なら"
```

| 辞書の項目 | Hex での使われ方 |
|---|---|
| 通常の語の `aliases` | 置き換え（`matched_phrase` → `output`） |
| 通常の語の `term` | vocabulary（認識寄せ） |
| `pin: true` | vocabulary の先頭へ並べ替え（下の「優先度」） |
| `context_only: true` の語 | 送らない（アシスタントが文脈で読み替える） |
| `note` | 使わない（人とアシスタント向けのメモ） |

Hex にある既存の項目は消しません。

反映するか聞かれて断った語には、アシスタントが `context_only: true` を付け、`note` に断ったことを書きます。
どのツールも機械的には使わなくなり、次の `sync` でも勧められません。あとで「やっぱり反映して」と言えば外します。

### この形式を自分のツールで読むとき

- `terms` のリスト。各要素は文字列（`"Kubernetes"` = 語だけ）か、`term` を持つマッピング。
- `aliases` は文字列 1 つかリスト。`context_only` / `pin` は真偽値（既定 false）。`note` は文字列。
- `hex_modes` は Hex 用のモード名とアプリ名の対応表、`alias_modes` は別名ごとの Hex の適用先。直接読むツールが Hex の適用先を解釈できない場合、個別の適用先を持つ別名は機械的な置き換えに使わない。
- 知らないキーは無視する（形式は後から増えることがある）。
- **`context_only: true` の語は、機械的な置き換えにも認識寄せにも使わない。**
- 長い誤認識から順に置き換える（「クラウドスパナー」を「スパナー」より先に）。
- 辞書はアシスタントが会話中に書き換えるので、壊れた状態で保存されることがある。読む側は止まらずに、直前の内容を使い続ける。

## 優先度（pin）と、Hex vocabulary の並べ替え

Hex は vocabulary を**先頭から**、語をつないで 500 文字に収まる分だけ認識寄せに使います（溢れた後ろの語は
使われません）。新しい語は末尾に足されるので、何もしないと「古い語ほど優先」になります。

辞書で `pin: true` を付けた語は、`toranomaki sync` が vocabulary の先頭へ並べ替えます。
`toranomaki sync` は毎回、枠の使用量（例: `認識寄せの枠: 338/500 文字（31/31 語が使われる）`）を表示し、
450 文字を超えると注意、枠から外れる語があればその語を挙げて警告します。Hex には並べ替えの
コマンドがないので、「消してすぐ入れ直すと末尾に回る」ことを使って、1 語ずつ入れ直します。

- 並べ替えの前に、Hex の vocabulary を `%LOCALAPPDATA%\toranomaki\backups\hex-vocabulary-*.json` にバックアップします。
- 実際の並びが予測と違えば、何も消さずに中止します。
- カンマを含む表記がある語は入れ直すと壊れる（`--sounds-like` がカンマ区切り）ので、並べ替えを中止します。
- 戻すときは `uv run toranomaki hex-restore <バックアップ> --apply`（中身と並びを丸ごと戻す。これも既定は差分表示のみ）。

### 困ったとき（並べ替えや復元で何かおかしくなったら）

1. まず `uv run toranomaki sync`（差分表示のみ）で、辞書と Hex のずれを確認する。
2. 戻したい時点のバックアップを選ぶ。`%LOCALAPPDATA%\toranomaki\backups\` に、並べ替え・復元のたびに
   `hex-vocabulary-<日時>.json` が作られる（中身は `hex vocabulary list --json` そのもの）。
   **新しい 3 個だけが残り、それより古いものは自動で消える**（壊れた状態で上書きしたときや、復元をやり直したいときのために 1 個より多く残す）。残したいものは別の場所にコピーしておく。
3. `uv run toranomaki hex-restore <バックアップ>` で差分を確認し、`--apply` で戻す。復元の前に、その時点の状態も
   別のバックアップとして保存されるので、復元自体もやり直せる。
4. 置き換え（replacements）は並べ替え・復元では触らない。おかしいときは `uv run toranomaki sync --apply` で辞書から作り直す。

### 動作確認の記録

2026-11-21、Hex 3.4.0（Windows）、vocabulary 31 語・置き換え 53 件の実データで確認した。

| 操作 | 結果 |
|---|---|
| 「Claude Code」（19 番目）に `pin: true` → `sync --apply` | 先頭に移動。31 語を入れ直して **2.2 秒**。語数・各語の表記・他の語の並び・置き換えはすべて変化なし |
| 続けて `sync`（差分表示） | 「変更なし」（2 回目は何もしない） |
| `hex-restore <並べ替え前のバックアップ> --apply` | 並べ替え前と完全に一致（中身・並び）。**2.1 秒**。復元前の状態もバックアップされた |
| もう一度 `sync --apply` | 1 回目の並べ替え後と完全に一致 |

確認方法: 各操作の前後で `hex vocabulary list --json` と `hex settings get dictation_processing.default_mode --json`
を保存して比較した。語数が増えると、入れ直す語数に比例して時間が延びる（1 語あたり約 70ms、上限 500 語で約 35 秒の見込み）。

## 注意: Whisper に事前に教えられる語には上限があります

Hex の vocabulary（認識寄せ）や、Whisper の hotwords に語を渡すツールでは、語が Whisper の前置きになります。
前置きは最大 223 トークンで、超えた分は切り捨てられます。英単語なら 1 語 2〜4 トークン、日本語やカタカナの長い語は
5〜12 トークンなので、実際に入るのは 30〜70 語程度です（Hex は自分で 500 文字に制限します）。
語が多いと、雑音を登録した語と聞き間違えやすくもなります。置き換え（replacements）に上限はありません。

## 開発

```powershell
uv run pytest -v
uv run ruff check . && uv run ruff format --check .
```

## ライセンス

MIT（[LICENSE](LICENSE)）
