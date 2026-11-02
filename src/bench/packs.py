"""Domain pack registry: discovery, loading, and manifest validation.

A domain pack is a directory under the repo's ``packs/`` declaring itself in a
``pack.yaml`` manifest:

    name: <pack name>                     # must equal the directory name
    version: <str>
    description: <str>
    kinds: [<knowledge-unit kind>, ...]   # at least one
    components:                           # what the pack owns/contributes
      - {type: module|data|db_seed, path: <repo-relative path>}
    eval_suites: [<suite id>, ...]

The kernel understands only the manifest schema above. What a pack's kinds,
components, or eval suites mean is entirely the pack's business; domain
vocabulary never appears here (enforced by the kernel domain-freedom gate),
and adding a pack requires no kernel changes.

Errors are reported faithfully: a pack directory without ``pack.yaml``, an
unreadable manifest, or malformed YAML all raise instead of being swallowed.
"""

from __future__ import annotations

import pathlib
from typing import Any, Optional

import yaml

# src/bench/packs.py -> repo root.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Domain packs live under packs/ in the repo.
PACKS_DIR = REPO_ROOT / "packs"

MANIFEST_NAME = "pack.yaml"

# Component types a pack may declare.
COMPONENT_TYPES = ("module", "data", "db_seed")

# Manifest fields every pack must declare.
_REQUIRED_FIELDS = (
    "name",
    "version",
    "description",
    "kinds",
    "components",
    "eval_suites",
)


def _read_manifest(path: pathlib.Path) -> dict:
    """Parse one manifest file; missing file / malformed YAML raise as-is."""
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data


def list_packs() -> list[dict]:
    """Read every ``packs/*/pack.yaml`` and return the parsed manifests.

    One manifest per subdirectory of :data:`PACKS_DIR`, sorted by directory
    name; non-directory entries are ignored. A directory without a
    ``pack.yaml`` or with malformed YAML raises (never silently skipped).
    """
    out: list[dict] = []
    for entry in sorted(PACKS_DIR.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        out.append(_read_manifest(entry / MANIFEST_NAME))
    return out


def load_pack(name: str) -> dict:
    """Load one pack's manifest by pack (directory) name.

    Raises ``ValueError`` for a name that is not a plain directory name and
    ``FileNotFoundError`` when the pack or its manifest does not exist.
    """
    if (
        not name
        or name in (".", "..")
        or "/" in name
        or "\\" in name
        or pathlib.PurePath(name).name != name
    ):
        raise ValueError(f"invalid pack name: {name!r}")
    return _read_manifest(PACKS_DIR / name / MANIFEST_NAME)


def _check_kinds(manifest: dict, problems: list[str]) -> None:
    kinds = manifest.get("kinds")
    if kinds is None:
        return  # missing-required-field already reported
    if not isinstance(kinds, list):
        problems.append("'kinds' must be a list of strings")
        return
    if not all(isinstance(k, str) and k.strip() for k in kinds):
        problems.append("'kinds' must contain only non-empty strings")
        return
    if not kinds:
        problems.append("'kinds' must not be empty (a pack declares what it provides)")


def _check_components(manifest: dict, problems: list[str]) -> None:
    components = manifest.get("components")
    if components is None:
        return  # missing-required-field already reported
    if not isinstance(components, list):
        problems.append("'components' must be a list")
        return
    repo_root = REPO_ROOT.resolve()
    for i, comp in enumerate(components):
        prefix = f"components[{i}]"
        if not isinstance(comp, dict):
            problems.append(f"{prefix} must be a mapping with 'type' and 'path'")
            continue
        ctype = comp.get("type")
        if ctype not in COMPONENT_TYPES:
            problems.append(
                f"{prefix}: illegal component type {ctype!r} "
                f"(expected one of {list(COMPONENT_TYPES)})"
            )
        cpath = comp.get("path")
        if not isinstance(cpath, str) or not cpath.strip():
            problems.append(f"{prefix}: 'path' must be a non-empty repo-relative string")
            continue
        resolved = (repo_root / cpath).resolve()
        if resolved != repo_root and repo_root not in resolved.parents:
            problems.append(f"{prefix}: path {cpath!r} escapes the repo root")
        elif not resolved.exists():
            problems.append(f"{prefix}: path {cpath!r} does not exist in the repo")


def validate_pack(manifest: Any, *, directory: Optional[str] = None) -> list[str]:
    """Validate one parsed manifest; return the violation list (empty = pass).

    Checks:
    - every required field is present (``name``, ``version``, ``description``,
      ``kinds``, ``components``, ``eval_suites``),
    - ``kinds`` is a non-empty list of non-empty strings,
    - every component has a legal ``type`` and a ``path`` that exists inside
      the repo (paths are repo-relative; escaping the repo root is a
      violation),
    - when the caller passes the pack's ``directory`` name, ``name`` matches
      it.
    """
    problems: list[str] = []
    if not isinstance(manifest, dict):
        return [f"manifest must be a mapping, got {type(manifest).__name__}"]

    for field in _REQUIRED_FIELDS:
        if manifest.get(field) is None:
            problems.append(f"missing required field {field!r}")

    name = manifest.get("name")
    if name is not None and (not isinstance(name, str) or not name.strip()):
        problems.append("'name' must be a non-empty string")

    version = manifest.get("version")
    if version is not None and (not isinstance(version, str) or not version.strip()):
        problems.append("'version' must be a non-empty string")

    description = manifest.get("description")
    if description is not None and not isinstance(description, str):
        problems.append("'description' must be a string")

    _check_kinds(manifest, problems)
    _check_components(manifest, problems)

    eval_suites = manifest.get("eval_suites")
    if eval_suites is not None and (
        not isinstance(eval_suites, list)
        or not all(isinstance(s, str) for s in eval_suites)
    ):
        problems.append("'eval_suites' must be a list of strings")

    if directory is not None and name != directory:
        problems.append(
            f"'name' {name!r} does not match the pack directory {directory!r}"
        )

    return problems
