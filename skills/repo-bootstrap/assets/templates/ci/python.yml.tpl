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
      - uses: actions/setup-python@{{ACTION_SETUP_PYTHON_SHA}} # {{ACTION_SETUP_PYTHON_TAG}}
        with:
          python-version: '{{PYTHON_VERSION}}'
      - name: Install
        run: python -m pip install -e '.[dev]'
      - name: Lint
        run: ruff check . && ruff format --check .
      - name: Test
        run: pytest -q
      - name: Build
        run: python -m build
