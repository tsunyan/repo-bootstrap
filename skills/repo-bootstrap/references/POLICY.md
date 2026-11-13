# 既定値・個人 GitHub Free の対応表・安全ゲート

実装は `scripts/policy.py`（`resolve` と `feature_plan`）。この文書はその要約。

## 既定値

| 入力 | 既定値 | 補足 |
|---|---|---|
| `owner` | 認証済みのユーザー | v1 は個人所有のリポジトリだけ |
| `visibility` | `public` | 利用者が選ぶ入力。plan はこの値を選択肢のおすすめとして `choices_required` に出し、create と adopt は指定がなければ止まる |
| `docs_locale` | public: `both` / private: `ja` | 同上（利用者が選ぶ入力） |
| `project_type` | `generic` | 文書と設定だけ。CI は作らない |
| `repo_kind` | public: `oss` / private: `internal` | |
| `license` | public かつ oss: `MIT` / それ以外: `none` | `Apache-2.0` はエラー（Phase 3） |
| `security_contact` | public: `private-reporting` / private: `existing-channel` | public に `existing-channel`、private に `private-reporting` は矛盾としてエラー。`email` は `--security-email` が必要 |
| `codeql` / `coderabbit` / `secret_scan` / `ci` | `auto` | |
| `ruleset` | `safe-default` | 削除と force push の禁止だけ。`strict` は PR 必須（承認 0 件）＋初回 CI で成功したチェック |
| `default_branch` | `main` | |

ランタイムの版（2026-11 時点で選択）: Node.js 24（engines は `>=24`）、CI の Python 3.14（`requires-python >=3.11`）、Java 21。`--node-version` などで変えられる。

## 個人 GitHub Free での判断

| 機能 | Public | Private | Private の代替 |
|---|---|---|---|
| マージ設定（squash のみ・マージ後にブランチ削除） | apply | apply | |
| GITHUB_TOKEN の既定権限を read に | apply | apply | |
| Dependabot alerts / security updates | apply | apply | |
| Dependabot version updates（`dependabot.yml`） | 生成 | 生成 | |
| GitHub secret scanning | apply | unsupported | Gitleaks のワークフロー（Push 後と PR で検出。Push 自体は止めない） |
| Push protection（リポジトリ） | apply | unsupported | 同上 |
| CodeQL default setup | apply（初回 push の後。対象言語はコミット内のファイルから決めて明示する。Rust は対象外） | unsupported | 言語別の lint とテスト。**同等ではない** |
| Ruleset | apply（初回 push の後） | unsupported | なし。GitHub はブランチを守らない |
| Private vulnerability reporting | apply（push 前に read-back 必須） | 使わない | SECURITY.md に既存の非公開の連絡経路を書く |
| CodeRabbit | App の導入を確認できたときだけ `.coderabbit.yaml` を生成。それ以外は manual_action | manual_action（非公開コードを外部に送るため） | |

CodeRabbit の App は、スクリプトが導入することはない。`--coderabbit on` は設定ファイルを置くだけで、レビューが動いた証明にはならない。

## 省略できない安全ゲート

どのモードでも外さない。失敗したら GitHub に何も送らずに止まる。

1. 未展開の `{{UPPER_SNAKE_CASE}}` が残っていない（`${{ github.* }}` は対象外）
2. ワークフローの `uses:` が 40 桁のコミット SHA。SHA は Action の公式リポジトリの最新リリースタグ（`vX.Y.Z`）から解決し、注釈付きタグはコミットまでたどる。解決できなければ止まる（fail closed）
3. ワークフローに `pull_request_target` がなく、最上位に `permissions` がある
4. コミットする内容に `.env`・秘密鍵・資格情報ファイルがなく、gitleaks が何も見つけない。public では gitleaks がなければ公開しない。push の直前にコミット履歴も gitleaks で調べる
5. public では、Private vulnerability reporting が有効だと読み戻せるまで push しない
6. 承認（`create` / `public` / `license`）がそろうまで、コミットも GitHub の操作もしない
7. 既存のファイルが、スキルが前回書いた内容（ロックファイルのハッシュ）と違えば上書きしない
8. 公開範囲は自動で変えない（repair でも変えない）。作成後にエラーが起きてもリポジトリを削除しない

## 状態の意味

| 状態 | 意味 |
|---|---|
| `applied` | 書き込みは成功。read-back はまだ |
| `verified` | read-back か実際の実行で確認した |
| `pending` | 非同期の処理が終わっていない（CI の初回実行など） |
| `unsupported` | このプラン・権限・公開範囲では使えない |
| `manual_action` | OAuth、App の導入、利用者の判断が要る |
| `skipped_by_policy` | 使わないと決めた |
| `failed` | 想定外の失敗。detail に原因と再開方法 |

`unsupported` / `manual_action` / `pending` が一つでもあれば `complete_with_constraints`（制約付き完了）で、完全な成功ではない。
