"""Build the complete set of files for a resolved request.

The output is a list of :class:`PlannedFile` held in memory. Nothing is
written here; :mod:`state` decides what may be written to disk.
"""

from __future__ import annotations

import json
import keyword
import re
from dataclasses import dataclass
from pathlib import Path

import renderer
from policy import BootstrapRequest, FeatureDecision, decision

TEMPLATES = Path(__file__).resolve().parent.parent / "assets" / "templates"

USER_VARS = frozenset(
    {
        "PROJECT_DESCRIPTION_JA",
        "PROJECT_DESCRIPTION_EN",
        "PROJECT_OVERVIEW_JA",
        "PROJECT_OVERVIEW_EN",
        "COPYRIGHT_HOLDER",
    }
)

JAVA_KEYWORDS = frozenset(
    [
        "abstract",
        "assert",
        "boolean",
        "break",
        "byte",
        "case",
        "catch",
        "char",
        "class",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extends",
        "final",
        "finally",
        "float",
        "for",
        "goto",
        "if",
        "implements",
        "import",
        "instanceof",
        "int",
        "interface",
        "long",
        "native",
        "new",
        "package",
        "private",
        "protected",
        "public",
        "return",
        "short",
        "static",
        "strictfp",
        "super",
        "switch",
        "synchronized",
        "this",
        "throw",
        "throws",
        "transient",
        "try",
        "void",
        "volatile",
        "while",
        "true",
        "false",
        "null",
        "var",
        "record",
        "yield",
        "sealed",
        "permits",
    ]
)

DEPENDABOT_ECOSYSTEM = {"rust": "cargo", "python": "pip", "node": "npm", "java-maven": "maven"}

# Which pinned actions each workflow needs (see actions.ACTIONS).
CI_ACTIONS = {
    "rust": ("ACTION_CHECKOUT", "ACTION_RUST_TOOLCHAIN"),
    "python": ("ACTION_CHECKOUT", "ACTION_SETUP_PYTHON"),
    "node": ("ACTION_CHECKOUT", "ACTION_SETUP_NODE"),
    "java-maven": ("ACTION_CHECKOUT", "ACTION_SETUP_JAVA"),
}
GITLEAKS_ACTIONS = ("ACTION_CHECKOUT", "ACTION_GITLEAKS")


class ScaffoldError(ValueError):
    pass


@dataclass(frozen=True)
class PlannedFile:
    path: str  # POSIX path relative to the repository root
    content: str
    template: str  # template it came from, or "generated:<what>"
    kind: str  # doc | config | ci | starter | meta


# ---------------------------------------------------------------- names


def python_names(r: BootstrapRequest) -> tuple[str, str]:
    base = r.package_name or r.name
    dist = re.sub(r"[-_.]+", "-", base).lower().strip("-")
    module = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")
    if not module or module[0].isdigit() or keyword.iskeyword(module):
        raise ScaffoldError(
            f"Cannot derive a Python module name from {base!r}. "
            "Pass --package-name with a name that starts with a letter."
        )
    return dist, module


def npm_name(r: BootstrapRequest) -> str:
    name = (r.package_name or r.name).lower()
    if not re.match(r"^[a-z0-9][a-z0-9._~-]{0,213}$", name) or name in ("node_modules", "favicon.ico"):
        raise ScaffoldError(f"{name!r} is not a valid npm package name. Pass --package-name.")
    return name


def cargo_name(r: BootstrapRequest) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]", "-", r.package_name or r.name).lower()
    if not re.match(r"^[a-z][a-z0-9_-]*$", name) or name in ("test", "core", "std", "alloc", "proc_macro"):
        raise ScaffoldError(f"{name!r} is not a usable Cargo package name. Pass --package-name.")
    return name


def _java_ident(part: str) -> str:
    ident = re.sub(r"[^a-z0-9_]", "_", part.lower())
    if not ident or ident[0].isdigit():
        ident = "_" + ident
    if ident in JAVA_KEYWORDS:
        ident += "_"
    return ident


