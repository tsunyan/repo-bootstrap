---
name: repo-bootstrap
description: 新しい GitHub リポジトリを、安全な標準構成（README・AGENTS・SECURITY・CONTRIBUTING・PR テンプレート・.gitignore・CI・Dependabot・GitHub のセキュリティ設定）で作る、既存のリポジトリに非破壊的に当てる、設定が実際に有効かを監査するスキル。文書の言語（日本語・英語・日英併記・英日併記）と公開範囲（Public・Private）を一次パラメータにし、個人の GitHub Free で使えない機能は黙って省かず代替と制約を報告する。「リポジトリを作って」「repo を初期化して」「新しいプロジェクトを GitHub に」「既存のリポジトリを標準構成にして」「リポジトリの設定を監査して」、または create a new GitHub repository, bootstrap or initialize a repo, audit repository settings と頼まれたときに使う。
compatibility: Requires git, gh (authenticated), Python 3.11+, and network access to GitHub. gitleaks is required to publish a public repository. PyYAML is optional (workflow structure check).
metadata:
  version: "0.1.0"
---

# repo-bootstrap

ファイルの描画と GitHub の操作は `scripts/bootstrap.py` が決定的に行う。エージェントの役目は、依頼を入力値に直すこと、承認を取ること、結果を正直に伝えることだけ。README などの本文を自分で作文しない（本文は `assets/templates/` に固定されている）。

詳しい規則は必要なときだけ読む:

- `references/POLICY.md`: 既定値、個人 Free の Public/Private 対応表、省略できない安全ゲート
- `references/LANGUAGE.md`: `ja` / `en` / `ja-en` / `en-ja` の生成規則
- `references/GITHUB_API.md`: 呼ぶ REST API と read-back の方法
- `references/DESIGN.md`: 規範となる設計書。`references/CHANGES.md`: 設計書から変えた点

## 手順

1. **入力を決める。** 依頼から次を読み取る。
   - `--name`（必須。不適切な名前は直さずに利用者へ返す）
   - **文書の言語 `--docs-locale ja|en|ja-en|en-ja` と公開範囲 `--visibility public|private` は、利用者に選んでもらう。** 依頼文ではっきり指定されていなければ、plan の前に選択肢で尋ねる（2 つまとめて 1 回で。選択肢の質問ツールがあればそれを使う）。既定値（言語は public なら ja-en、private なら ja。公開範囲は public）は「おすすめ」として示すだけで、黙って使わない。言語の選択肢は 4 つを次の説明つきで示す。`ja`: 日本語だけ。`en`: 英語だけ。`ja-en`: 日英併記で日本語が主（README.md が日本語、README.en.md が英語。ほかの文書は日本語の節が先）。`en-ja`: 英日併記で英語が主（README.md が英語、README.ja.md が日本語。ほかの文書は英語の節が先）。GitHub のトップに出るのは README.md なので、海外の読者も想定するなら en-ja が向く。利用者が「両方」とだけ答えたら、どちらを主にするか確かめる（`both` は `ja-en` の別名として残してある）。文書の言語は実装言語ではない。依頼文が日本語で書かれていることは、言語の指定とみなさない
   - ほかの値は、言われていなければ既定値を使い、細かく質問しない
   - `--type rust|python|node|java-maven|generic`（既定 generic = 文書と設定だけ）
   - 説明文 `--description-ja/-en`、概要 `--overview-ja/-en`。依頼文や既存のコードで裏付けられることだけを書く。`ja-en` と `en-ja` では両言語を渡す（スクリプトは翻訳しない）。なければ省略すると、機能を断言しない固定文になる
2. **plan を見せる。** `python scripts/bootstrap.py plan --name NAME --docs-locale ... --visibility ...` を実行する。GitHub にも手元にも何も書かない。`outcome` が `choice_required` なら、`choices_required` に出た入力を手順 1 のとおり利用者に尋ねてから plan をやり直す。結果から、作るファイル、適用する設定、`unsupported`（Free で使えない機能とその代替）、必要な承認を短くまとめて利用者に示す。
3. **承認を取る。** `approvals_required` に出た項目を、影響を添えて利用者に確認する。
   - `create`: GitHub にリポジトリを作り、生成物をコミットして push する
   - `public`: コードが誰でも見られるようになる
   - `license`: MIT ライセンスで利用を許諾する
   承認なしに `--approve` を付けない。利用者が断った項目があれば入力を変えて plan からやり直す（例: ライセンスを断られたら `--license none`）。
4. **create を実行する。** `python scripts/bootstrap.py create --name NAME --path DIR --docs-locale ... --visibility ... --approve create,public,license`
   - `--docs-locale` と `--visibility` がないと、何もせずに終了コード 2 で止まる（adopt も、`.repo-bootstrap.yml` に記録がなければ同じ）
   - `--path` は空のフォルダか、変更のない Git 作業ツリーの最上位。既存のコミットはそのまま push される
   - 承認が足りないと、手元にファイルを生成しただけで終了コード 3 で止まる（コミットも GitHub 操作もしない）
   - スクリプトは、ローカル検証（未展開変数、Action の SHA 固定、構文、リンク、言語、gitleaks）→ 空リポジトリ作成 → 設定 → Private vulnerability reporting の read-back → push → CodeQL → 初回 CI の待機 → Ruleset → read-back の順に進む。Public で脆弱性報告の経路が有効にならなければ push しない
5. **結果を伝える。** レポート（`DIR/.git/repo-bootstrap/bootstrap-report.md`）の `outcome` をそのまま伝える。
   - `complete_with_constraints` を「完了」と言い換えない。`unsupported` / `manual_action` / `pending` を一つずつ短い日本語で伝える
   - `applied` は「設定の書き込みは成功したが確認前」、`verified` だけが「確認済み」
   - `failed` は原因と、`repair` での再開方法を伝える。作ったリポジトリを勝手に消さない

## ほかのモード

- 既存のリポジトリに当てる: `adopt --path CLONE`。編集済みのファイルは上書きせず、差分を `.git/repo-bootstrap/conflicts/` に出す。コミットと push はしない。GitHub の設定も変えるときは利用者の承認を得て `--approve settings`
- 監査: `verify --repo OWNER/REPO`（読み取りだけ）
- 途中で止まった create の再開や設定の修復: `repair --repo OWNER/REPO --path CLONE --approve settings,push`。公開範囲は変えない

## してはいけないこと

- 承認のない公開、ライセンス付与、GitHub App（CodeRabbit など）の導入
- Free で使えない機能（Private の CodeQL・Ruleset・GitHub の secret scanning）を「有効」「同等」と言うこと。Gitleaks は秘密の検出で、脆弱性の検出の代わりではない
- 検証の失敗を通すために、検査を外したりスクリプトを迂回して手でファイルを書いたりすること
- Secret の値をコマンドライン引数、ログ、ファイルに書くこと。名前だけを `--secret NAME` で渡し、値は利用者に `gh secret set` で入力してもらう
