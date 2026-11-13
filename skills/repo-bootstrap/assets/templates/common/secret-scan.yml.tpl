# Optional private-Free fallback; only render after selecting a pinned Gitleaks action revision.
name: Secret scan
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  gitleaks:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@{{ACTION_CHECKOUT_SHA}} # {{ACTION_CHECKOUT_TAG}}
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: gitleaks/gitleaks-action@{{ACTION_GITLEAKS_SHA}} # {{ACTION_GITLEAKS_TAG}}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITLEAKS_ENABLE_COMMENTS: "false"
          GITLEAKS_ENABLE_UPLOAD_ARTIFACT: "false"
