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
      - uses: dtolnay/rust-toolchain@{{ACTION_RUST_TOOLCHAIN_SHA}} # pinned revision
        with:
          toolchain: stable
          components: rustfmt, clippy
      - name: Format
        run: cargo fmt --all -- --check
      - name: Lint
        run: cargo clippy --all-targets --all-features --locked -- -D warnings
      - name: Test
        run: cargo test --all-targets --all-features --locked
      - name: Build
        run: cargo build --locked