def java_names(r: BootstrapRequest) -> tuple[str, str, str]:
    owner = r.owner.lower()
    group_id = "io.github." + re.sub(r"[^a-z0-9-]", "-", owner)
    artifact = re.sub(r"[^a-z0-9.-]", "-", (r.package_name or r.name).lower()).strip("-.")
    if not artifact:
        raise ScaffoldError("Cannot derive a Maven artifactId. Pass --package-name.")
    package = ".".join(["io", "github", _java_ident(owner), _java_ident(r.package_name or r.name)])
    return group_id, artifact, package


# ---------------------------------------------------------------- variables


def _commands(r: BootstrapRequest) -> dict[str, str]:
    t = r.project_type
    if t == "rust":
        return {
            "INSTALL_COMMAND": "cargo build --locked",
            "USAGE_COMMAND": "cargo run",
            "DEV_SETUP_COMMAND": "rustup component add rustfmt clippy",
            "LINT_COMMAND": (
                "cargo fmt --all -- --check && cargo clippy --all-targets --all-features --locked -- -D warnings"
            ),
            "TEST_COMMAND": "cargo test --all-targets --all-features --locked",
            "BUILD_COMMAND": "cargo build --locked",
        }
    if t == "python":
        _, module = python_names(r)
        return {
            "INSTALL_COMMAND": "python -m pip install .",
            "USAGE_COMMAND": f"python -m {module}",
            "DEV_SETUP_COMMAND": "python -m pip install -e '.[dev]'",
            "LINT_COMMAND": "ruff check . && ruff format --check .",
            "TEST_COMMAND": "pytest -q",
            "BUILD_COMMAND": "python -m build",
        }
    if t == "node":
        return {
            "INSTALL_COMMAND": "npm ci",
            "USAGE_COMMAND": "npm start",
            "DEV_SETUP_COMMAND": "npm ci",
            "LINT_COMMAND": "npm run lint",
            "TEST_COMMAND": "npm test",
            "BUILD_COMMAND": "npm run build",
        }
    if t == "java-maven":
        _, _, package = java_names(r)
        mvn = "mvn --batch-mode --no-transfer-progress"
        return {
            "INSTALL_COMMAND": f"{mvn} package",
            "USAGE_COMMAND": f"java -cp target/classes {package}.App",
            "DEV_SETUP_COMMAND": f"{mvn} dependency:resolve",
            "LINT_COMMAND": f"{mvn} validate",
            "TEST_COMMAND": f"{mvn} test",
            "BUILD_COMMAND": f"{mvn} verify",
        }
    return {
        k: renderer.NO_COMMAND
        for k in (
            "INSTALL_COMMAND",
            "USAGE_COMMAND",
            "DEV_SETUP_COMMAND",
            "LINT_COMMAND",
            "TEST_COMMAND",
            "BUILD_COMMAND",
        )
    }


_RUNTIME = {
    "rust": ("Rust stable toolchain（rustupで導入）", "Rust stable toolchain installed via rustup", "Git", "Git"),
    "python": ("Python 3.11 以上", "Python 3.11 or later", "Git", "Git"),
    "node": ("Node.js {node} 以上（npm を含む）", "Node.js {node} or later (with npm)", "Git", "Git"),
    "java-maven": (
        "Java {java}（LTS）以上",
        "Java {java} (LTS) or later",
        "Apache Maven 3.9 以上、Git",
        "Apache Maven 3.9 or later, Git",
    ),
    "generic": ("特定のランタイムはありません", "No specific runtime", "Git", "Git"),
}

_USAGE_NOTES = {
    "rust": (
        "現時点では雛形アプリです。オプションが未実装の場合、`--help`の動作も保証しません。",
        "This is a scaffold. CLI options, including `--help`, may not be implemented yet.",
    ),
    "python": (
        "現時点では雛形アプリです。プロジェクト名を表示するだけで、オプションは未実装です。",
        "This is a scaffold. It prints the project name; options are not implemented yet.",
    ),
    "node": (
        "現時点では雛形アプリです。プロジェクト名を表示するだけで、オプションは未実装です。",
        "This is a scaffold. It prints the project name; options are not implemented yet.",
    ),
    "java-maven": (
        "現時点では雛形アプリです。`mvn package` の後に実行すると、プロジェクト名を表示します。",
        "This is a scaffold. After `mvn package`, it prints the project name.",
    ),
    "generic": ("", ""),
}

