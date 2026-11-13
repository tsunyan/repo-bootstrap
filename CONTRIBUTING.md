<!-- 日本語 / English: keep both sections semantically consistent. -->

## 日本語

# コントリビューションガイド

改善提案、バグ報告、Pull Requestを歓迎します。

## 変更を始める前に

1. 既存のIssueとPull Requestを確認してください。
2. 大きな仕様変更は、実装前にIssueで方向性を相談してください。
3. セキュリティ上の問題は公開Issueに書かず、[SECURITY.md](SECURITY.md) に従ってください。

## ローカルでの確認

この段階で定義されたコマンドはありません。

## Pull Request

- 目的、主要な変更点、動作確認の結果を記載してください。
- 互換性への影響があれば明示してください。
- 修正に関連するテストとドキュメントを更新してください。
- CIが失敗した場合は、原因を解決してからレビューを依頼してください。
- 秘密情報、生成された巨大ファイル、不要なバイナリを追加しないでください。

## レビュー

メンテナーが設計・セキュリティ・互換性・保守性の観点から判断します。
提案の採否やレビュー期間は保証しません。

---

## English

# Contributing

Bug reports, improvements, and pull requests are welcome.

## Before starting

1. Search existing issues and pull requests.
2. Discuss major design changes in an issue before implementation.
3. Report security issues privately according to [SECURITY.md](SECURITY.md), not in a public issue.

## Local verification

No commands are defined at this stage.

## Pull requests

- Explain the motivation, changes, and verification results.
- Disclose compatibility implications and breaking changes.
- Update relevant tests and documentation.
- Resolve CI failures before requesting review.
- Do not commit secrets, large generated artifacts, or unnecessary binaries.

## Review

Maintainers evaluate design, security, compatibility, and maintainability.
Acceptance and review timing are not guaranteed.
