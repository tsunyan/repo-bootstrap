"""Profile resolution, defaults, and the personal GitHub Free feature matrix.

Everything here is pure: no network, no filesystem writes. The rest of the
skill takes a resolved :class:`BootstrapRequest` and a list of
:class:`FeatureDecision` from this module.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import asdict, dataclass, field

SKILL_VERSION = "0.1.0"
SCHEMA_VERSION = 1

# Bilingual modes name the primary language first: ja-en puts Japanese first
# (README.md is Japanese, README.en.md English); en-ja puts English first
# (README.md is English, README.ja.md Japanese).
LOCALES = ("ja", "en", "ja-en", "en-ja")
BILINGUAL_LOCALES = ("ja-en", "en-ja")
LOCALE_ALIASES = {"both": "ja-en"}  # 0.1.0 name; kept so existing profiles still load

VISIBILITIES = ("public", "private")
PROJECT_TYPES = ("rust", "python", "node", "java-maven", "generic")
REPO_KINDS = ("oss", "personal", "internal")
LICENSES = ("MIT", "none")
TRISTATE = ("auto", "on", "off")
RULESETS = ("safe-default", "strict", "off")
SECURITY_CONTACTS = ("private-reporting", "email", "existing-channel")
MODES = ("plan", "create", "adopt", "verify", "repair")

# Runtime versions chosen for new starters (2026-11). Override with CLI flags.
NODE_LTS_MAJOR = "24"
PYTHON_CI_VERSION = "3.14"
JAVA_LTS_MAJOR = "21"

_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_SECRET_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

DESCRIPTION_MAX = 350
OVERVIEW_MAX = 1200


class PolicyError(ValueError):
    """Input that the skill refuses to act on. The message is shown to the user."""


@dataclass
class BootstrapRequest:
    mode: str
    name: str
    owner: str | None = None
    description_ja: str | None = None
    description_en: str | None = None
    overview_ja: str | None = None
    overview_en: str | None = None
    docs_locale: str | None = None
    visibility: str | None = None
    project_type: str | None = None
    repo_kind: str | None = None
    license: str | None = None
    copyright_holder: str | None = None
    copyright_year: int | None = None
    default_branch: str = "main"
    coderabbit: str = "auto"
    codeql: str = "auto"
    secret_scan: str = "auto"
    ruleset: str = "safe-default"
    security_contact: str | None = None
    security_email: str | None = None
    ci: str = "auto"
    secrets: list[str] = field(default_factory=list)
    node_version: str = NODE_LTS_MAJOR
    python_version: str = PYTHON_CI_VERSION
    java_version: str = JAVA_LTS_MAJOR
    package_name: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class FeatureDecision:
    """What the skill intends to do with one GitHub feature.

    ``action`` is one of ``apply`` (call the API / render the file),
    ``unsupported``, ``manual_action`` or ``skipped_by_policy``.
    """

    id: str
    action: str
    detail: str


def validate_repo_name(name: str) -> str:
    if not name or not _REPO_NAME_RE.match(name):
        raise PolicyError(
            f"Repository name {name!r} is not allowed. Use 1-100 characters from A-Z, a-z, 0-9, '-', '_' and '.'."
        )
    if name in (".", "..") or name.lower().endswith(".git"):
        raise PolicyError(f"Repository name {name!r} is reserved.")
    return name


def validate_owner(owner: str) -> str:
    if not _OWNER_RE.match(owner):
        raise PolicyError(f"Owner {owner!r} is not a valid GitHub user name.")
    return owner


def clean_text(value: str | None, *, label: str, limit: int) -> str | None:
    """Normalise a free-text field to one line without control characters."""
    if value is None:
        return None
    text = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    if _CONTROL_RE.search(text):
        raise PolicyError(f"{label} contains control characters.")
    if not text:
        return None
    if len(text) > limit:
        raise PolicyError(f"{label} is longer than {limit} characters.")
    return text


def _choose(value, allowed, label):
    if value not in allowed:
        raise PolicyError(f"{label} must be one of {', '.join(allowed)} (got {value!r}).")
    return value


def resolve(
    req: BootstrapRequest, *, authenticated_login: str | None = None, today: _dt.date | None = None
) -> BootstrapRequest:
    """Fill defaults and reject contradictory input. Returns a new request."""
    r = BootstrapRequest(**req.to_dict())
    _choose(r.mode, MODES, "mode")
    validate_repo_name(r.name)

    if r.owner is None:
        r.owner = authenticated_login
    if r.owner is None:
        raise PolicyError("Owner is unknown: log in with `gh auth login` or pass --owner.")
    validate_owner(r.owner)

    r.visibility = _choose(r.visibility or "public", VISIBILITIES, "visibility")
    public = r.visibility == "public"
    locale = LOCALE_ALIASES.get(r.docs_locale, r.docs_locale)
    r.docs_locale = _choose(locale or ("ja-en" if public else "ja"), LOCALES, "docs_locale")
    r.project_type = _choose(r.project_type or "generic", PROJECT_TYPES, "project_type")
    r.repo_kind = _choose(r.repo_kind or ("oss" if public else "internal"), REPO_KINDS, "repo_kind")

    if r.license == "Apache-2.0":
        raise PolicyError("Apache-2.0 is planned for Phase 3 and is not available yet. Use MIT or none.")
    r.license = _choose(r.license or ("MIT" if public and r.repo_kind == "oss" else "none"), LICENSES, "license")

    for key in ("coderabbit", "codeql", "secret_scan", "ci"):
        _choose(getattr(r, key), TRISTATE, key)
    _choose(r.ruleset, RULESETS, "ruleset")
    if not re.match(r"^[A-Za-z0-9._/-]{1,100}$", r.default_branch):
        raise PolicyError(f"default_branch {r.default_branch!r} is not allowed.")

    r.security_contact = r.security_contact or ("private-reporting" if public else "existing-channel")
    _choose(r.security_contact, SECURITY_CONTACTS, "security_contact")
    if r.security_contact == "private-reporting" and not public:
        raise PolicyError(
            "Private vulnerability reporting only exists for public repositories. "
            "Use security_contact=existing-channel or email for a private repository."
        )
    if r.security_contact == "existing-channel" and public:
        raise PolicyError(
            "A public repository needs a reporting route that outsiders can use. "
            "Use security_contact=private-reporting (default) or email."
        )
    if r.security_contact == "email":
        if not r.security_email or not _EMAIL_RE.match(r.security_email):
            raise PolicyError("security_contact=email needs --security-email with a valid address.")
    elif r.security_email:
        raise PolicyError("--security-email is only used with security_contact=email.")

    for s in r.secrets:
        if not _SECRET_NAME_RE.match(s) or s.upper().startswith("GITHUB_"):
            raise PolicyError(f"Secret name {s!r} is not allowed.")

    r.description_ja = clean_text(r.description_ja, label="description_ja", limit=DESCRIPTION_MAX)
    r.description_en = clean_text(r.description_en, label="description_en", limit=DESCRIPTION_MAX)
    r.overview_ja = clean_text(r.overview_ja, label="overview_ja", limit=OVERVIEW_MAX)
    r.overview_en = clean_text(r.overview_en, label="overview_en", limit=OVERVIEW_MAX)
    _require_both_languages(r)

    r.copyright_holder = clean_text(r.copyright_holder or r.owner, label="copyright_holder", limit=200)
    r.copyright_year = r.copyright_year or (today or _dt.datetime.now().astimezone().date()).year
    for key in ("node_version", "python_version", "java_version"):
        if not re.match(r"^\d+(\.\d+)?$", getattr(r, key)):
            raise PolicyError(f"{key} must look like 24 or 3.14.")
    return r


def is_bilingual(locale: str) -> bool:
    return locale in BILINGUAL_LOCALES


def primary_language(locale: str) -> str:
    """ja or en: the language of README.md and of the first section."""
    return "en" if locale in ("en", "en-ja") else "ja"


def readme_paths(locale: str) -> dict[str, str]:
    """README file per language for a bilingual locale."""
    return {"ja": "README.md", "en": "README.en.md"} if locale == "ja-en" else {"ja": "README.ja.md", "en": "README.md"}


def _require_both_languages(r: BootstrapRequest) -> None:
    """Text written in one language must also be given in the other when both are rendered.

    The skill never machine-translates; the agent supplies both strings.
    """
    needs = ("ja", "en") if is_bilingual(r.docs_locale) else (r.docs_locale,)
    # Package metadata (Cargo.toml, package.json, ...) always uses the English description.
    if r.project_type != "generic":
        needs = tuple(sorted(set(needs) | {"en"}))
    for base in ("description", "overview"):
        given = {lang for lang in ("ja", "en") if getattr(r, f"{base}_{lang}")}
        if given and not set(needs) <= given:
            missing = ", ".join(f"{base}_{lang}" for lang in needs if lang not in given)
            raise PolicyError(f"{base} was given only partly. Also pass {missing} (the skill does not translate).")


def feature_plan(r: BootstrapRequest, *, coderabbit_app_installed: bool | None = None) -> list[FeatureDecision]:
    """Decide each GitHub feature for a personal GitHub Free account."""
    public = r.visibility == "public"
    d: list[FeatureDecision] = []

    def add(fid: str, action: str, detail: str) -> None:
        d.append(FeatureDecision(fid, action, detail))

    add("repo.merge_settings", "apply", "Squash merge on, merge commits off, delete branches on merge")
    add("actions.token_permissions", "apply", "Default GITHUB_TOKEN permission: read")
    add("dependabot.alerts", "apply", "Enable Dependabot alerts")
    add("dependabot.security_updates", "apply", "Enable Dependabot security updates")

    if public:
        add("secret_scanning", "apply", "Enable GitHub secret scanning (free for public repositories)")
        add("push_protection", "apply", "Enable repository push protection")
    else:
        add(
            "secret_scanning",
            "unsupported",
            "GitHub secret scanning is not available for private repositories on personal Free",
        )
        add(
            "push_protection",
            "unsupported",
            "Repository push protection is not available for private repositories on personal Free; "
            "the Gitleaks workflow only detects secrets after they are pushed",
        )

    if r.codeql == "off":
        add("codeql", "skipped_by_policy", "codeql=off")
    elif public:
        add("codeql", "apply", "Enable CodeQL default setup after the first push")
    else:
        add(
            "codeql",
            "unsupported",
            "CodeQL code scanning is not available for private repositories on personal Free. "
            "Lint and tests in CI are the fallback; they are not equivalent",
        )

    gitleaks = r.secret_scan == "on" or (r.secret_scan == "auto" and not public)
    if r.secret_scan == "off":
        add("gitleaks", "skipped_by_policy", "secret_scan=off")
    elif gitleaks:
        add("gitleaks", "apply", "Add a Gitleaks workflow pinned to a verified commit SHA")
    else:
        add("gitleaks", "skipped_by_policy", "Public repository uses GitHub secret scanning instead")

    if r.ruleset == "off":
        add("ruleset.main", "skipped_by_policy", "ruleset=off")
    elif public:
        detail = "Block deletion and force pushes on the default branch after the first push"
        if r.ruleset == "strict":
            detail += "; require PRs (0 approvals) and the CI checks that passed on the first run"
        add("ruleset.main", "apply", detail)
    else:
        add(
            "ruleset.main",
            "unsupported",
            "Rulesets are not available for private repositories on personal Free; "
            "the default branch is not protected by GitHub",
        )

    if public and r.security_contact == "private-reporting":
        add(
            "private_vulnerability_reporting",
            "apply",
            "Enable private vulnerability reporting; the push is held until it reads back as enabled",
        )
    elif r.security_contact == "email":
        add("private_vulnerability_reporting", "skipped_by_policy", "security_contact=email")
    else:
        add(
            "private_vulnerability_reporting",
            "skipped_by_policy",
            "Private repository: SECURITY.md points to an existing private channel",
        )

    if r.coderabbit == "off":
        add("coderabbit", "skipped_by_policy", "coderabbit=off")
    elif not public:
        add(
            "coderabbit",
            "manual_action",
            "CodeRabbit would read private code. Confirm data handling and install the GitHub App yourself; "
            "the skill does not install it",
        )
    elif coderabbit_app_installed:
        add("coderabbit", "apply", "CodeRabbit GitHub App is installed; render .coderabbit.yaml")
    elif r.coderabbit == "on":
        add(
            "coderabbit",
            "manual_action",
            "Render .coderabbit.yaml, but the GitHub App installation could not be verified",
        )
    else:
        add(
            "coderabbit",
            "manual_action",
            "CodeRabbit GitHub App installation was not verified; .coderabbit.yaml is not rendered",
        )

    if r.project_type == "generic" or r.ci == "off":
        reason = "CI skipped: no runnable project" if r.project_type == "generic" else "ci=off"
        add("ci", "skipped_by_policy", reason)
    else:
        add("ci", "apply", f"Add {r.project_type} CI with actions pinned to full commit SHAs")
    return d


def decision(decisions: list[FeatureDecision], fid: str) -> FeatureDecision:
    for item in decisions:
        if item.id == fid:
            return item
    raise KeyError(fid)


def required_approvals(r: BootstrapRequest) -> list[str]:
    """Approvals the user must give before ``create`` touches GitHub."""
    needed = ["create"]
    if r.visibility == "public":
        needed.append("public")
    if r.license != "none":
        needed.append("license")
    return needed