_LANG_LABEL = {
    "rust": ("Rust", "Rust"),
    "python": ("Python", "Python"),
    "node": ("Node.js", "Node.js"),
    "java-maven": ("Java（Maven）", "Java (Maven)"),
}


def _load_json(name: str) -> dict:
    return json.loads((TEMPLATES / "common" / name).read_text(encoding="utf-8"))


def default_texts(r: BootstrapRequest) -> dict[str, str]:
    """Fixed wording used when the user gave no description or overview.

    These never claim features; they only say what the skill generated.
    """
    if r.project_type == "generic":
        overview = (
            "このリポジトリは、プロジェクトの標準構成を管理する場所です。",
            "This repository holds the standard project configuration.",
        )
    else:
        ja, en = _LANG_LABEL[r.project_type]
        overview = (
            f"{ja}で実装する開発用のスターター構成です。アプリケーションの機能はまだ実装していません。",
            f"This repository is a {en} development starter. Application features are not implemented yet.",
        )
    return {
        "PROJECT_DESCRIPTION_JA": f"{r.name} プロジェクト",
        "PROJECT_DESCRIPTION_EN": f"{r.name} project",
        "PROJECT_OVERVIEW_JA": overview[0],
        "PROJECT_OVERVIEW_EN": overview[1],
    }


def build_variables(r: BootstrapRequest, pins: dict[str, dict]) -> dict[str, str]:
    content = _load_json("content-i18n.json")
    issue = _load_json("issue-i18n.json")
    defaults = default_texts(r)
    v: dict[str, str] = {
        "PROJECT_NAME": r.name,
        "REPOSITORY_NAME": r.name,
        "OWNER": r.owner,
        "PROJECT_DESCRIPTION_JA": r.description_ja or defaults["PROJECT_DESCRIPTION_JA"],
        "PROJECT_DESCRIPTION_EN": r.description_en or defaults["PROJECT_DESCRIPTION_EN"],
        "PROJECT_OVERVIEW_JA": r.overview_ja or defaults["PROJECT_OVERVIEW_JA"],
        "PROJECT_OVERVIEW_EN": r.overview_en or defaults["PROJECT_OVERVIEW_EN"],
        "VISIBILITY": r.visibility,
        "DOCS_LOCALE": r.docs_locale,
        "PROJECT_TYPE": r.project_type,
        "REPO_KIND": r.repo_kind,
        "DEFAULT_BRANCH": r.default_branch,
        "LICENSE_ID": r.license,
        "COPYRIGHT_YEAR": str(r.copyright_year),
        "COPYRIGHT_HOLDER": r.copyright_holder,
        "CODEQL": r.codeql,
        "CODERABBIT": r.coderabbit,
        "RULESET": r.ruleset,
        "SECRET_SCAN": r.secret_scan,
        "CI": r.ci,
        "SECURITY_CONTACT_KIND": r.security_contact,
        "CODERABBIT_REVIEW_LANGUAGE": "en-US" if r.docs_locale == "en" else "ja-JP",
        "NODE_LTS_MAJOR": r.node_version,
        "PYTHON_VERSION": r.python_version,
        "JAVA_LTS_MAJOR": r.java_version,
    }
    for key, value in {
        "COPYRIGHT_HOLDER_YAML": r.copyright_holder,
        "SECURITY_EMAIL_YAML": r.security_email,
        "PROJECT_DESCRIPTION_JA_YAML": r.description_ja,
        "PROJECT_DESCRIPTION_EN_YAML": r.description_en,
        "PROJECT_OVERVIEW_JA_YAML": r.overview_ja,
        "PROJECT_OVERVIEW_EN_YAML": r.overview_en,
    }.items():
        v[key] = json.dumps(value, ensure_ascii=False)

    v.update(_commands(r))
    v["DEV_SETUP_COMMAND_INLINE"] = v["DEV_SETUP_COMMAND"]
    rt = _RUNTIME[r.project_type]
    fmt = {"node": r.node_version, "java": r.java_version}
    v["RUNTIME_REQUIREMENT_JA"] = rt[0].format(**fmt)
    v["RUNTIME_REQUIREMENT_EN"] = rt[1].format(**fmt)
    v["OTHER_REQUIREMENTS_JA"] = rt[2]
    v["OTHER_REQUIREMENTS_EN"] = rt[3]
    v["USAGE_NOTES_JA"], v["USAGE_NOTES_EN"] = _USAGE_NOTES[r.project_type]

    lic = content["license_statement"]
    v["LICENSE_STATEMENT_JA"] = lic[f"{r.license}_ja"]
    v["LICENSE_STATEMENT_EN"] = lic[f"{r.license}_en"]

    sc = content["security_contact"]
    kind = {"private-reporting": "public", "existing-channel": "private", "email": "email"}[r.security_contact]
    email_vars = {"SECURITY_EMAIL": r.security_email or ""}
    v["SECURITY_CONTACT_JA"] = renderer.render(sc[f"{kind}_ja"], email_vars)
    v["SECURITY_CONTACT_EN"] = renderer.render(sc[f"{kind}_en"], email_vars)

    v.update(content[r.docs_locale])
    v.update(issue[r.docs_locale])

    for key, pin in pins.items():
        v[f"{key}_SHA"] = pin["sha"]
        v[f"{key}_TAG"] = pin["tag"]

    t = r.project_type
    if t == "rust":
        v["CARGO_PACKAGE_NAME"] = cargo_name(r)
        v["CARGO_LICENSE_LINE"] = f'license = "{r.license}"' if r.license != "none" else ""
    elif t == "python":
        v["PYTHON_DISTRIBUTION_NAME"], v["PYTHON_MODULE"] = python_names(r)
        v["CLI_COMMAND_NAME"] = v["PYTHON_DISTRIBUTION_NAME"]
        v["PYTHON_LICENSE_LINE"] = f'license = "{r.license}"' if r.license != "none" else ""
    elif t == "node":
        v["NPM_PACKAGE_NAME"] = npm_name(r)
    elif t == "java-maven":
        v["JAVA_GROUP_ID"], v["JAVA_ARTIFACT_ID"], v["JAVA_PACKAGE"] = java_names(r)
    return v


