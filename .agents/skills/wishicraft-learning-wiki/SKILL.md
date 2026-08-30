---
name: wishicraft-learning-wiki
description: Generate or update Wishicraft's private repository-local Obsidian learning Wiki from canonical docs and historical Codex notes. Use for 「学習Wikiを更新して」「今回のPhaseの内容を学習Wikiへ反映して」「Wishicraftの学習ページを再生成して」 or `$wishicraft-learning-wiki`; not for ordinary documentation or implementation work.
metadata:
  short-description: Wishicraft学習Wikiを生成・更新
---

# Wishicraft Learning Wiki

Wishicraft repositoryの文書を読み、個人用・非公開・ローカル専用のObsidian互換Wikiを`.local/learning-wiki/`へ生成または更新する。用語選定、説明、リンク、索引はCodex自身が行う。generator、sync state、manifest、増分更新処理は作らない。

## 境界

- 最初にrepositoryの`AGENTS.md`と必読文書を読む。
- 実行前のbranch、HEAD、tracked working treeを記録する。既存変更を変更・復元しない。
- 毎回`README.md`、`docs/**/*.md`、`local-notes/codex/**/*.md`を全体確認する。解釈に必要な最小限だけ`config/project.yaml`、対象stage設定、secret配置契約を読む。
- 現在地点はREADME、delivery plan、Decision、repository状態から実行時に判定し、固定しない。未着手Phaseを進行中と表現せず、必要なら`completed_through`と`next_phase`を分ける。
- 出力は`.local/learning-wiki/`だけに置き、元のdocs、notes、README、config、source、infrastructure、testsを変更しない。
- `.local/learning-wiki/`がGit管理対象外か`git check-ignore`で確認する。未設定ならtrackedな`.gitignore`ではなく`.git/info/exclude`へ正確な`/.local/learning-wiki/`だけを追加する。
- dependency、hosting、Quartz、認証、公開処理、AWS、Discord、GitHub設定、production、実機、commit、pushを操作しない。
- `.obsidian/**`はObsidian、`personal/**`はユーザーが所有する外部可変領域であり、Skillの生成・管理対象ではない。作成、変更、削除、復元、snapshot取得、自動復元を行わず、Wiki更新でも上書きしない。
- この2領域の「保持」はSkillが意図的に書き込まないことを意味し、実行前後のbyte一致を意味しない。Obsidianが開かれている間の`workspace.json`等やユーザーによる並行変更はSkill失敗にせず、Skill自身の変更として報告しない。Skillが書き込んだ証拠がある場合だけ失敗とし、原因を断定できない変更を復元しない。
- 既存出力を更新する前にprovenanceと構造からWishicraft learning Wikiだと確認し、不明ならfail closedする。
- 実行前後でtracked working treeを比較し、新しいtracked変更を残さない。

## Authority

次の区分を維持する。

- `docs/`の現行文書: `canonical`
- Accepted Decision: `canonical-decision`
- DeferredまたはSuperseded Decision: `historical-decision`
- `local-notes/codex/`: `historical-learning`
- Wiki内の説明: `derived`

古いPhaseの途中状態、失敗、当時の未実施事項、resource実測を現行契約として断定しない。Decisionは状態とsupersessionまで読む。矛盾時はcanonical sourceを優先し、解消できなければ断定を書かず報告する。ID、ARN、secret、AWS設定、`null`を推測しない。

各derivedページのfront matterには少なくとも次を持たせる。

```yaml
canonical_status: derived
as_of_commit: <実行時HEAD>
completed_through: <実行時に確認した完了地点>
next_phase: <次の未着手作業単位>
sources:
  - path: docs/example.md
    authority: canonical
```

値を確定できない場合は推測せず、本文または完了報告で未確定とする。

## 用語選定とalias

次の一つ以上を満たす概念だけを候補にする。

- 複数文書に現れる、Wishicraft理解の中核、略語、または類似概念と混同しやすい。
- 一般的な意味とWishicraft固有の意味を分ける必要がある。
- 学習メモで疑問・失敗・説明の対象になった、または次Phaseの前提になる。

