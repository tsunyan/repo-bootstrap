# 設計書（1.0-draft）から変えた点

実装中に見つけた設計書の不具合と、設計書が決めていなかった点の決め方。

## テンプレートの修正

- `common/content-i18n.json`: `security_contact.public_*` と `email_*` に、実装者向けの注記（「この案内は…確認できた場合にのみ掲載します」など）が本文として入っていた。描画すると SECURITY.md にそのまま出るので、注記は `_notes` に移した。ライセンスの文言 `license_statement` も追加した（設計書の描画例 `examples/rendered-public-both-rust` と同じ文）
- `common/repo-bootstrap.yml.tpl`: `codeql: auto` などが固定値で、実際の入力が記録されなかった。全項目を変数にし、`repair` と `adopt` が入力を復元できるよう、説明文・著作権者・年なども記録する
- `starter/python/pyproject.toml.tpl`: `license = "MIT"`（SPDX の文字列）は setuptools 77 以降でないと読めないので、`setuptools>=75` を `>=77` にした

## 設計書が決めていなかった点

- generic の文書: テンプレートのコマンド欄（コードフェンスと AGENTS の箇条書き）を「この段階で定義されたコマンドはありません。」に置き換える（§9.5）
- Java の LINT_COMMAND: Maven には lint の標準がないので `mvn validate`（pom の検証）にした。CI は設計どおり `mvn verify` だけ
- Cargo.lock と package-lock.json: 依存のないスターターなので、ツールを呼ばずに決まった内容を書く。CI の `--locked` と `npm ci` で検証される
- 承認: `--approve create,public,license`（create）、`settings,push`（repair）、`settings`（adopt）で渡す。足りなければ終了コード 3
- レポートの置き場所: `<作業ツリー>/.git/repo-bootstrap/`。リポジトリにはコミットされない
- `dependabot.yml`: エコシステムもワークフローもない generic では作らない（作っても対象がない）
- adopt で既存のプロジェクト（マニフェストあり）に CI を足すときは、コマンドが実在するか分からないので既定では作らず manual_action にする。`--ci on` で作る（node は scripts の有無を確かめる）
- CodeQL default setup: 設計書は `state=configured` を確認するだけだったが、初回 push の直後に設定すると GitHub の言語検出が追いつかず、対象が `actions` だけになることがあった（このスキルの配布用リポジトリで実際に起きた）。対象言語をファイルの拡張子から決めて `languages` で明示し、すべて入っているときだけ verified にする
- 文書の言語と公開範囲: 設計書は「解決する」とだけ書き、既定値もあった。初版のスキルは指定がないと既定値を黙って使い、配布用リポジトリを作ったときも利用者に言語を尋ねなかった。この 2 つは一次パラメータなので利用者に選んでもらう。plan は選ばれていない入力を `choices_required`（`outcome: choice_required`）として既定値つきで出し、create と adopt は指定がなければ終了コード 2 で止まる（adopt は `.repo-bootstrap.yml` の記録があればそれを使う）
- Gitleaks の Action はテンプレートどおり `gitleaks/gitleaks-action`（個人アカウントは無料。組織ではライセンスキーが要る）

## 未実装（設計書の Phase 3 以降）

- Apache-2.0、Semgrep、Copier への移行、テンプレート更新の 3-way マージ（今は差分を出すだけ）
- 組織所有のリポジトリ