# ---------------------------------------------------------------- file plan


def needed_actions(r: BootstrapRequest, decisions: list[FeatureDecision]) -> list[str]:
    keys: list[str] = []
    if decision(decisions, "ci").action == "apply":
        keys += CI_ACTIONS[r.project_type]
    if decision(decisions, "gitleaks").action == "apply":
        keys += GITLEAKS_ACTIONS
    return sorted(set(keys))


def renders_coderabbit_config(r: BootstrapRequest, decisions: list[FeatureDecision]) -> bool:
    return decision(decisions, "coderabbit").action == "apply" or r.coderabbit == "on"


def _doc_entries(locale: str) -> list[tuple[str, str, str]]:
    """(template, output path, language of the file)."""
    lang = "both" if locale == "both" else locale
    entries = [
        (f"{locale}/README.md.tpl", "README.md", "ja" if locale == "both" else locale),
        (f"{locale}/AGENTS.md.tpl", "AGENTS.md", lang),
        (f"{locale}/SECURITY.md.tpl", "SECURITY.md", lang),
        (f"{locale}/CONTRIBUTING.md.tpl", "CONTRIBUTING.md", lang),
        (f"{locale}/PULL_REQUEST_TEMPLATE.md.tpl", ".github/PULL_REQUEST_TEMPLATE.md", lang),
    ]
    if locale == "both":
        entries.insert(1, ("both/README.en.md.tpl", "README.en.md", "en"))
    return entries


