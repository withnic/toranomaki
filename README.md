# Toranomaki

Claude が育てる共通の音声辞書（`~/.claude/voice-glossary.yaml`）の形式を決め、Hex へ橋渡しします。
録音や音声認識は持ちません（Hex に任せます）。

```text
~/.claude/voice-glossary.yaml   ← 正本。Claude が会話中に誤認識を見つけて追記する（形式は Toranomaki が決める）
   ├─▶ Claude Code   ~/.claude/CLAUDE.md から読み込み、誤認識を読み替える
   ├─▶ Hex           置き換え（replacements）と vocabulary   ← toranomaki sync（Hex は自分で管理していないので書き出す）
   └─▶ 自分のツール   この形式のまま直接読む（下の「この形式を自分のツールで読むとき」）
```

自分で管理しているツールは、辞書を直接読む方が簡単で確実です（書き出しのずれが起きず、`sync` も要らない）。
書き出すのは、改造しない方針の Hex だけです。

## 仕組み: Claude を使うほど辞書が育つ

Hex のような音声入力で Claude Code に指示していると、誤認識（「プロンプツ」= prompts、「扶養」= 不要 など）が
混ざります。この仕組みの肝は、**その読み替えを Claude 自身に辞書へ記録させ、その辞書を音声入力ツールに戻す**ことです。

```text
話す（Hex）──▶ 誤認識まじりの文 ──▶ Claude が文脈で読み替えて作業する
                                         │ 新しい誤認識なら voice-glossary.yaml に追記（「辞書に追加: X → Y」）
                                         ▼
                              toranomaki sync --apply ──▶ Hex の置き換え・認識寄せに反映
                                                        （Claude 以外へ入力するときも直る）
```

使うほど辞書が育ち、Claude の読み替えも、Claude 以外へ入力するときの誤字も減っていきます。
これまでの検証で分かったことは次のとおりです。

- **Claude に渡す前に LLM で清書しない**: Claude は誤認識や独特の語順を含む生の発話を正しく読めます。
  一方、ローカル LLM（7b〜32b）の清書は意味を変えたり内容を足したりしました。トークンもほぼ減りません
  （発話は数百トークン、1 往復は数万）。
- **一般語とぶつかる読み替えは機械的に置き換えない**: 「扶養」→「不要」を置き換えると、本当に「扶養」と
  言ったときに壊れます。`context_only: true` にして、文脈が読める Claude だけに任せます。
- **Hex の vocabulary だけでは誤認識は直らない**: vocabulary は認識寄せ（Labs の vocabulary biasing）と
  AI 書き直し用で、どちらもオフだと何も起きません。確実に直すには置き換え（replacements）に入れます。

## 自分の環境に導入する

前提: [Hex](https://github.com/anomalyco/hex) と Claude Code を使っていること、[uv](https://docs.astral.sh/uv/) があること。

**いちばん大事なのは、`~/.claude/CLAUDE.md` に「誤認識を見つけたら辞書に追記する」という指示を入れることです。**
辞書を育てるのは Claude なので、この指示がないと辞書は空のままで、`toranomaki sync` は何も配れません。

1. リポジトリを取得する
   ```powershell
   git clone https://github.com/withnic/toranomaki.git
   cd toranomaki
   ```
2. 雛形を置く（既にある場合は中身を追記する）
   ```powershell
   copy templates\voice-glossary.yaml $HOME\.claude\voice-glossary.yaml
   Get-Content templates\CLAUDE.voice.md | Add-Content $HOME\.claude\CLAUDE.md
   ```
   - `templates/CLAUDE.voice.md` が Claude への指示（読み替えて辞書に記録する）、`voice-glossary.yaml` が辞書です。
   - 指示の末尾の `@~/.claude/voice-glossary.yaml` で、Claude は毎回辞書を読み込んでから発話を読みます。
   - `~/.claude/CLAUDE.md` はすべてのプロジェクトで読まれるので、どこで話しても辞書が育ちます。
3. あとは普段どおり音声で指示するだけです。Claude が誤認識に気づくと「辞書に追加: X → Y」と言って追記します。
4. ときどき Hex へ反映します（下の「使い方」）。Hex の Labs で `vocabulary-biasing` をオンにすると、
   正しい語の認識そのものも寄ります（`hex labs on vocabulary-biasing`）。

## 使い方

```powershell
uv sync
uv run toranomaki sync           # 何が変わるかを見る（何も書き込まない）
uv run toranomaki sync --apply   # 反映する
```

- Hex は起動している必要があります（公式 CLI の `hex settings apply` と `hex vocabulary add` で書き込みます）。

## 辞書の書き方

```yaml
terms:
  - term: "Claude Code"          # 正しい表記
    aliases: ["クロードコード"]    # 実際に出てきた誤認識
  - term: "不要"
    aliases: ["扶養"]
    context_only: true           # 一般語と衝突するので機械的に置き換えない（Claude だけが文脈で読み替える）
    note: "「扶養なら〜」= 不要なら"
```

| 辞書の項目 | Hex での使われ方 |
|---|---|
| 通常の語の `aliases` | 置き換え（`matched_phrase` → `output`） |
| 通常の語の `term` | vocabulary（認識寄せ） |
| `pin: true` | vocabulary の先頭へ並べ替え（下の「優先度」） |
| `context_only: true` の語 | 送らない（Claude だけが文脈で読み替える） |
| `note` | 使わない（人と Claude 向けのメモ） |

Hex にある既存の項目は消しません。

### この形式を自分のツールで読むとき

- `terms` のリスト。各要素は文字列（`"Kubernetes"` = 語だけ）か、`term` を持つマッピング。
- `aliases` は文字列 1 つかリスト。`context_only` / `pin` は真偽値（既定 false）。`note` は文字列。
- 知らないキーは無視する（形式は後から増えることがある）。
- **`context_only: true` の語は、機械的な置き換えにも認識寄せにも使わない。**
- 長い誤認識から順に置き換える（「クラウドスパナー」を「スパナー」より先に）。
- 辞書は Claude が会話中に書き換えるので、壊れた状態で保存されることがある。読む側は止まらずに、直前の内容を使い続ける。

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
