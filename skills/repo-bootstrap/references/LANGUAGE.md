# 文書の言語（docs_locale）の規則

`docs_locale` は文書の言語で、実装言語（`project_type`）とは別の軸。

| docs_locale | README | AGENTS / SECURITY / CONTRIBUTING / PR テンプレート | Issue フォーム | CodeRabbit のレビュー言語 |
|---|---|---|---|---|
| `ja` | 日本語の `README.md` | 日本語 | 日本語 | `ja-JP` |
| `en` | 英語の `README.md` | 英語 | 英語 | `en-US` |
| `both` | 日本語の `README.md` と英語の `README.en.md`。冒頭で相互にリンク | 1 ファイルに `## 日本語` と `## English` の両方 | ラベルを「日本語 / English」で併記 | `ja-JP` |

`AGENTS.md` などを言語ごとに分けないのは、GitHub やエージェントが固定のファイル名で読むため。

## 守ること

- コードの識別子、API 名、パス、CLI コマンド、設定キーは翻訳しない
- スクリプトは翻訳しない。`both` で説明文や概要を渡すときは、エージェントが両言語を用意して `--description-ja` と `--description-en` の両方を渡す（片方だけならエラー）
- `project_type` が generic 以外なら、パッケージのメタデータ（Cargo.toml、package.json など）に使うため英語の説明も必要
- モードを変えても、残った旧言語のファイルは自動で消さない（adopt は差分を示すだけ）

## 検査（`validator.check_locale`）

- `en`: 文書に日本語（ひらがな・カタカナ・漢字・全角記号）が残っていない
- `ja`: 文書に日本語があり、`## English` の節がない
- `both`: `README.en.md` があり相互リンクが成立し、英語版に日本語が混ざっていない。併記ファイルは両方の節を持ち、見出しの数がそろっている。Issue フォームのラベルが併記になっている

意味が一致しているかまでは機械では確かめられない。テンプレートの固定文はそろえてあるが、利用者が渡した説明文の対訳はレビューで確認する。
