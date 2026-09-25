from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
KEYWORDS_PATH = ROOT / "data" / "sources" / "seed_keywords.csv"

FIELDNAMES = [
    "source_id",
    "url",
    "platform",
    "keyword",
    "category",
    "creator",
    "title",
    "status",
    "notes",
]

TIKTOK_HOSTS = {
    "www.tiktok.com",
    "tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}


def normalize_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)

    if parts.scheme not in {"http", "https"}:
        raise ValueError("URL must start with http:// or https://")

    host = parts.netloc.lower()
    if host not in TIKTOK_HOSTS:
        raise ValueError(f"Only TikTok URLs are accepted in Step 1. Got host: {host}")

    # Remove query strings/fragments so the same video is not stored twice
    # just because it was copied with different tracking parameters.
    return urlunsplit(("https", host, parts.path.rstrip("/"), "", ""))


def load_keyword_categories() -> dict[str, str]:
    mapping: dict[str, str] = {}
    with KEYWORDS_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            mapping[row["keyword"].strip()] = row["category"].strip()
    return mapping


def load_rows() -> list[dict[str, str]]:
    if not SOURCES_PATH.exists():
        return []

    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def next_source_id(rows: list[dict[str, str]]) -> str:
    max_id = 0
    pattern = re.compile(r"^SRC(\d+)$")

    for row in rows:
        match = pattern.match(row.get("source_id", ""))
        if match:
            max_id = max(max_id, int(match.group(1)))

    return f"SRC{max_id + 1:04d}"


def append_source(
    url: str,
    keyword: str,
    creator: str = "",
    title: str = "",
    notes: str = "",
) -> dict[str, str]:
    normalized_url = normalize_url(url)
    rows = load_rows()

    for row in rows:
        if normalize_url(row["url"]) == normalized_url:
            raise ValueError(
                f"Duplicate URL: already stored as {row['source_id']}"
            )

    keyword_categories = load_keyword_categories()
    category = keyword_categories.get(keyword.strip(), "unclassified")

    row = {
        "source_id": next_source_id(rows),
        "url": normalized_url,
        "platform": "tiktok",
        "keyword": keyword.strip(),
        "category": category,
        "creator": creator.strip(),
        "title": title.strip(),
        "status": "new",
        "notes": notes.strip(),
    }

    SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)

    file_exists = SOURCES_PATH.exists() and SOURCES_PATH.stat().st_size > 0
    with SOURCES_PATH.open("a", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Add one TikTok recipe candidate URL to video_sources.csv."
    )
    parser.add_argument("--url", required=True, help="TikTok video/share URL")
    parser.add_argument("--keyword", required=True, help="Keyword used to find it")
    parser.add_argument("--creator", default="", help="Optional creator name")
    parser.add_argument("--title", default="", help="Optional caption/title")
    parser.add_argument("--notes", default="", help="Optional notes")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        row = append_source(
            url=args.url,
            keyword=args.keyword,
            creator=args.creator,
            title=args.title,
            notes=args.notes,
        )
    except ValueError as exc:
        raise SystemExit(f"[ERROR] {exc}") from exc

    print("[OK] Added source")
    print(f"  source_id : {row['source_id']}")
    print(f"  keyword   : {row['keyword']}")
    print(f"  category  : {row['category']}")
    print(f"  url       : {row['url']}")


if __name__ == "__main__":
    main()
