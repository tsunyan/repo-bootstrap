"""Deterministic template rendering.

Only ``{{UPPER_SNAKE_CASE}}`` placeholders are template variables. GitHub
Actions expressions such as ``${{ github.ref }}`` are left untouched.
"""

from __future__ import annotations

import json
import re

VAR_RE = re.compile(r"(?<!\$)\{\{([A-Z][A-Z0-9_]*)\}\}")
# Any leftover double-brace token that is not a GitHub Actions expression.
UNRESOLVED_RE = re.compile(r"(?<!\$)\{\{[^{}\n]{0,80}\}\}")

# Marker that stands in for a command when the project has none (generic).
NO_COMMAND = "\u0000REPO_BOOTSTRAP_NO_COMMAND\u0000"

NO_COMMAND_TEXT = {
    "ja": "この段階で定義されたコマンドはありません。",
    "en": "No commands are defined at this stage.",
}


class RenderError(ValueError):
    pass


def _md(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _json_inner(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


def _xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


ESCAPERS = {
    "md": _md,
    "toml": _json_inner,  # TOML basic strings accept JSON-style escapes
    "json": _json_inner,
    "yaml_dq": _json_inner,
    "xml": _xml,
    "raw": lambda v: v,
}


def context_for(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".md"):
        return "md"
    if lower.endswith(".toml"):
        return "toml"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith((".yml", ".yaml")):
        return "yaml_dq"
    if lower.endswith(".xml"):
        return "xml"
    return "raw"


def render(
    text: str, variables: dict[str, str], *, user_vars: frozenset[str] = frozenset(), context: str = "raw"
) -> str:
    """Replace placeholders. Values of ``user_vars`` are escaped for ``context``.

    Raises :class:`RenderError` listing every placeholder without a value.
    Undefined strings are an error, never silently blank.
    """
    missing = sorted({m.group(1) for m in VAR_RE.finditer(text) if m.group(1) not in variables})
    if missing:
        raise RenderError("Undefined template variables: " + ", ".join(missing))
    escape = ESCAPERS[context]

    def sub(m: re.Match) -> str:
        key = m.group(1)
        value = variables[key]
        return escape(value) if key in user_vars else value

    return VAR_RE.sub(sub, text)


def find_unresolved(text: str) -> list[str]:
    return sorted(set(UNRESOLVED_RE.findall(text)))


def tidy(text: str, path: str) -> str:
    """Collapse blank runs left by empty optional lines; end with one newline."""
    if path.lower().endswith((".md", ".toml", ".yml", ".yaml")):
        text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() if not path.lower().endswith(".md") else line for line in text.split("\n"))
    return text.rstrip("\n") + "\n"


_BILINGUAL_RE = re.compile(r"(?s)\A(<!--.*?-->\n+)?(## 日本語\n.*?)\n+---\n+(## English\n.*)\Z")


def english_first(text: str) -> str:
    """Put the ``## English`` section of a bilingual document before ``## 日本語``."""
    m = _BILINGUAL_RE.match(text)
    if not m:
        raise RenderError("Bilingual document must be '## 日本語', '---', then '## English'")
    comment = (m.group(1) or "").replace("日本語 / English", "English / 日本語")
    return f"{comment}{m.group(3).rstrip()}\n\n---\n\n{m.group(2).rstrip()}\n"


def drop_missing_commands(text: str, lang: str) -> str:
    """Replace command blocks that only hold NO_COMMAND with a localised note.

    Bilingual templates (lang "ja-en" or "en-ja") always hold the Japanese
    section before the ``## English`` heading; ``english_first`` reorders them
    afterwards.
    """
    if NO_COMMAND not in text:
        return text
    if lang in ("ja-en", "en-ja"):
        marker = "\n## English\n"
        if marker not in text:
            raise RenderError("Bilingual document has no '## English' section")
        head, tail = text.split(marker, 1)
        return drop_missing_commands(head, "ja") + marker + drop_missing_commands(tail, "en")
    note = NO_COMMAND_TEXT[lang]
    fence = re.compile(r"```[a-z]*\n((?:[^\n]*\n)*?)```\n?")

    def fence_sub(m: re.Match) -> str:
        body = [line for line in m.group(1).split("\n") if line.strip()]
        if body and all(NO_COMMAND in line for line in body):
            return note + "\n"
        return m.group(0)

    text = fence.sub(fence_sub, text)
    out: list[str] = []
    for line in text.split("\n"):
        if NO_COMMAND in line:
            replacement = f"- {note}" if line.lstrip().startswith("- ") else note
            if not out or out[-1] != replacement:
                out.append(replacement)
            continue
        out.append(line)
    return "\n".join(out)
