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

次の一つ以上を満たす概念を候補にする。

- 複数文書に現れる、Wishicraft理解の中核、略語、または類似概念と混同しやすい。
- 一般的な意味とWishicraft固有の意味を分ける必要がある。
- 学習メモで疑問・失敗・説明の対象になった、または次Phaseの前提になる。
- 英語の技術用語、略語・頭字語、repository内の短縮表記、または一般英単語でも技術文脈で特別な意味を持つ。
- AWS、Discord、Minecraft、Docker等の製品・service固有語、またはtest、validation、deploy、運用で使う英語表現である。
- 一度しか現れなくても、その段落を理解するために意味を知る必要がある、後から忘れやすい、または他概念との関係が分からないと理解しにくい。
- 日本語表記でも、Wishicraftの安全性、検証、責務、停止境界を理解するために重要である。

判断時は「この用語を一文で説明できない読者が、周囲の段落を正しく理解できるか」を問う。説明なしでは曖昧になるなら、出現回数だけで除外しない。一方、文脈上の意味を持たない一般英単語や、解説してもWishicraft文書の理解に寄与しない語は候補にしない。

commit hash、resource/instance/Command ID、IP、version番号だけの項目、一時値、一度限りの変数/test名、単なるfile名やcommand optionはページ化しない。

既存ページのtitle、aliases、source表記を照合し、同じ概念なら更新する。英語・日本語、略称、大文字小文字、表記揺れだけで重複ページを作らない。曖昧な短縮表記をtitleにせず、repositoryの文脈に合う製品名・service名・技術概念を含む正規名称へ寄せる。

本文は日本語で書く。英語titleにはsource中の実表記、実用的な大文字小文字差、略称、一般的で自然な日本語名、検索されそうな日本語表現を`aliases`へ追加し、不自然な機械翻訳や意味の異なる概念の統合を避ける。

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

単なる抜粋ではなく、英語用語に不慣れな読者が後から理解し直せる説明にする。「一言でいうと」は未説明の英語への言い換えにせず、略語は元の英語名称を示す。一般的な意味とWishicraft固有の使い方、canonicalとhistorical-learningを分け、実際に関係する処理・判断を具体例にする。必要な専門用語は用語ページへlinkし、根拠がなければ「今回確認したsourceだけでは判断できない」と明記する。日本語本文から英語titleへは必要に応じて`[[desired-state|望ましい状態]]`のような表示名を使う。

## ガイド、索引、出力

個別用語だけでは理解しにくい処理フロー、入力と出力、責務境界、検証順序、failure時の停止点がある場合は、複数用語の関係を示す再利用可能な日本語guideを作成・更新する。個々の定義を並べるだけにせず、Wishicraftと外部基盤の責務、canonical契約とhistorical-learningを分ける。Phaseごとや候補一覧から機械的に増やさない。

`Home.md`から全生成用語、guide、表示用sourceへ到達でき、関連用語とSourcesから相互にたどれるようにする。source数が多い場合はauthorityやPhaseなど意味のある単位で整理した索引を使い、無秩序な長い一覧や同一sourceの重複生成を避ける。

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

trackedな`docs/**/*.md`と`local-notes/codex/**/*.md`を実行ごとに列挙し、関連性や用語linkの有無で絞らず、全件を`.local/learning-wiki/sources/`へ表示用コピーとして収録する。source pathと表示用ページは1対1とし、元directory構造を保持して同名fileを衝突させない。追加、削除、renameを反映し、新規sourceだけでなく既存sourceも毎回確認する。READMEやconfigは現在地点とauthority判断には使ってよいが、この全件収録対象には含めない。

- 冒頭にprovenance、authority、元source path、historical noteの注意を追加する。
- 原文表示用コピー、authority、provenance、用語linkをsourceの現状に合わせ、sourceにない内容を推測で補わない。将来計画、Deferred、未実施事項を原文から削らず、付加領域で現行の完了状態と区別する。
- 追加層以降の本文で既存用語ページに対応する語が現れた場合、その重要な出現箇所から用語ページへ直接移動できるObsidian Wiki linkを付ける。別の関連用語一覧だけで代替しない。
- 同じsource内では各用語の最初の重要な出現だけを原則としてリンクする。単なる一覧、偶然の文字列一致、意味の異なる同名語は除外し、複数aliasが一致する場合は文脈に合う最長の表現を優先する。
- 日本語などtitleと異なる表示語は、表示文を維持するpiped linkにする。対応する既存用語ページがなければリンクを作らず、用語ページ数やlink密度を目的に増やさない。
- code block、inline code、URL、heading、既存front matter、既存Markdown linkを変更しない。resource ID、commit hash、IP、version番号、一時値もリンク対象にしない。
- canonicalとhistorical-learningの表示用sourceへ同じ規則を適用し、authorityの区別を維持する。
- sourceから用語へ、用語のSourcesからsourceへ戻れるようにする。

用語ページを新設・renameした場合、またはaliasを追加した場合は、その用語について新規分だけでなく全表示用sourceを再確認する。各sourceの最初の重要な意味一致箇所だけへlinkし、対応ページのない語や単なる文字列一致にはlinkしない。

Wiki link追加後の「原文一致」はbyte一致ではなく、追加したWiki linkを正規化した本文で判定する。`[[Operation]]`は`Operation`へ、`[[Operation|操作]]`は`操作`へ戻し、その結果が元source本文と一致しなければならない。表示される文字、語順、heading、code、URL、既存Markdown linkは変えず、許可する本文差分は既存用語へのWiki link記法だけとする。provenanceなど表示用コピー固有の付加領域は従来どおり比較対象から分離する。

汎用scannerを作らず、CodexがMarkdown構造と文脈を確認しながらリンクする。

## 更新と検証

1. repository規約、状態、tracked source inventory、全対象文書、既存Wikiを読む。
2. authority、完了地点、Accepted/Deferred/Superseded、Phase間の変更を整理する。
3. 既存用語とaliasを照合し、新規・更新・統合を判断する。
4. `.obsidian/**`と`personal/**`を生成・管理対象から除外してHome、用語、guide、表示用sourceを更新する。
5. 次を検証する。失敗時は不完全な更新を成功扱いせず、`.local/learning-wiki/`内で安全に直せるものだけ直して再検証する。

- tracked source inventoryと表示用sourceがpath単位で1対1に一致し、重複、欠落、削除済みsourceへの参照がない。
- 全内部link先が存在し、Homeから全生成ページへ到達できる。
- 正規名称とaliasが衝突せず、英語titleに自然な日本語aliasがある。
- 略語の展開があり、一言説明が別の未説明英語だけにならず、一般概念とWishicraft固有用途が分かれている。
- authority区分が維持され、Superseded Decisionや途中Phaseを現行仕様にしていない。
- 各derivedページにsource、authority、実行時HEADのas-of情報がある。
- 表示用コピーの追加Wiki linkを表示文字列へ正規化した原文部分が元sourceと一致し、許可されたWiki link記法以外を壊していない。全表示用sourceを確認し、重要な用語から既存用語ページへ移動でき、同一source内に過剰な重複linkがない。
- Skillが`.obsidian/**`または`personal/**`へ書き込んだ証拠がない。実行中の外部並行変更はbyte差だけで失敗にせず、Skillの変更として報告・復元しない。
- tracked fileが実行前より増えて変更されず、`.local/learning-wiki/`がignoreされている。
- dependencyや外部環境を操作していない。

完了時は生成・更新ファイル、検証結果、未確定事項、Obsidianで開く`.local/learning-wiki/`を報告して停止する。Phase作業、別Skill作成、commit、pushへ続けない。
