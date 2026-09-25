from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
DEFAULT_PROFILE_DIR = ROOT / ".browser" / "tiktok-profile"

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
    "cach lam", "cong thuc", "nguyen lieu", "nau", "mon", "com",
    "canh", "xao", "kho", "chien", "rim", "luoc", "hap", "nuong",
    "sot", "gia vi", "recipe",
}

STUDENT_FRIENDLY_TERMS = {
    "sinh vien", "tiet kiem", "de lam", "don gian", "nhanh",
    "15 phut", "20 phut", "30 phut", "duoi 50k", "50k",
    "noi com dien", "mot chao", "1 chao", "it nguyen lieu",
}

NEGATIVE_TERMS = {
    "mukbang", "food tour", "buffet", "review quan",
    "review nha hang", "an thu", "challenge",
}


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    without_marks = "".join(
        char for char in normalized
        if unicodedata.category(char) != "Mn"
    )
    return without_marks.replace("đ", "d").replace("Đ", "D").lower()


def extract_video_id(url: str) -> str:
    match = VIDEO_ID_RE.search(url)
    return match.group(1) if match else ""


def score_relevance(title: str, keyword: str = "") -> tuple[int, str]:
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


def load_rows() -> list[dict[str, str]]:
    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [
            {
                field: source_row.get(field, "") or ""
                for field in FIELDNAMES
            }
            for source_row in reader
        ]


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


async def launch_context(
    playwright: Playwright,
    browser_name: str,
    profile_dir: Path,
    headless: bool,
) -> BrowserContext:
    profile_dir.mkdir(parents=True, exist_ok=True)

    common = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "viewport": {"width": 1440, "height": 1000},
        "locale": "vi-VN",
    }

    if browser_name == "edge":
        return await playwright.chromium.launch_persistent_context(
            channel="msedge",
            **common,
        )

    if browser_name == "chrome":
        return await playwright.chromium.launch_persistent_context(
            channel="chrome",
            **common,
        )

    return await playwright.chromium.launch_persistent_context(**common)


async def first_meta(page: Page, *selectors: str) -> str:
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count() == 0:
            continue

        value = await locator.first.get_attribute("content")
        if value and value.strip():
            return value.strip()

    return ""


async def first_text(page: Page, *selectors: str) -> str:
    for selector in selectors:
        locator = page.locator(selector)
        if await locator.count() == 0:
            continue

        try:
            value = (await locator.first.inner_text(timeout=2000)).strip()
        except Exception:
            continue

        if value:
            return " ".join(value.split())

    return ""


def find_video_object(node: Any, video_id: str) -> dict[str, Any] | None:
    if isinstance(node, dict):
        node_id = str(node.get("id", ""))
        if node_id == video_id and (
            "desc" in node or "author" in node or "video" in node
        ):
            return node

        for value in node.values():
            result = find_video_object(value, video_id)
            if result is not None:
                return result

    elif isinstance(node, list):
        for value in node:
            result = find_video_object(value, video_id)
            if result is not None:
                return result

    return None


async def extract_hydration_metadata(
    page: Page,
    video_id: str,
) -> dict[str, str]:
    locator = page.locator("script#__UNIVERSAL_DATA_FOR_REHYDRATION__")
    if await locator.count() == 0:
        return {}

    try:
        raw = await locator.first.text_content(timeout=3000) or ""
        payload = json.loads(raw)
    except Exception:
        return {}

    item = find_video_object(payload, video_id)
    if not item:
        return {}

    author = item.get("author")
    author_name = ""
    if isinstance(author, dict):
        author_name = str(
            author.get("nickname")
            or author.get("uniqueId")
            or author.get("unique_id")
            or ""
        ).strip()

    video = item.get("video")
    thumbnail_url = ""
    if isinstance(video, dict):
        cover = (
            video.get("cover")
            or video.get("dynamicCover")
            or video.get("originCover")
            or ""
        )
        thumbnail_url = str(cover).strip()

    return {
        "title": str(item.get("desc", "") or "").strip(),
        "author_name": author_name,
        "thumbnail_url": thumbnail_url,
    }


