"""Persist runtime-configured settings back into the API's .env file.

Used by admin-page configuration flows (BP cuff pairing, HIS connection):
the change is applied in-memory first (effective immediately) and then
upserted here so it survives a restart. Repo convention: plain KEY=VALUE
lines, no quoting needed for these values.
"""

from __future__ import annotations

from pathlib import Path


def persist_env_keys(values: dict[str, str]) -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(values)
    for idx, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            lines[idx] = f"{key}={remaining.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
