# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileCopyrightText: 2026 Lany Atwood <lany@colorized.life>

"""Decide whether to publish a Git tag; never upload or modify Git references."""

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

NUMBER = r"(?:0|[1-9][0-9]*)"
VERSION = rf"({NUMBER})\.({NUMBER})\.({NUMBER})(?:-rc({NUMBER}))?"
REGISTRY_URL = "https://api.comfy.org/nodes"


class PublishError(Exception):
    """A failed check must stop publication, rather than permit an upload."""


def parse_version(value, *, tag=False, python_rc=False):
    pattern = VERSION
    if python_rc:
        pattern = pattern.replace("-rc", "-?rc")
    if tag:
        pattern = "v" + pattern
    match = re.fullmatch(pattern, value) if isinstance(value, str) else None
    if match is None:
        raise PublishError(f"Invalid {'tag' if tag else 'version'}: {value!r}")
    major, minor, patch, rc = match.groups()
    # The project's rcN convention compares N numerically, not lexically.
    return (int(major), int(minor), int(patch), int(rc is None), int(rc or 0))


def git(repo, *args):
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise PublishError(f"Git read failed: {result.stderr.strip()}")
    return result.stdout.strip()


def select_tag(repo, requested_tag):
    if requested_tag:
        parse_version(requested_tag, tag=True)
        return requested_tag
    candidates = []
    for tag in git(
        repo, "for-each-ref", "--format=%(refname:strip=2)", "refs/tags/"
    ).splitlines():
        try:
            version = parse_version(tag, tag=True)
        except PublishError:
            print(f"Ignoring historical tag outside vX.Y.Z[-rcN]: {tag!r}")
        else:
            candidates.append((version, tag))
    return max(candidates)[1] if candidates else None


def latest_registry_version(node_id):
    url = f"{REGISTRY_URL}/{urllib.parse.quote(node_id, safe='')}/versions"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise PublishError(f"Registry returned HTTP {response.status}")
            versions = json.load(response)
    except (OSError, ValueError) as exc:
        raise PublishError(f"Registry request failed: {exc}") from exc
    if not isinstance(versions, list):
        raise PublishError("Registry response must be a list of versions")
    parsed = []
    # Include every status: pending/flagged/deleted versions still reserve a version.
    for entry in versions:
        if not isinstance(entry, dict):
            raise PublishError("Registry response contains an invalid version entry")
        value = entry.get("version")
        parsed.append((parse_version(value), value))
    return max(parsed)[1] if parsed else None


def decide(repo, requested_tag=""):
    tag = select_tag(repo, requested_tag)
    if tag is None:
        return {"publish": "false", "reason": "No valid version tags are available."}
    candidate = parse_version(tag, tag=True)
    commit = git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit) is None:
        raise PublishError(f"Tag {tag!r} did not resolve to a commit")
    try:
        metadata = tomllib.loads(git(repo, "show", f"{commit}:pyproject.toml"))
    except ValueError as exc:
        raise PublishError(f"Invalid release pyproject.toml: {exc}") from exc
    project = metadata.get("project")
    if not isinstance(project, dict):
        raise PublishError("Release pyproject.toml is missing [project]")
    node_id = project.get("name")
    if not isinstance(node_id, str) or not node_id.strip():
        raise PublishError("Release pyproject.toml is missing project.name")
    if parse_version(project.get("version"), python_rc=True) != candidate:
        raise PublishError(f"Tag {tag} does not match project.version")
    latest = latest_registry_version(node_id)
    publish = latest is None or candidate > parse_version(latest)
    reason = (
        "Candidate is newer than every registry version."
        if publish
        else "Candidate is equal to or older than the latest registry version."
    )
    return {
        "tag": tag,
        "commit": commit,
        "node_id": node_id,
        "latest": latest or "(none)",
        "publish": str(publish).lower(),
        "reason": reason,
    }


def report(decision):
    print(json.dumps(decision, sort_keys=True))
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a") as stream:
            for key in ("publish", "tag", "commit"):
                if key in decision:
                    stream.write(f"{key}={decision[key]}\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a") as stream:
            stream.write(
                f"Candidate: `{decision.get('tag', '(none)')}`\n\n"
                f"Latest registry version: `{decision.get('latest', '(not queried)')}`\n\n"
                f"Publish: **{decision['publish']}**. {decision['reason']}\n"
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--tag", default="", help="Exact tag; empty selects the highest version"
    )
    args = parser.parse_args(argv)
    try:
        report(decide(args.repo, args.tag))
    except (PublishError, OSError) as exc:
        message = str(exc)
        escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error::{escaped}", file=sys.stderr)
        report({"publish": "false", "reason": f"Publication check failed: {message}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
