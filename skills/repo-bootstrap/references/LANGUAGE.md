# 文書の言語（docs_locale）の規則

`docs_locale` は文書の言語で、実装言語（`project_type`）とは別の軸。

| docs_locale | README | AGENTS / SECURITY / CONTRIBUTING / PR テンプレート | Issue フォーム | CodeRabbit のレビュー言語 |
|---|---|---|---|---|
| `ja` | 日本語の `README.md` | 日本語 | 日本語 | `ja-JP` |
| `en` | 英語の `README.md` | 英語 | 英語 | `en-US` |
| `ja-en` | 日本語の `README.md` と英語の `README.en.md`。冒頭で相互にリンク | 1 ファイルに `## 日本語` → `## English` の順で両方 | 「日本語 / English」の順で併記 | `ja-JP` |
| `en-ja` | 英語の `README.md` と日本語の `README.ja.md`。冒頭で相互にリンク | 1 ファイルに `## English` → `## 日本語` の順で両方 | 「English / 日本語」の順で併記 | `en-US` |

`ja-en` と `en-ja` は、先に書いた言語が主になる。主の言語は README.md（GitHub のトップに出る）の言語、併記ファイルの先の節、Issue フォームのラベルの先、GitHub の説明文、CodeRabbit のレビュー言語に使う。0.1.0 の `both` は `ja-en` の別名として受け付ける（既存の `.repo-bootstrap.yml` を読めるように）。

テンプレートは `assets/templates/both/` の 1 組だけで、日本語の節が先に書いてある。`en-ja` では描画後に節を入れ替え（`renderer.english_first`）、README の相互リンクは変数（`README_JA_PATH` / `README_EN_PATH`）で差し替える。

`AGENTS.md` などを言語ごとに分けないのは、GitHub やエージェントが固定のファイル名で読むため。

## 守ること

- コードの識別子、API 名、パス、CLI コマンド、設定キーは翻訳しない
- スクリプトは翻訳しない。`ja-en` と `en-ja` で説明文や概要を渡すときは、エージェントが両言語を用意して `--description-ja` と `--description-en` の両方を渡す（片方だけならエラー）
- `project_type` が generic 以外なら、パッケージのメタデータ（Cargo.toml、package.json など）に使うため英語の説明も必要
- モードを変えても、残った旧言語のファイルは自動で消さない（adopt は差分を示すだけ）

## 検査（`validator.check_locale`）

- `en`: 文書に日本語（ひらがな・カタカナ・漢字・全角記号）が残っていない
- `ja`: 文書に日本語があり、`## English` の節がない
- `ja` / `en`: `README.en.md` も `README.ja.md` もない
- `ja-en` / `en-ja`: 主と副の README がそろい（もう一方の副の README はない）、相互リンクが成立し、英語版に日本語が混ざっていない。併記ファイルは両方の節を持ち、節の順が主の言語に合い、見出しの数がそろっている。Issue フォームのラベルが主の言語から併記になっている

意味が一致しているかまでは機械では確かめられない。テンプレートの固定文はそろえてあるが、利用者が渡した説明文の対訳はレビューで確認する。
