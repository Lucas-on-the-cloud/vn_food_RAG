from __future__ import annotations

import csv
from pathlib import Path


def load_alias_mapping(path: str | Path) -> dict[str, str]:
    """Build multilingual ingredient alias -> canonical English ID mapping."""

    aliases: dict[str, str] = {}

    with open(path, "r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            canonical = row["canonical_name_en"].strip().lower()

            for column in ("canonical_name_en", "name_vi", "name_zh_tw"):
                value = row.get(column, "").strip().lower()
                if value:
                    aliases[value] = canonical

    return aliases


def normalize_ingredient(name: str, aliases: dict[str, str]) -> str | None:
    return aliases.get(name.strip().lower())