async def extract_browser_metadata(
    page: Page,
    video_id: str,
) -> dict[str, str]:
    hydration = await extract_hydration_metadata(page, video_id)

    title = hydration.get("title", "")
    author_name = hydration.get("author_name", "")
    thumbnail_url = hydration.get("thumbnail_url", "")

    if not title:
        title = await first_text(
            page,
            '[data-e2e="browse-video-desc"]',
            'h1[data-e2e="browse-video-desc"]',
        )

    if not author_name:
        author_name = await first_text(
            page,
            '[data-e2e="browse-username"]',
            '[data-e2e="browse-user-name"]',
        )

    if not title:
        title = await first_meta(
            page,
            'meta[property="og:description"]',
            'meta[name="description"]',
        )

    if not author_name:
        author_name = await first_meta(
            page,
            'meta[property="og:title"]',
        )

    if not thumbnail_url:
        thumbnail_url = await first_meta(
            page,
            'meta[property="og:image"]',
            'meta[name="twitter:image"]',
        )

    return {
        "title": " ".join(title.split()),
        "author_name": " ".join(author_name.split()),
        "thumbnail_url": thumbnail_url.strip(),
    }


async def enrich_one(
    context: BrowserContext,
    semaphore: asyncio.Semaphore,
    index: int,
    row: dict[str, str],
    wait_ms: int,
) -> tuple[int, dict[str, str], str]:
    async with semaphore:
        page = await context.new_page()
        source_id = row["source_id"]

        try:
            video_id = extract_video_id(row["url"])
            row["video_id"] = video_id

            await page.goto(
                row["url"],
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_timeout(wait_ms)

            metadata = await extract_browser_metadata(page, video_id)

            if not metadata["title"]:
                raise RuntimeError(
                    "TikTok page loaded but no usable title/description was found."
                )

            row["title"] = metadata["title"]
            row["author_name"] = metadata["author_name"]
            row["thumbnail_url"] = metadata["thumbnail_url"]

            score, label = score_relevance(
                row["title"],
                row.get("keyword", ""),
            )
            row["relevance_score"] = str(score)
            row["relevance_label"] = label
            row["status"] = "metadata_ready"
            row["notes"] = append_note(
                row.get("notes", ""),
                "browser_metadata_enriched",
            )

            detail = (
                f"{label}({score}) "
                f"{row['title'][:80]}"
            )
            return index, row, detail

        except Exception as exc:
            row["video_id"] = extract_video_id(row["url"])
            row["status"] = "metadata_error"
            row["notes"] = append_note(
                row.get("notes", ""),
                f"browser_metadata_error_{type(exc).__name__}",
            )
            return index, row, f"ERROR {type(exc).__name__}: {exc}"

        finally:
            await page.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enrich TikTok metadata concurrently using multiple Playwright "
            "pages in one persistent browser context."
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
        "--workers",
        type=int,
        default=5,
        help="Concurrent TikTok pages (default: 5).",
    )
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=3000,
        help="Wait after opening each TikTok page (default: 3000ms).",
    )
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome", "chromium"],
        default="edge",
    )
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
    )
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    rows = load_rows()

    eligible: list[tuple[int, dict[str, str]]] = []

    for index, row in enumerate(rows):
        if args.source_id and row["source_id"] != args.source_id:
            continue

        if not args.force and row.get("status") == "metadata_ready":
            continue

        eligible.append((index, dict(row)))

    if args.limit is not None:
        eligible = eligible[: args.limit]

    if not eligible:
        print("No eligible rows to enrich.")
        return

    workers = max(1, min(args.workers, len(eligible)))
    semaphore = asyncio.Semaphore(workers)

    print("=" * 72)
    print("TikTok Metadata Enrichment - Parallel Browser Mode")
    print("=" * 72)
    print(f"Eligible : {len(eligible)}")
    print(f"Workers  : {workers}")
    print(f"Browser  : {args.browser}")
    print(f"Headless : {args.headless}")
    print(f"CSV      : {SOURCES_PATH}")

    success = 0
    failed = 0

    async with async_playwright() as playwright:
        context = await launch_context(
            playwright=playwright,
            browser_name=args.browser,
            profile_dir=Path(args.profile_dir),
            headless=args.headless,
        )

        tasks = [
            asyncio.create_task(
                enrich_one(
                    context=context,
                    semaphore=semaphore,
                    index=index,
                    row=row,
                    wait_ms=args.wait_ms,
                )
            )
            for index, row in eligible
        ]

        for task in asyncio.as_completed(tasks):
            index, updated_row, detail = await task
            rows[index] = updated_row

            if updated_row.get("status") == "metadata_ready":
                success += 1
            else:
                failed += 1

            # Single writer in the event loop: no concurrent CSV writes.
            write_rows(rows)

            print(
                f"{updated_row['source_id']:8} "
                f"{updated_row.get('status', ''):16} "
                f"{detail}"
            )

        await context.close()

    print()
    print("=" * 72)
    print("DONE")
    print(f"Processed : {len(eligible)}")
    print(f"Success   : {success}")
    print(f"Failed    : {failed}")
    print("=" * 72)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
