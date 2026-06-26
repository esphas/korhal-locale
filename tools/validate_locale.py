#!/usr/bin/env python3
"""Validate korhal zh-CN locale cfg keys against upstream English sources."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
REFERENCES = WORKSPACE / "references"
from locale_delegated import parse_full_cfg
from locale_registry import REGISTRY_PATH, en_source_map, load_registry

LOCALE_DIR = ROOT / "locale" / "zh-CN"
SKIP_CFG = {"meta.cfg"}


def mod_name_aliases(mod_id: str) -> dict[str, str]:
    """Map upstream English keys to korhal equivalents in [mod-name]."""
    return {f"mod-name|title": f"mod-name|{mod_id}"}


def mod_description_aliases(mod_id: str) -> dict[str, str]:
    """Map generic mod-description keys to mod-id keyed entries."""
    return {f"mod-description|description": f"mod-description|{mod_id}"}


def diff_keys(
    en_keys: set[str], zh_keys: set[str], mod_id: str
) -> tuple[set[str], set[str]]:
    alias = {**mod_name_aliases(mod_id), **mod_description_aliases(mod_id)}
    missing: set[str] = set()
    for key in en_keys:
        if key in zh_keys:
            continue
        alt = alias.get(key)
        if alt and alt in zh_keys:
            continue
        missing.add(key)

    extra: set[str] = set()
    reverse = {v: k for k, v in alias.items()}
    for key in zh_keys:
        if key in en_keys:
            continue
        alt = reverse.get(key)
        if alt and alt in en_keys:
            continue
        extra.add(key)
    return missing, extra


def parse_cfg_loose(path: Path) -> dict[str, str]:
    """Include keys before the first [section] (runtime messages)."""
    data: dict[str, str] = {}
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";"):
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


def parse_cfg(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    section: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith(";"):
            continue
        match = re.match(r"\[(.+)\]", raw)
        if match:
            section = match.group(1)
            continue
        if "=" in raw and section:
            key, value = raw.split("=", 1)
            data[f"{section}|{key.strip()}"] = value
    return data


def parse_cfg_auto(path: Path) -> dict[str, str]:
    data = parse_cfg(path)
    return data if data else parse_cfg_loose(path)


def parse_version(version: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", version)
    return tuple(int(part) for part in parts) if parts else (0,)


def read_mod_info(path: Path) -> tuple[str | None, str | None]:
    info_path = path / "info.json"
    if not info_path.is_file():
        return None, None
    data = json.loads(info_path.read_text(encoding="utf-8"))
    name = data.get("name")
    version = data.get("version")
    return (
        name if isinstance(name, str) else None,
        version if isinstance(version, str) else None,
    )


def folder_matches_mod_id(folder_name: str, mod_id: str) -> bool:
    if folder_name == mod_id:
        return True
    return bool(re.match(rf"^{re.escape(mod_id)}[_-]", folder_name))


def find_reference_candidates(mod_id: str) -> list[tuple[tuple[int, ...], Path, str | None]]:
    if not REFERENCES.is_dir():
        return []

    candidates: list[tuple[tuple[int, ...], Path, str | None]] = []
    for entry in REFERENCES.iterdir():
        if not entry.is_dir():
            continue

        info_name, info_version = read_mod_info(entry)
        if info_name == mod_id:
            version_key = parse_version(info_version or "0")
            candidates.append((version_key, entry, info_version))
            continue

        if info_name is None and folder_matches_mod_id(entry.name, mod_id):
            candidates.append(((0,), entry, None))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates


def resolve_latest_reference(
    mod_id: str,
) -> tuple[Path, str | None, list[tuple[Path, str | None]]]:
    candidates = find_reference_candidates(mod_id)
    if not candidates:
        raise FileNotFoundError(
            f"no reference folder for {mod_id!r} under {REFERENCES}"
        )

    _version_key, ref_dir, ref_version = candidates[0]
    older = [(path, version) for _vk, path, version in candidates[1:]]
    return ref_dir, ref_version, older


def default_locale_paths(mod_id: str, ref_dir: Path) -> list[str]:
    for rel in (
        f"locale/en/{mod_id}.cfg",
        "locale/en/en.cfg",
        "locale/en/strings.cfg",
    ):
        if (ref_dir / rel).is_file():
            return [rel]
    raise FileNotFoundError(
        f"no default English locale under {ref_dir.relative_to(WORKSPACE)}; "
        f"add entry to {REGISTRY_PATH.name}"
    )


def resolve_en_paths(
    mod_id: str,
    manifest: dict,
    cli_en: list[str] | None,
) -> tuple[list[Path], Path, str | None, list[tuple[Path, str | None]]]:
    if cli_en:
        paths = [
            Path(path) if Path(path).is_absolute() else WORKSPACE / path
            for path in cli_en
        ]
        return paths, Path("."), None, []

    ref_dir, ref_version, older = resolve_latest_reference(mod_id)
    rel_paths = manifest.get(mod_id) or default_locale_paths(mod_id, ref_dir)
    en_paths = [ref_dir / rel for rel in rel_paths]
    return en_paths, ref_dir, ref_version, older


def load_en_keys(mod_id: str, en_paths: list[Path]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in en_paths:
        if not path.is_file():
            raise FileNotFoundError(f"missing English source: {path}")
        keys = parse_cfg_auto(path)
        overlap = set(merged) & set(keys)
        if overlap:
            sample = sorted(overlap)[0]
            raise ValueError(
                f"duplicate key {sample!r} across English sources for {mod_id}"
            )
        merged.update(keys)
    return merged


def read_header(path: Path) -> tuple[str | None, str | None]:
    lines = path.read_text(encoding="utf-8").splitlines()
    mod_line = lines[0].strip() if lines else ""
    version_line = lines[1].strip() if len(lines) > 1 else ""
    mod_match = re.fullmatch(r"# mod: (.+)", mod_line)
    version_match = re.fullmatch(r"# version: (.+)", version_line)
    return (
        mod_match.group(1) if mod_match else None,
        version_match.group(1) if version_match else None,
    )


def validate_mod(
    mod_id: str,
    manifest: dict,
    *,
    en_override: list[str] | None = None,
    check_header: bool = True,
    strict_version: bool = False,
) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []
    zh_path = LOCALE_DIR / f"{mod_id}.cfg"
    if not zh_path.is_file():
        return [f"{mod_id}: missing {zh_path.relative_to(ROOT)}"]

    try:
        en_paths, ref_dir, ref_version, older_refs = resolve_en_paths(
            mod_id, manifest, en_override
        )
        en_keys = load_en_keys(mod_id, en_paths)
    except (FileNotFoundError, ValueError) as exc:
        return [f"{mod_id}: {exc}"]

    if older_refs:
        skipped = ", ".join(
            f"{path.name} ({version or 'unknown'})" for path, version in older_refs
        )
        warnings.append(
            f"{mod_id}: using latest reference {ref_dir.name} "
            f"({ref_version or '?'}); skipped older: {skipped}"
        )

    zh_keys_set = set(parse_full_cfg(zh_path))
    en_keys_set = set(en_keys)
    missing, extra = diff_keys(en_keys_set, zh_keys_set, mod_id)
    missing = sorted(missing)
    extra = sorted(extra)

    if check_header:
        header_mod, header_version = read_header(zh_path)
        if header_mod != mod_id:
            errors.append(
                f"{mod_id}: header mod mismatch "
                f"(expected {mod_id!r}, got {header_mod!r})"
            )
        if not header_version:
            errors.append(f"{mod_id}: missing or invalid `# version:` header line")
        elif ref_version and header_version != ref_version:
            message = (
                f"{mod_id}: cfg header version {header_version!r} != "
                f"latest reference {ref_version!r} ({ref_dir.name})"
            )
            if strict_version:
                errors.append(message)
            else:
                warnings.append(message)

    if missing:
        errors.append(f"{mod_id}: missing {len(missing)} key(s) from English source")
        for key in missing[:20]:
            errors.append(f"  - {key}")
        if len(missing) > 20:
            errors.append(f"  ... and {len(missing) - 20} more")

    if extra:
        errors.append(f"{mod_id}: {len(extra)} extra key(s) not in English source")
        for key in extra[:20]:
            errors.append(f"  + {key}")
        if len(extra) > 20:
            errors.append(f"  ... and {len(extra) - 20} more")

    for warning in warnings:
        print(f"warn: {warning}", file=sys.stderr)

    if not errors:
        en_label = ", ".join(
            path.relative_to(ref_dir).as_posix() for path in en_paths
        )
        ref_label = ref_dir.relative_to(WORKSPACE).as_posix()
        print(
            f"OK  {mod_id}: {len(zh_keys_set)} keys "
            f"(ref: {ref_label} @ {ref_version or '?'}, en: {en_label}, "
            f"cfg: {read_header(zh_path)[1]})"
        )
    return errors


def discover_mod_ids() -> list[str]:
    return sorted(
        path.stem for path in LOCALE_DIR.glob("*.cfg") if path.name not in SKIP_CFG
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mod_id",
        nargs="?",
        help="mod id to validate (default: all locale cfg files)",
    )
    parser.add_argument(
        "--en",
        action="append",
        dest="en_paths",
        metavar="PATH",
        help="English source path(s); bypasses references/ lookup",
    )
    parser.add_argument(
        "--no-header",
        action="store_true",
        help="skip two-line header checks",
    )
    parser.add_argument(
        "--strict-version",
        action="store_true",
        help="fail if cfg # version: differs from latest reference info.json",
    )
    args = parser.parse_args()

    manifest = en_source_map()
    mod_ids = [args.mod_id] if args.mod_id else discover_mod_ids()

    all_errors: list[str] = []
    for mod_id in mod_ids:
        all_errors.extend(
            validate_mod(
                mod_id,
                manifest,
                en_override=args.en_paths,
                check_header=not args.no_header,
                strict_version=args.strict_version,
            )
        )

    if all_errors:
        print("\n".join(all_errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
