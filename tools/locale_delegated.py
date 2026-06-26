"""Parse and maintain korhal-delegated locale blocks in anchor cfg files."""
from __future__ import annotations

import re
from pathlib import Path

DELEGATED_BEGIN = "# korhal-delegated-begin"
DELEGATED_END = "# korhal-delegated-end"
DELEGATED_HEADER = (
    "# Keys below overlap upstream mods; applied via locale-align when this anchor is active."
)


def _parse_cfg_lines(lines: list[str], *, skip_delegated_block: bool) -> dict[str, str]:
    data: dict[str, str] = {}
    section: str | None = None
    in_delegated = False

    for line in lines:
        stripped = line.strip()
        if stripped == DELEGATED_BEGIN:
            in_delegated = True
            continue
        if stripped == DELEGATED_END:
            in_delegated = False
            continue
        if skip_delegated_block and in_delegated:
            continue

        if stripped.startswith("#"):
            if not in_delegated:
                continue
            stripped = stripped[1:].strip()
            if not stripped:
                continue

        match = re.match(r"\[(.+)\]", stripped)
        if match:
            section = match.group(1)
            continue

        if "=" in stripped and section:
            key, value = stripped.split("=", 1)
            data[f"{section}|{key.strip()}"] = value

    return data


def parse_runtime_cfg(path: Path) -> dict[str, str]:
    """Locale keys loaded by Factorio (excludes korhal-delegated block)."""
    return _parse_cfg_lines(path.read_text(encoding="utf-8").splitlines(), skip_delegated_block=True)


def parse_delegated_cfg(path: Path) -> dict[str, str]:
    """Authoring-only keys inside the korhal-delegated comment block."""
    lines = path.read_text(encoding="utf-8").splitlines()
    in_delegated = False
    delegated_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == DELEGATED_BEGIN:
            in_delegated = True
            continue
        if stripped == DELEGATED_END:
            break
        if in_delegated:
            delegated_lines.append(line)
    return _parse_commented_cfg(delegated_lines)


def _parse_commented_cfg(lines: list[str]) -> dict[str, str]:
    data: dict[str, str] = {}
    section: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            stripped = stripped[1:].strip()
        if not stripped:
            continue
        match = re.match(r"\[(.+)\]", stripped)
        if match:
            section = match.group(1)
            continue
        if "=" in stripped and section:
            key, value = stripped.split("=", 1)
            data[f"{section}|{key.strip()}"] = value
    return data


def parse_full_cfg(path: Path) -> dict[str, str]:
    runtime = parse_runtime_cfg(path)
    delegated = parse_delegated_cfg(path)
    merged = dict(runtime)
    merged.update(delegated)
    return merged


def format_delegated_block(delegated: dict[str, str]) -> list[str]:
    if not delegated:
        return []

    by_section: dict[str, list[tuple[str, str]]] = {}
    for compound, value in sorted(delegated.items()):
        section, key = compound.split("|", 1)
        by_section.setdefault(section, []).append((key, value))

    rows = [DELEGATED_BEGIN, f"# {DELEGATED_HEADER.lstrip('# ')}", ""]
    for section in sorted(by_section):
        rows.append(f"# [{section}]")
        for key, value in by_section[section]:
            rows.append(f"# {key}={value}")
        rows.append("")
    rows.append(DELEGATED_END)
    return rows


def rewrite_cfg(path: Path, delegated: dict[str, str]) -> tuple[int, bool]:
    """Remove delegated keys from runtime body; write them into the comment block."""
    lines = path.read_text(encoding="utf-8").splitlines()
    had_block = any(line.strip() == DELEGATED_BEGIN for line in lines)
    body_lines: list[str] = []
    in_delegated = False
    section: str | None = None
    removed = 0

    for line in lines:
        stripped = line.strip()
        if stripped == DELEGATED_BEGIN:
            in_delegated = True
            continue
        if in_delegated:
            if stripped == DELEGATED_END:
                in_delegated = False
            continue

        match = re.match(r"\[(.+)\]", stripped)
        if match:
            section = match.group(1)
            body_lines.append(line)
            continue

        if "=" in stripped and section and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            compound = f"{section}|{key}"
            if compound in delegated:
                removed += 1
                continue

        body_lines.append(line)

    while body_lines and not body_lines[-1].strip():
        body_lines.pop()

    out = body_lines[:]
    if delegated:
        if out:
            out.append("")
        out.extend(format_delegated_block(delegated))

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return removed, had_block and not delegated
