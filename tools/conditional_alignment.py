#!/usr/bin/env python3
"""Generate conditional-overrides.lua from anchor cfg vs localized dependency cfgs.

Reads tools/mods.json: for each mod whose required or optional dependencies include
other korhal-localized mods, compare overlapping English keys and emit Lua when
anchor zh != dependency zh.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from locale_delegated import parse_full_cfg, rewrite_cfg
from locale_registry import (
    conditional_stacks,
    en_source_map,
    localized_optional_dependencies,
    localized_required_dependencies,
    load_registry,
)

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
REFERENCES = WORKSPACE / "references"
LOCALE = ROOT / "locale" / "zh-CN"
OUT_OVERRIDES_LUA = ROOT / "locale-align" / "conditional-overrides.lua"


def parse_cfg_auto(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        match = re.match(r"\[(.+)\]", raw)
        if match:
            section = match.group(1)
            continue
        if "=" in raw:
            if section is None:
                section = "[no-section]"
            key, value = raw.split("=", 1)
            data[f"{section}|{key.strip()}"] = value
    return data


def find_reference_dir(mod_id: str) -> Path:
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
        raise FileNotFoundError(f"no reference for {mod_id!r}")
    candidates.sort(reverse=True)
    return candidates[0][1]


def load_reference_en(mod_id: str, en_sources: dict[str, list[str]]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for rel in en_sources[mod_id]:
        merged.update(parse_cfg_auto(find_reference_dir(mod_id) / rel))
    return merged


def load_korhal_zh(mod_id: str) -> dict[str, str]:
    path = LOCALE / f"{mod_id}.cfg"
    return parse_full_cfg(path) if path.is_file() else {}


def zh_get(zh: dict[str, str], key: str, mod_id: str) -> str:
    if key in zh:
        return zh[key]
    for alias_fn in (
        lambda mid: {f"mod-description|description": f"mod-description|{mid}"},
        lambda mid: {f"mod-name|title": f"mod-name|{mid}"},
    ):
        alt = alias_fn(mod_id).get(key)
        if alt and alt in zh:
            return zh[alt]
    return ""


def standalone_value(key: str, dep_ids: list[str], dep_zh: dict[str, dict[str, str]]) -> str:
    for dep in dep_ids:
        if key in dep_zh.get(dep, {}):
            return dep_zh[dep][key]
    return ""


def lua_string(value: str) -> str:
    normalized = value.replace("\\n", "\n")
    escaped = (
        normalized.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def process_stack(
    stack: dict[str, object],
    en_sources: dict[str, list[str]],
) -> tuple[list[dict[str, str]], int, int, list[str]]:
    stack_id = str(stack["id"])
    anchor = str(stack["anchor"])
    dep_ids: list[str] = list(stack["dependencies"])  # type: ignore[arg-type]

    anchor_en = load_reference_en(anchor, en_sources)
    dep_en_keys: set[str] = set()
    dep_zh = {dep: load_korhal_zh(dep) for dep in dep_ids}
    for dep in dep_ids:
        dep_en_keys |= set(load_reference_en(dep, en_sources))

    overlap = sorted(set(anchor_en) & dep_en_keys)
    anchor_zh = load_korhal_zh(anchor)
    missing_overlap = [
        key for key in overlap if not zh_get(anchor_zh, key, anchor)
    ]
    if missing_overlap:
        print(
            f"warn: {anchor}.cfg missing {len(missing_overlap)} overlap key(s)",
            file=sys.stderr,
        )
        for key in missing_overlap[:10]:
            print(f"  - {key}", file=sys.stderr)
        if len(missing_overlap) > 10:
            print(f"  ... and {len(missing_overlap) - 10} more", file=sys.stderr)

    override_entries: list[dict[str, str]] = []
    skip_sections = {"mod-name", "mod-description"}
    for key in overlap:
        section, name = key.split("|", 1)
        if section in skip_sections:
            continue
        standalone = standalone_value(key, dep_ids, dep_zh)
        anchor_val = zh_get(anchor_zh, key, anchor)
        if anchor_val and anchor_val != standalone:
            override_entries.append(
                {
                    "stack": stack_id,
                    "anchor": anchor,
                    "section": section,
                    "key": name,
                    "text": anchor_val,
                }
            )

    return override_entries, len(overlap), len(override_entries), missing_overlap


def apply_delegated_strips(
    all_overrides: list[dict[str, str]],
    stacks: list[dict[str, object]],
) -> None:
    by_anchor: dict[str, dict[str, str]] = {}
    for entry in all_overrides:
        anchor = entry["anchor"]
        compound = f"{entry['section']}|{entry['key']}"
        by_anchor.setdefault(anchor, {})[compound] = entry["text"]

    for stack in stacks:
        anchor = str(stack["anchor"])
        path = LOCALE / f"{anchor}.cfg"
        if not path.is_file():
            continue
        delegated = by_anchor.get(anchor, {})
        removed, cleared = rewrite_cfg(path, delegated)
        if delegated:
            print(
                f"{anchor}: delegated {len(delegated)} key(s), "
                f"stripped {removed} from runtime cfg"
            )
        elif cleared:
            print(f"{anchor}: cleared delegated block")


def write_overrides_lua(entries: list[dict[str, str]]) -> None:
    rows: list[str] = []
    for entry in sorted(entries, key=lambda e: (e["stack"], e["section"], e["key"])):
        rows.append(
            "  {\n"
            f'    stack = "{entry["stack"]}",\n'
            f'    anchor = "{entry["anchor"]}",\n'
            f'    section = "{entry["section"]}",\n'
            f'    key = "{entry["key"]}",\n'
            f"    text = {lua_string(entry['text'])},\n"
            "  },"
        )
    OUT_OVERRIDES_LUA.parent.mkdir(parents=True, exist_ok=True)
    OUT_OVERRIDES_LUA.write_text(
        "-- Generated by tools/conditional_alignment.py — do not edit by hand.\n"
        "return {\n"
        + "\n".join(rows)
        + "\n}\n",
        encoding="utf-8",
    )


def main() -> int:
    registry = load_registry()
    en_sources = en_source_map(registry)
    stacks = conditional_stacks(registry)
    if not stacks:
        write_overrides_lua([])
        print("no conditional stacks (no localized dependency chains)")
        return 0

    all_overrides: list[dict[str, str]] = []

    for stack in stacks:
        overrides, overlap_n, diff_n, missing = process_stack(stack, en_sources)
        all_overrides.extend(overrides)
        if missing:
            print(
                f"warn: {stack['id']} missing {len(missing)} overlap key(s) in anchor cfg",
                file=sys.stderr,
            )
        anchor = str(stack["id"])
        req_n = len(localized_required_dependencies(anchor, registry))
        opt_n = len(localized_optional_dependencies(anchor, registry))
        print(
            f"{anchor}: overlap={overlap_n} lua_overrides={diff_n} "
            f"localized_deps={len(stack['dependencies'])} "
            f"(required={req_n} optional={opt_n})"
        )

    write_overrides_lua(all_overrides)
    apply_delegated_strips(all_overrides, stacks)
    print(f"total lua_overrides={len(all_overrides)} stacks={len(stacks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
