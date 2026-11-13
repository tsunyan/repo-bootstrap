# Contributing

Bug reports, improvements, and pull requests are welcome.

## Before starting

1. Search existing issues and pull requests.
2. Discuss major design changes in an issue before implementation.
3. Report security issues privately according to [SECURITY.md](SECURITY.md), not in a public issue.

## Local verification

```sh
{{DEV_SETUP_COMMAND}}
{{LINT_COMMAND}}
{{TEST_COMMAND}}
{{BUILD_COMMAND}}
```

## Pull requests

- Explain the motivation, changes, and verification results.
- Disclose compatibility implications and breaking changes.
- Update relevant tests and documentation.
- Resolve CI failures before requesting review.
- Do not commit secrets, large generated artifacts, or unnecessary binaries.

## Review

Maintainers evaluate design, security, compatibility, and maintainability.
Acceptance and review timing are not guaranteed.