def _starter_entries(r: BootstrapRequest, v: dict[str, str]) -> list[tuple[str, str]]:
    t = r.project_type
    if t == "rust":
        return [("starter/rust/Cargo.toml.tpl", "Cargo.toml"), ("starter/rust/main.rs.tpl", "src/main.rs")]
    if t == "python":
        mod = v["PYTHON_MODULE"]
        return [
            ("starter/python/pyproject.toml.tpl", "pyproject.toml"),
            ("starter/python/__init__.py.tpl", f"src/{mod}/__init__.py"),
            ("starter/python/__main__.py.tpl", f"src/{mod}/__main__.py"),
            ("starter/python/test_smoke.py.tpl", "tests/test_smoke.py"),
        ]
    if t == "node":
        return [
            ("starter/node/package.json.tpl", "package.json"),
            ("starter/node/index.js.tpl", "src/index.js"),
            ("starter/node/index.test.js.tpl", "test/index.test.js"),
        ]
    if t == "java-maven":
        pkg_path = v["JAVA_PACKAGE"].replace(".", "/")
        return [
            ("starter/java-maven/pom.xml.tpl", "pom.xml"),
            ("starter/java-maven/App.java.tpl", f"src/main/java/{pkg_path}/App.java"),
            ("starter/java-maven/AppTest.java.tpl", f"src/test/java/{pkg_path}/AppTest.java"),
        ]
    return []


def _generated_lockfiles(r: BootstrapRequest, v: dict[str, str]) -> list[PlannedFile]:
    if r.project_type == "rust":
        text = (
            "# This file is automatically @generated by Cargo.\n"
            "# It is not intended for manual editing.\n"
            "version = 4\n\n"
            "[[package]]\n"
            f'name = "{v["CARGO_PACKAGE_NAME"]}"\n'
            'version = "0.1.0"\n'
        )
        return [PlannedFile("Cargo.lock", text, "generated:cargo-lock", "starter")]
    if r.project_type == "node":
        name = v["NPM_PACKAGE_NAME"]
        lock = {
            "name": name,
            "version": "0.1.0",
            "lockfileVersion": 3,
            "requires": True,
            "packages": {"": {"name": name, "version": "0.1.0", "engines": {"node": f">={r.node_version}"}}},
        }
        return [PlannedFile("package-lock.json", json.dumps(lock, indent=2) + "\n", "generated:npm-lock", "starter")]
    return []


def _read(template: str) -> str:
    return (TEMPLATES / template).read_text(encoding="utf-8")


def _render_file(template: str, path: str, v: dict[str, str], *, lang: str | None = None) -> str:
    text = renderer.render(_read(template), v, user_vars=USER_VARS, context=renderer.context_for(path))
    if lang:
        text = renderer.drop_missing_commands(text, lang)
    if renderer.NO_COMMAND in text:
        raise ScaffoldError(f"{path}: a command placeholder is left in a place that cannot hold a note")
    return renderer.tidy(text, path)


def merge_gitignore(generated: str, existing: str | None) -> str:
    """Keep every existing line; append generated lines that are missing."""
    if not existing:
        return generated
    have = {line.strip() for line in existing.splitlines()}
    missing = [
        line
        for line in generated.splitlines()
        if line.strip() and not line.startswith("#") and line.strip() not in have
    ]
    if not missing:
        return existing if existing.endswith("\n") else existing + "\n"
    base = existing if existing.endswith("\n") else existing + "\n"
    return base + "\n# Added by repo-bootstrap\n" + "\n".join(missing) + "\n"


