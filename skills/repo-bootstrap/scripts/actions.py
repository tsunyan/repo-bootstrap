"""Resolve GitHub Actions to full 40-character commit SHAs.

Only the actions listed in :data:`ACTIONS` are allowed. A release tag is
taken from the action's own repository (latest release, or an explicit
tag), annotated tags are dereferenced, and anything unexpected fails closed.
"""

from __future__ import annotations

import re

from github_api import GitHubClient, GitHubError

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SEMVER_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")

# key -> (repository, how to pick the revision)
ACTIONS: dict[str, tuple[str, str]] = {
    "ACTION_CHECKOUT": ("actions/checkout", "release"),
    "ACTION_SETUP_NODE": ("actions/setup-node", "release"),
    "ACTION_SETUP_PYTHON": ("actions/setup-python", "release"),
    "ACTION_SETUP_JAVA": ("actions/setup-java", "release"),
    "ACTION_GITLEAKS": ("gitleaks/gitleaks-action", "release"),
    # dtolnay/rust-toolchain publishes no releases; its `stable` branch is the documented ref.
    "ACTION_RUST_TOOLCHAIN": ("dtolnay/rust-toolchain", "branch:stable"),
}


class ActionResolutionError(RuntimeError):
    pass


def resolve_one(client: GitHubClient, key: str, tag: str | None = None) -> dict:
    if key not in ACTIONS:
        raise ActionResolutionError(f"{key} is not an allowed action")
    repo, how = ACTIONS[key]
    try:
        if how.startswith("branch:"):
            branch = how.split(":", 1)[1]
            data = client.get(f"repos/{repo}/branches/{branch}")
            sha = data["commit"]["sha"]
            label = f"{branch} branch"
        else:
            if tag is None:
                release = client.get(f"repos/{repo}/releases/latest")
                if release.get("draft") or release.get("prerelease"):
                    raise ActionResolutionError(f"{repo}: latest release is a draft or prerelease")
                tag = release["tag_name"]
            if not SEMVER_TAG_RE.match(tag):
                raise ActionResolutionError(f"{repo}: tag {tag!r} is not a vMAJOR.MINOR.PATCH release tag")
            ref = client.get(f"repos/{repo}/git/ref/tags/{tag}")
            obj = ref["object"]
            # Annotated tags point to a tag object; follow until a commit.
            for _ in range(3):
                if obj["type"] == "commit":
                    break
                if obj["type"] != "tag":
                    raise ActionResolutionError(f"{repo}@{tag} points to a {obj['type']}, not a commit")
                obj = client.get(f"repos/{repo}/git/tags/{obj['sha']}")["object"]
            if obj["type"] != "commit":
                raise ActionResolutionError(f"{repo}@{tag}: could not reach a commit")
            sha = obj["sha"]
            label = tag
    except GitHubError as exc:
        raise ActionResolutionError(f"{repo}: {exc}") from exc
    except (KeyError, TypeError) as exc:
        raise ActionResolutionError(f"{repo}: unexpected API response ({exc})") from exc
    if not SHA_RE.match(sha):
        raise ActionResolutionError(f"{repo}: resolved revision {sha!r} is not a 40-character SHA")
    return {"repository": repo, "tag": label, "sha": sha}


def resolve(
    client: GitHubClient, keys: list[str], *, previous: dict[str, dict] | None = None, refresh: bool = False
) -> dict[str, dict]:
    """Resolve every key. Reuse pins recorded in the lock unless ``refresh``.

    Reusing keeps a second run byte-identical; Dependabot updates the pins.
    """
    out: dict[str, dict] = {}
    for key in keys:
        old = (previous or {}).get(key)
        if old and not refresh and SHA_RE.match(old.get("sha", "")):
            out[key] = old
            continue
        out[key] = resolve_one(client, key)
    return out
