#!/usr/bin/env python3
"""Refresh dependencies in tools/mods.json from references/*/info.json."""
from __future__ import annotations

import json
import sys

from locale_registry import REGISTRY_PATH, dependencies_from_reference, load_registry


DEP_FIELDS = ("dependencies", "optional_dependencies", "incompatible")


def main() -> int:
    registry = load_registry()
    updated = 0
    for mod_id in sorted(registry):
        parsed = dependencies_from_reference(mod_id)
        changed = any(registry[mod_id].get(field) != parsed[field] for field in DEP_FIELDS)
        if changed:
            for field in DEP_FIELDS:
                registry[mod_id][field] = parsed[field]
            updated += 1
            req = len(parsed["dependencies"])
            opt = len(parsed["optional_dependencies"])
            inc = len(parsed["incompatible"])
            print(f"{mod_id}: required={req} optional={opt} incompatible={inc}")
    REGISTRY_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"updated {updated}/{len(registry)} mod(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