def build_plan(
    r: BootstrapRequest,
    decisions: list[FeatureDecision],
    pins: dict[str, dict],
    *,
    target: Path | None = None,
    include_starter: bool = True,
) -> list[PlannedFile]:
    v = build_variables(r, pins)
    files: list[PlannedFile] = []

    for template, path, lang in _doc_entries(r.docs_locale):
        files.append(PlannedFile(path, _render_file(template, path, v, lang=lang), template, "doc"))

    # .gitignore = base + language-specific part, merged with an existing file.
    gi = _read("common/.gitignore.base")
    lang_ignore = {"rust": "rust", "python": "python", "node": "node", "java-maven": "java"}.get(r.project_type)
    if lang_ignore:
        gi = gi.rstrip("\n") + "\n\n# " + r.project_type + "\n" + _read(f"common/.gitignore.{lang_ignore}")
    existing_gi = None
    if target is not None and (target / ".gitignore").is_file():
        existing_gi = (target / ".gitignore").read_text(encoding="utf-8")
    files.append(
        PlannedFile(
            ".gitignore", merge_gitignore(renderer.tidy(gi, ".gitignore"), existing_gi), "common/.gitignore.*", "config"
        )
    )
    files.append(PlannedFile(".gitattributes", _read("common/.gitattributes"), "common/.gitattributes", "config"))
    files.append(PlannedFile(".editorconfig", _read("common/.editorconfig"), "common/.editorconfig", "config"))

    ci_on = decision(decisions, "ci").action == "apply"
    gitleaks_on = decision(decisions, "gitleaks").action == "apply"
    existing_workflows = bool(target and any((target / ".github" / "workflows").glob("*.y*ml")))
    eco = DEPENDABOT_ECOSYSTEM.get(r.project_type)
    if ci_on or gitleaks_on or existing_workflows or eco:
        block = ""
        if eco:
            eco_text = renderer.render(_read("common/dependabot.ecosystem.tpl"), {"DEPENDABOT_ECOSYSTEM": eco})
            block = "\n".join(("  " + line) if line else line for line in eco_text.rstrip("\n").split("\n"))
        text = renderer.render(_read("common/dependabot.yml.tpl"), {"DEPENDABOT_PROJECT_ECOSYSTEM_BLOCK": block})
        files.append(
            PlannedFile(".github/dependabot.yml", renderer.tidy(text, "x.yml"), "common/dependabot.yml.tpl", "config")
        )

    if renders_coderabbit_config(r, decisions):
        files.append(
            PlannedFile(
                ".coderabbit.yaml",
                _render_file("common/.coderabbit.yaml.tpl", ".coderabbit.yaml", v),
                "common/.coderabbit.yaml.tpl",
                "config",
            )
        )
    if r.license == "MIT":
        files.append(
            PlannedFile(
                "LICENSE", _render_file("common/LICENSE.MIT.tpl", "LICENSE", v), "common/LICENSE.MIT.tpl", "config"
            )
        )
    files.append(
        PlannedFile(
            ".github/ISSUE_TEMPLATE/bug_report.yml",
            _render_file("common/issue-bug.yml.tpl", ".github/ISSUE_TEMPLATE/bug_report.yml", v),
            "common/issue-bug.yml.tpl",
            "config",
        )
    )
    files.append(
        PlannedFile(
            ".repo-bootstrap.yml",
            _render_file("common/repo-bootstrap.yml.tpl", ".repo-bootstrap.yml", v),
            "common/repo-bootstrap.yml.tpl",
            "meta",
        )
    )
    if gitleaks_on:
        files.append(
            PlannedFile(
                ".github/workflows/secret-scan.yml",
                _render_file("common/secret-scan.yml.tpl", "secret-scan.yml", v),
                "common/secret-scan.yml.tpl",
                "ci",
            )
        )
    if ci_on:
        tpl = f"ci/{r.project_type}.yml.tpl"
        files.append(PlannedFile(".github/workflows/ci.yml", _render_file(tpl, "ci.yml", v), tpl, "ci"))

    if include_starter:
        for template, path in _starter_entries(r, v):
            files.append(PlannedFile(path, _render_file(template, path, v), template, "starter"))
        files.extend(_generated_lockfiles(r, v))

    paths = [f.path for f in files]
    if len(paths) != len(set(paths)):
        raise ScaffoldError("Two templates render to the same path")
    return files


def parse_profile(text: str) -> dict:
    """Parse ``.repo-bootstrap.yml`` (flat ``key: value`` lines written by this skill)."""
    data: dict = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, raw = line.partition(":")
        raw = raw.strip()
        if raw.startswith('"') or raw in ("null", "true", "false") or raw.isdigit():
            data[key.strip()] = json.loads(raw)
        else:
            data[key.strip()] = raw
    return data


def read_profile(path: Path) -> dict:
    return parse_profile(path.read_text(encoding="utf-8"))
