"""Work out the next release version from git tags and commit messages.

Used by .github/workflows/release.yml; can also be run locally to preview:

    python tools/next_version.py            # automatic bump
    python tools/next_version.py --bump minor

Prints GitHub-Actions output lines (version=..., tag=..., bump=..., previous=...).
`version` is empty when there is nothing to release.

Bump rules (commits since the last vX.Y.Z tag reachable from HEAD):
  major  "BREAKING CHANGE" in a message, a "type!:" subject, or "[major]"
  minor  a subject starting with feat / Add / New, or "[minor]"
  patch  everything else
A HEAD commit containing "[skip release]" produces no release.
The first release (no tags yet) is FIRST_VERSION.
"""

from __future__ import annotations

import argparse
import re
import subprocess

FIRST_VERSION = (1, 0, 0)
SEMVER_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
MAJOR = re.compile(r"BREAKING[ -]CHANGE|^\w+(\([^)]*\))?!:|\[major\]", re.I | re.M)
MINOR = re.compile(r"^(feat(\([^)]*\))?:|add\b|adds\b|added\b|new\b)|\[minor\]", re.I)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def decide_bump(messages: list[str]) -> str:
    if any(MAJOR.search(m) for m in messages):
        return "major"
    if any(MINOR.search(m.strip()) or "[minor]" in m.lower() for m in messages):
        return "minor"
    return "patch"


def bump(version: tuple[int, int, int], kind: str) -> tuple[int, int, int]:
    major, minor, patch = version
    if kind == "major":
        return (major + 1, 0, 0)
    if kind == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def latest_tag() -> tuple[str, tuple[int, int, int]] | None:
    found = []
    for t in git("tag", "--merged", "HEAD", "--list", "v*").split():
        m = SEMVER_TAG.match(t)
        if m:
            found.append((tuple(int(x) for x in m.groups()), t))
    if not found:
        return None
    v, t = max(found)
    return t, v


def messages_since(tag: str | None) -> list[str]:
    rng = [f"{tag}..HEAD"] if tag else ["HEAD"]
    out = git("log", "--format=%B%x00", *rng)
    return [m.strip() for m in out.split("\x00") if m.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bump", choices=["auto", "patch", "minor", "major"], default="auto")
    a = ap.parse_args()

    prev = latest_tag()
    msgs = messages_since(prev[0] if prev else None)
    head = git("log", "-1", "--format=%B")
    out = {"version": "", "tag": "", "bump": "", "previous": prev[0] if prev else ""}

    if a.bump == "auto" and (not msgs or "[skip release]" in head.lower()):
        pass  # nothing new since the last tag, or explicitly skipped
    elif prev is None:
        v = FIRST_VERSION
        out.update(version="%d.%d.%d" % v, tag="v%d.%d.%d" % v, bump="first")
    else:
        kind = decide_bump(msgs) if a.bump == "auto" else a.bump
        v = bump(prev[1], kind)
        out.update(version="%d.%d.%d" % v, tag="v%d.%d.%d" % v, bump=kind)

    for k, val in out.items():
        print(f"{k}={val}")


if __name__ == "__main__":
    main()
