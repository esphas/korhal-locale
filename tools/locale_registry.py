"""Korhal locale mod registry — en sources and upstream dependencies per localized mod."""
from __future__ import annotations

import json
import re
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("mods.json")
WORKSPACE = Path(__file__).resolve().parents[2]
REFERENCES = WORKSPACE / "references"


def load_registry() -> dict[str, dict]:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{REGISTRY_PATH.name} must be a JSON object keyed by mod id")
    for mod_id, entry in data.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{mod_id}: registry entry must be an object")
        if "en" not in entry or not isinstance(entry["en"], list):
            raise ValueError(f"{mod_id}: missing or invalid 'en' locale source list")
        entry.setdefault("dependencies", [])
        entry.setdefault("optional_dependencies", [])
        entry.setdefault("incompatible", [])
    return data


def en_source_map(registry: dict[str, dict] | None = None) -> dict[str, list[str]]:
    registry = registry or load_registry()
    return {mod_id: entry["en"] for mod_id, entry in registry.items()}


def _dependency_ids(entry: dict, *fields: str) -> list[str]:
    ids: list[str] = []
    for field in fields:
        for dep in entry.get(field, []):
            if dep not in ids:
                ids.append(dep)
    return ids


def localized_required_dependencies(
    mod_id: str, registry: dict[str, dict] | None = None
) -> list[str]:
    registry = registry or load_registry()
    entry = registry.get(mod_id)
    if not entry:
        return []
    return [dep for dep in _dependency_ids(entry, "dependencies") if dep in registry]


def localized_optional_dependencies(
    mod_id: str, registry: dict[str, dict] | None = None
) -> list[str]:
    registry = registry or load_registry()
    entry = registry.get(mod_id)
    if not entry:
        return []
    return [
        dep for dep in _dependency_ids(entry, "optional_dependencies") if dep in registry
    ]


def localized_dependencies(mod_id: str, registry: dict[str, dict] | None = None) -> list[str]:
    """Korhal-localized deps for locale overlap (required + optional)."""
    registry = registry or load_registry()
    entry = registry.get(mod_id)
    if not entry:
        return []
    return [
        dep
        for dep in _dependency_ids(entry, "dependencies", "optional_dependencies")
        if dep in registry
    ]


def conditional_stacks(registry: dict[str, dict] | None = None) -> list[dict[str, object]]:
    """Mods that override locale of other korhal-localized dependencies when active."""
    registry = registry or load_registry()
    stacks: list[dict[str, object]] = []
    for mod_id in sorted(registry):
        deps = localized_dependencies(mod_id, registry)
        if deps:
            stacks.append({"id": mod_id, "anchor": mod_id, "dependencies": deps})
    return stacks


def mod_id_from_constraint(raw: str) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    first = re.split(r"\s|>=|<=|>|<|=", raw, maxsplit=1)[0]
    if first in {"base", "space-age", "quality"}:
        return None
    return first or None


def classify_dependency_entry(dep: str) -> tuple[str, str] | None:
    """Map one info.json dependency string to (kind, mod_id).

    kind is ``required``, ``optional``, or ``incompatible`` (Factorio ``!``).
    """
    s = dep.strip()
    if not s:
        return None

    if s.startswith("!"):
        mod_id = mod_id_from_constraint(s[1:].strip())
        return ("incompatible", mod_id) if mod_id else None

    if s.startswith("(?"):
        mod_id = mod_id_from_constraint(s[3:].strip())
        return ("optional", mod_id) if mod_id else None

    if s.startswith("?"):
        mod_id = mod_id_from_constraint(s[1:].strip())
        return ("optional", mod_id) if mod_id else None

    if s.startswith("+"):
        mod_id = mod_id_from_constraint(s[1:].strip())
        return ("optional", mod_id) if mod_id else None

    if s.startswith("~"):
        mod_id = mod_id_from_constraint(s[1:].strip())
        return ("optional", mod_id) if mod_id else None

    if s.startswith("(") and ")" in s:
        inner = s[1 : s.index(")")].strip()
        mod_id = mod_id_from_constraint(inner)
        return ("required", mod_id) if mod_id else None

    mod_id = mod_id_from_constraint(s)
    return ("required", mod_id) if mod_id else None


def parse_info_dependencies(deps: list[str]) -> dict[str, list[str]]:
    required: list[str] = []
    optional: list[str] = []
    incompatible: list[str] = []

    for dep in deps:
        classified = classify_dependency_entry(dep)
        if not classified:
            continue
        kind, mod_id = classified
        bucket = {"required": required, "optional": optional, "incompatible": incompatible}[
            kind
        ]
        if mod_id not in bucket:
            bucket.append(mod_id)

    return {
        "dependencies": required,
        "optional_dependencies": optional,
        "incompatible": incompatible,
    }


def find_reference_dir(mod_id: str) -> Path | None:
    candidates: list[tuple[tuple[int, ...], Path]] = []
    for entry in REFERENCES.iterdir():
        if not entry.is_dir():
            continue
        info = entry / "info.json"
        if info.is_file():
            meta = json.loads(info.read_text(encoding="utf-8"))
            if meta.get("name") == mod_id:
                version = meta.get("version", "0")
                parts = tuple(int(x) for x in re.findall(r"\d+", version))
                candidates.append((parts, entry))
        elif entry.name == mod_id or entry.name.startswith(f"{mod_id}_"):
            candidates.append(((0,), entry))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def dependencies_from_reference(mod_id: str) -> dict[str, list[str]]:
    ref_dir = find_reference_dir(mod_id)
    if not ref_dir:
        return {"dependencies": [], "optional_dependencies": [], "incompatible": []}
    info = ref_dir / "info.json"
    if not info.is_file():
        return {"dependencies": [], "optional_dependencies": [], "incompatible": []}
    meta = json.loads(info.read_text(encoding="utf-8"))
    return parse_info_dependencies(meta.get("dependencies", []))
