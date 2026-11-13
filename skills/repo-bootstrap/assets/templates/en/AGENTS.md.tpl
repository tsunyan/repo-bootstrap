# AGENTS.md — {{PROJECT_NAME}}

These instructions apply to coding agents working in this repository.

## Working principles

- Read the README, relevant code, and existing tests before editing.
- Keep changes scoped to the request; avoid unrelated refactoring.
- Review the need, maintenance status, license, and known vulnerabilities of new dependencies.
- Call out breaking changes to public interfaces and document migration when needed.
- Add regression tests for bug fixes where practical.
- Follow established naming conventions for code, identifiers, commands, and configuration keys.

## Development commands

- Setup: `{{DEV_SETUP_COMMAND_INLINE}}`
- Lint: `{{LINT_COMMAND}}`
- Test: `{{TEST_COMMAND}}`
- Build: `{{BUILD_COMMAND}}`

## Security and boundaries

- Never add credentials, private keys, tokens, or real personal data to code, logs, or tests.
- Do not change `.env`, production settings, external service secrets, or access policies without authorization.
- Do not weaken authentication, cryptography, or authorization controls to make tests pass.
- Do not disable CI or security checks to obtain a green result.
- Do not run destructive commands, publish, deploy, or incur costs without explicit authorization.
- Report any checks you could not run; never claim they succeeded.

## Documentation and language

- Write project documentation {{DOCS_LANGUAGE_POLICY_EN}}.
- Update the README, tests, and examples when behavior changes.
- Follow existing commit conventions; otherwise use short imperative English messages.

## Definition of done

- Run relevant tests and lint checks, and report their results.
- Treat checks that could not run as unverified, not passing.
- Summarize changes, risks, and outstanding work.
