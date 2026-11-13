name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
permissions:
  contents: read
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@{{ACTION_CHECKOUT_SHA}} # {{ACTION_CHECKOUT_TAG}}
        with:
          persist-credentials: false
      - uses: actions/setup-node@{{ACTION_SETUP_NODE_SHA}} # {{ACTION_SETUP_NODE_TAG}}
        with:
          node-version: '{{NODE_LTS_MAJOR}}'
          cache: npm
      - name: Install
        run: npm ci
      - name: Lint
        run: npm run lint
      - name: Test
        run: npm test
      - name: Build
        run: npm run build