commit hash、resource/instance/Command ID、IP、version番号だけの項目、一時値、一度限りの変数/test名、単なるfile名やcommand optionはページ化しない。

既存ページのtitle、aliases、source表記を照合し、同じ概念なら更新する。英語・日本語、略称、大文字小文字、表記揺れだけで重複ページを作らない。

本文は日本語で書く。英語titleにはrepository内または一般的で自然な日本語名と略称を`aliases`へ追加し、不自然な機械翻訳は避ける。

```yaml
aliases:
  - 望ましい状態
  - 目標状態
  - Desired
```

用語ページは原則として次のsectionを持つ。

```markdown
# 正規名称

## 一言でいうと
## 一般的な意味
## Wishicraftではどう使うか
## 混同しやすい概念
## 具体例
## 関連用語
## Sources
```

単なる抜粋ではなく、後から理解し直せる説明にする。根拠がなければ「今回確認したsourceだけでは判断できない」と明記する。日本語本文から英語titleへは必要に応じて`[[desired-state|望ましい状態]]`のような表示名を使う。

## ガイド、索引、出力

個別用語だけでは理解しにくい独立した処理フロー、状態比較、責務境界がある場合だけ、再利用可能な日本語guideを作成・更新する。Phaseごとに機械的に増やさない。

`Home.md`から全生成用語、guide、表示用sourceへ到達でき、関連用語とSourcesから相互にたどれるようにする。

```text
.local/learning-wiki/
├── Home.md
├── glossary/
├── guides/
├── sources/
│   ├── docs/
│   └── local-notes/
└── personal/
```

## 表示用source

関連する`docs/`と`local-notes/codex/`は、手間を理由に省略せず`.local/learning-wiki/sources/`へ表示用コピーを作る。

- 冒頭にprovenance、authority、元source path、historical noteの注意を追加する。
- 追加層以降の原文本文を元sourceと一致させる。原文に許す変更はWiki link追加だけとする。
- code block、inline code、URL、heading、既存front matter、既存Markdown linkを壊さない。
- 各用語は同じsource内の最初の重要な出現だけをリンクし、長いaliasを優先する。
- sourceから用語へ、用語のSourcesからsourceへ戻れるようにする。
- resource ID、hash、IP、version、一時値をリンク対象にしない。

汎用scannerを作らず、CodexがMarkdown構造と文脈を確認しながらリンクする。

## 更新と検証

1. repository規約、状態、全対象文書、既存Wikiを読む。
2. authority、完了地点、Accepted/Deferred/Superseded、Phase間の変更を整理する。
3. 既存用語とaliasを照合し、新規・更新・統合を判断する。
4. `.obsidian/**`と`personal/**`を生成・管理対象から除外してHome、用語、guide、表示用sourceを更新する。
5. 次を検証する。失敗時は不完全な更新を成功扱いせず、`.local/learning-wiki/`内で安全に直せるものだけ直して再検証する。

- 全内部link先が存在し、Homeから全生成ページへ到達できる。
- 正規名称とaliasが衝突せず、英語titleに自然な日本語aliasがある。
- authority区分が維持され、Superseded Decisionや途中Phaseを現行仕様にしていない。
- 各derivedページにsource、authority、実行時HEADのas-of情報がある。
- 表示用コピーの原文部分が元sourceと一致し、許可箇所以外を壊していない。
- Skillが`.obsidian/**`または`personal/**`へ書き込んだ証拠がない。実行中の外部並行変更はbyte差だけで失敗にせず、Skillの変更として報告・復元しない。
- tracked fileが実行前より増えて変更されず、`.local/learning-wiki/`がignoreされている。
- dependencyや外部環境を操作していない。

完了時は生成・更新ファイル、検証結果、未確定事項、Obsidianで開く`.local/learning-wiki/`を報告して停止する。Phase作業、別Skill作成、commit、pushへ続けない。
