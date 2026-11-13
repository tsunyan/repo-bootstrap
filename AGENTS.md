<!-- 日本語 / English: keep both sections semantically consistent. -->

## 日本語

# AGENTS.md — repo-bootstrap

このファイルは本リポジトリで作業するAIコーディングエージェント向けの指示です。

## 作業の原則

- 変更前にREADME、関連するソース、既存テストを確認する。
- 依頼の範囲だけを変更し、無関係なリファクタリングをしない。
- 新規依存関係は必要性・保守状況・ライセンス・既知の脆弱性を確認する。
- 公開APIの変更や互換性破壊は明示し、必要なら移行手順を記載する。
- バグ修正では可能な限り回帰テストを追加する。
- コード、識別子、コマンド、設定キーは既存の命名規則に従う。

## 開発コマンド

- この段階で定義されたコマンドはありません。

## セキュリティと禁止事項

- 認証情報、秘密鍵、アクセストークン、実在する個人情報をコード・ログ・テストに追加しない。
- `.env`、本番設定、外部サービスのSecrets、権限設定を勝手に変更しない。
- 認証・暗号・認可に関わる処理を安易に無効化しない。
- CIやセキュリティ検査を無効にしてテストを通さない。
- 明示的な依頼なしに破壊的なコマンド、公開・デプロイ・課金を伴う操作を行わない。
- 不明点や実行できなかった検証は、完了報告で明示する。

## ドキュメントと言語

- 仕様と外部向け文書は日本語と英語の両方で内容を一致させて記述してください（日本語が主。README.md は日本語、README.en.md は英語で、ほかの文書は日本語の節を先に置く）。
- 振る舞いの変更では、必要に応じてREADME・テスト・サンプルを更新する。
- Gitコミットの形式は既存の運用に合わせる。規約がなければ短い命令形の英語にする。

## 完了条件

- 変更に対応したテストとLintを実行し、結果を報告する。
- 実行不能な検証は未確認として扱い、成功したと装わない。
- 変更点、リスク、残作業を簡潔に説明する。

---

## English

# AGENTS.md — repo-bootstrap

These instructions apply to coding agents working in this repository.

## Working principles

- Read the README, relevant code, and existing tests before editing.
- Keep changes scoped to the request; avoid unrelated refactoring.
- Review the need, maintenance status, license, and known vulnerabilities of new dependencies.
- Call out breaking changes to public interfaces and document migration when needed.
- Add regression tests for bug fixes where practical.
- Follow established naming conventions for code, identifiers, commands, and configuration keys.

## Development commands

- No commands are defined at this stage.

## Security and boundaries

- Never add credentials, private keys, tokens, or real personal data to code, logs, or tests.
- Do not change `.env`, production settings, external service secrets, or access policies without authorization.
- Do not weaken authentication, cryptography, or authorization controls to make tests pass.
- Do not disable CI or security checks to obtain a green result.
- Do not run destructive commands, publish, deploy, or incur costs without explicit authorization.
- Report any checks you could not run; never claim they succeeded.

## Documentation and language

- Write project documentation in both Japanese and English with equivalent meaning (Japanese first: README.md is Japanese, README.en.md is English, and other documents put the Japanese section first).
- Update the README, tests, and examples when behavior changes.
- Follow existing commit conventions; otherwise use short imperative English messages.

## Definition of done

- Run relevant tests and lint checks, and report their results.
- Treat checks that could not run as unverified, not passing.
- Summarize changes, risks, and outstanding work.
