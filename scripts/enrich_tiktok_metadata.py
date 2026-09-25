from __future__ import annotations

import argparse
import csv
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
OEMBED_ENDPOINT = "https://www.tiktok.com/oembed"

FIELDNAMES = [
    "source_id",
    "video_id",
    "url",
    "platform",
    "keyword",
    "category",
    "creator",
    "author_name",
    "title",
    "thumbnail_url",
    "relevance_score",
    "relevance_label",
    "status",
    "notes",
]

VIDEO_ID_RE = re.compile(r"/video/(\d+)")

STRONG_RECIPE_TERMS = {
    "cach lam",
    "cong thuc",
    "nguyen lieu",
    "nau",
    "mon",
    "com",
    "canh",
    "xao",
    "kho",
    "chien",
    "rim",
    "luoc",
    "hap",
    "nuong",
    "sot",
    "gia vi",
    "recipe",
}

STUDENT_FRIENDLY_TERMS = {
    "sinh vien",
    "tiet kiem",
    "de lam",
    "don gian",
    "nhanh",
    "15 phut",
    "20 phut",
    "30 phut",
    "duoi 50k",
    "50k",
    "noi com dien",
    "mot chao",
    "1 chao",
    "it nguyen lieu",
}

NEGATIVE_TERMS = {
    "mukbang",
    "food tour",
    "buffet",
    "review quan",
    "review nha hang",
    "an thu",
    "challenge",
}


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    without_marks = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return without_marks.replace("đ", "d").replace("Đ", "D").lower()


def extract_video_id(url: str) -> str:
    match = VIDEO_ID_RE.search(url)
    return match.group(1) if match else ""


def score_relevance(title: str, keyword: str = "") -> tuple[int, str]:
    """Heuristic baseline for recipe relevance.

    This is deliberately simple and interpretable. Later phases can replace it
    with an embedding or classifier baseline after we have human-reviewed data.
    """

    text = strip_accents(f"{title} {keyword}")
    score = 0

    strong_matches = sum(term in text for term in STRONG_RECIPE_TERMS)
    student_matches = sum(term in text for term in STUDENT_FRIENDLY_TERMS)
    negative_matches = sum(term in text for term in NEGATIVE_TERMS)

    score += min(strong_matches, 3)
    score += min(student_matches * 2, 4)
    score -= negative_matches * 3

    score = max(score, 0)

    if score >= 4:
        label = "high"
    elif score >= 2:
        label = "medium"
    else:
        label = "low"

    return score, label


def fetch_oembed(url: str, timeout: int = 20) -> dict:
    query = urlencode({"url": url})
    request = Request(
        f"{OEMBED_ENDPOINT}?{query}",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )

    with urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw)


def load_rows() -> list[dict[str, str]]:
    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = []

        for source_row in reader:
            row = {field: source_row.get(field, "") or "" for field in FIELDNAMES}
            rows.append(row)

        return rows


def write_rows(rows: list[dict[str, str]]) -> None:
    with SOURCES_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def append_note(existing: str, new_note: str) -> str:
    existing = (existing or "").strip()
    if not existing:
        return new_note

    parts = [part.strip() for part in existing.split(";") if part.strip()]
    if new_note not in parts:
        parts.append(new_note)
    return ";".join(parts)


def enrich_row(row: dict[str, str], timeout: int) -> dict[str, str]:
    row["video_id"] = extract_video_id(row["url"])

    metadata = fetch_oembed(row["url"], timeout=timeout)

    title = str(metadata.get("title", "") or "").strip()
    author_name = str(metadata.get("author_name", "") or "").strip()
    thumbnail_url = str(metadata.get("thumbnail_url", "") or "").strip()

    row["title"] = title
    row["author_name"] = author_name
    row["thumbnail_url"] = thumbnail_url

    score, label = score_relevance(title, row.get("keyword", ""))
    row["relevance_score"] = str(score)
    row["relevance_label"] = label
    row["status"] = "metadata_ready"
    row["notes"] = append_note(row.get("notes", ""), "oembed_enriched")

    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich TikTok source URLs with official oEmbed metadata and "
            "calculate a simple recipe-relevance baseline."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N eligible rows.",
    )
    parser.add_argument(
        "--source-id",
        help="Process only one source ID, e.g. SRC0001.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-fetch rows that already have metadata_ready status.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds between requests (default: 0.5).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=20,
        help="HTTP timeout in seconds (default: 20).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    rows = load_rows()
    processed = 0
    success = 0
    failed = 0

    print("=" * 72)
    print("TikTok Metadata Enrichment")
    print("=" * 72)
    print(f"Input/output : {SOURCES_PATH}")

    for index, row in enumerate(rows):
        if args.source_id and row["source_id"] != args.source_id:
            continue

        if not args.force and row.get("status") == "metadata_ready":
            continue

        if args.limit is not None and processed >= args.limit:
            break

        processed += 1
        source_id = row["source_id"]
        print(f"\n[{processed}] {source_id}")
        print(f"    {row['url']}")

        try:
            rows[index] = enrich_row(row, timeout=args.timeout)
            success += 1

            print(f"    title     : {rows[index]['title'][:100]}")
            print(f"    author    : {rows[index]['author_name']}")
            print(
                f"    relevance : {rows[index]['relevance_label']} "
                f"({rows[index]['relevance_score']})"
            )

        except HTTPError as exc:
            failed += 1
            row["video_id"] = extract_video_id(row["url"])
            row["status"] = "metadata_error"
            row["notes"] = append_note(
                row.get("notes", ""),
                f"oembed_http_{exc.code}",
            )
            print(f"    ERROR HTTP {exc.code}")

        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            failed += 1
            row["video_id"] = extract_video_id(row["url"])
            row["status"] = "metadata_error"
            row["notes"] = append_note(
                row.get("notes", ""),
                f"oembed_error_{type(exc).__name__}",
            )
            print(f"    ERROR {type(exc).__name__}: {exc}")

        # Persist after every row so an interrupted run does not lose progress.
        write_rows(rows)

        if args.sleep > 0:
            time.sleep(args.sleep)

    print("\n" + "=" * 72)
    print("DONE")
    print(f"Processed : {processed}")
    print(f"Success   : {success}")
    print(f"Failed    : {failed}")
    print("=" * 72)


if __name__ == "__main__":
    main()
