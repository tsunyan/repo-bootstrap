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
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@{{ACTION_CHECKOUT_SHA}} # {{ACTION_CHECKOUT_TAG}}
        with:
          persist-credentials: false
      - uses: actions/setup-java@{{ACTION_SETUP_JAVA_SHA}} # {{ACTION_SETUP_JAVA_TAG}}
        with:
          distribution: temurin
          java-version: '{{JAVA_LTS_MAJOR}}'
          cache: maven
      - name: Verify
        run: mvn --batch-mode --no-transfer-progress verify
