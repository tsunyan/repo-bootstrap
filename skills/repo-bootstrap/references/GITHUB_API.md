# 使う GitHub REST API と read-back

すべて `gh api --include` 経由（`scripts/github_api.py`）。API バージョンは `2022-11-28`。2026-11-14 に、個人アカウント（トークンのスコープ `repo`, `workflow`）で応答の形を確認した。

## 呼び出しの規則

- 429 と 5xx（と secondary rate limit の 403）は `Retry-After` に従って最大 4 回まで試す
- 401 / 403 / 404 / 422 は区別して報告する。403 を「プランにない」と決めつけない（権限不足のこともある）
- `plan` と `verify` のクライアントは読み取り専用で、書き込みを試みると例外になる
- 書き込みの前に読み、すでに期待どおりなら書かない。書いた後は読み戻し、合わなければ 2 秒おきに最大 4 回読み直す

## 操作と確認方法

| 操作 | 書き込み | 読み戻し | verified の条件 |
|---|---|---|---|
| 認証ユーザー | — | `GET /user` | — |
| 空リポジトリの作成 | `POST /user/repos`（`auto_init: false`） | `GET /repos/{o}/{r}` | `private` が期待どおり |
| マージ設定 | `PATCH /repos/{o}/{r}` | `GET /repos/{o}/{r}` | `allow_squash_merge=true`, `allow_merge_commit=false`, `delete_branch_on_merge=true` |
| GITHUB_TOKEN の既定権限 | `PUT /repos/{o}/{r}/actions/permissions/workflow` | 同じパスを GET | `default_workflow_permissions=read`、PR 承認不可 |
| Dependabot alerts | `PUT /repos/{o}/{r}/vulnerability-alerts` | 同じパスを GET | 204（無効なら 404） |
| Dependabot security updates | `PUT /repos/{o}/{r}/automated-security-fixes` | 同じパスを GET | `enabled=true` かつ `paused=false` |
| Secret scanning / push protection | `PATCH /repos/{o}/{r}` の `security_and_analysis` | `GET /repos/{o}/{r}` | 各 `status=enabled` |
| Private vulnerability reporting | `PUT /repos/{o}/{r}/private-vulnerability-reporting` | 同じパスを GET | `enabled=true` |
| CodeQL default setup | `PATCH /repos/{o}/{r}/code-scanning/default-setup`（`state: configured` と `languages`） | 同じパスを GET | `state=configured` で、コミット内のファイルから決めた言語がすべて `languages` に入っている |
| Ruleset | `POST /repos/{o}/{r}/rulesets`、管理対象（名前が `repo-bootstrap: default branch`）だけ `PUT` で更新 | `GET /repos/{o}/{r}/rulesets/{id}` | `enforcement=active` と規則の種類 |
| 初回 CI | push | `GET /repos/{o}/{r}/actions/runs?head_sha=…` | 各ワークフローの run が `completed` かつ `success` |
| 必須チェック名（strict） | — | `GET /repos/{o}/{r}/actions/runs/{id}/jobs` | 成功したジョブ名だけを Ruleset に入れる |
| Secret | 値は扱わない | `GET /repos/{o}/{r}/actions/secrets` | 名前が存在する |
| CodeRabbit App | 扱わない | `GET /user/installations` | OAuth トークンでは 403 になることが多い。そのときは不明として manual_action |
| Action の SHA | — | `GET /repos/{action}/releases/latest` → `git/ref/tags/{tag}` →（注釈付きなら）`git/tags/{sha}` | 40 桁の SHA。`dtolnay/rust-toolchain` はリリースがないので `branches/stable` |

他人が作った Ruleset は変更せず、名前だけ報告する。

## CodeQL の対象言語

`languages` を省くと、GitHub はその時点で検出済みの言語だけを選ぶ。初回 push の直後は言語の検出が追いつかず、たとえば Python のリポジトリでも `actions` だけになることがある。そのため対象言語は GitHub の言語統計ではなく、push したコミットのファイルの拡張子から決めて明示する（`github_api.codeql_languages_for`）。

- 受け付ける値（REST のドキュメント、2026-11-14 確認）: `actions`, `c-cpp`, `csharp`, `go`, `java-kotlin`, `javascript-typescript`, `python`, `ruby`, `swift`
- Rust は含まれない。Rust のファイルがあれば「CodeQL の対象外（CI の lint とテストだけ）」とレポートに書く
- 409（別の設定を検証中）と 422（リポジトリの準備ができていない）は、10 秒おきに最大 6 回まで再試行する
- `.tpl` などのテンプレートは数えない
