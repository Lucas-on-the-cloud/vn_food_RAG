from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
KEYWORDS_PATH = ROOT / "data" / "sources" / "seed_keywords.csv"
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

VIDEO_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([^/?#]+)/video/(\d+)",
    re.IGNORECASE,
)
SOURCE_ID_RE = re.compile(r"^SRC(\d+)$")


def canonical_video_url(url: str) -> str | None:
    if url.startswith("/"):
        url = f"https://www.tiktok.com{url}"

    match = VIDEO_URL_RE.search(url)
    if not match:
        return None

    creator, video_id = match.groups()
    return f"https://www.tiktok.com/@{creator}/video/{video_id}"


def creator_from_url(url: str) -> str:
    match = VIDEO_URL_RE.search(url)
    return match.group(1) if match else ""


def video_id_from_url(url: str) -> str:
    match = VIDEO_URL_RE.search(url)
    return match.group(2) if match else ""


def clean_text(text: str, max_length: int = 400) -> str:
    value = " ".join((text or "").split())
    return value[:max_length]


def load_keyword_rows() -> list[dict[str, str]]:
    with KEYWORDS_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def keyword_category_map() -> dict[str, str]:
    return {
        row["keyword"].strip(): row["category"].strip()
        for row in load_keyword_rows()
    }


def load_source_rows() -> list[dict[str, str]]:
    if not SOURCES_PATH.exists():
        return []

    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        return [
            {
                field: source_row.get(field, "") or ""
                for field in FIELDNAMES
            }
            for source_row in csv.DictReader(file)
        ]


def write_source_rows(rows: list[dict[str, str]]) -> None:
    SOURCES_PATH.parent.mkdir(parents=True, exist_ok=True)

    with SOURCES_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def next_source_number(rows: list[dict[str, str]]) -> int:
    current_max = 0

    for row in rows:
        match = SOURCE_ID_RE.match(row.get("source_id", ""))
        if match:
            current_max = max(current_max, int(match.group(1)))

    return current_max + 1


def current_unique_count(rows: list[dict[str, str]] | None = None) -> int:
    rows = load_source_rows() if rows is None else rows
    return len({
        canonical
        for row in rows
        if (canonical := canonical_video_url(row.get("url", "")))
    })


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


async def extract_visible_video_links(
    page: Page,
) -> list[dict[str, str]]:
    raw_items = await page.locator('a[href*="/video/"]').evaluate_all(
        """
        (elements) => elements.map((a) => ({
            href: a.href || a.getAttribute("href") || "",
            text: (a.innerText || a.textContent || "").trim()
        }))
        """
    )

    results: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in raw_items:
        canonical = canonical_video_url(item.get("href", ""))
        if not canonical or canonical in seen:
            continue

        seen.add(canonical)
        results.append(
            {
                "url": canonical,
                "creator": creator_from_url(canonical),
                "title": clean_text(item.get("text", "")),
            }
        )

    return results


async def crawl_keyword(
    context: BrowserContext,
    semaphore: asyncio.Semaphore,
    keyword: str,
    limit: int,
    max_scrolls: int,
    scroll_wait_ms: int,
) -> tuple[str, list[dict[str, str]], str | None]:
    async with semaphore:
        page = await context.new_page()
        search_url = f"https://www.tiktok.com/search?q={quote(keyword)}"

        try:
            await page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_timeout(3_000)

            found: dict[str, dict[str, str]] = {}
            stagnant_rounds = 0
            previous_count = 0

            for _ in range(max_scrolls + 1):
                for item in await extract_visible_video_links(page):
                    found[item["url"]] = item

                if len(found) >= limit:
                    break

                if len(found) == previous_count:
                    stagnant_rounds += 1
                else:
                    stagnant_rounds = 0
                    previous_count = len(found)

                if stagnant_rounds >= 6:
                    break

                await page.mouse.wheel(0, 5000)
                await page.wait_for_timeout(scroll_wait_ms)

            return keyword, list(found.values())[:limit], None

        except Exception as exc:
            return (
                keyword,
                [],
                f"{type(exc).__name__}: {exc}",
            )

        finally:
            await page.close()


def append_discovered(
    rows: list[dict[str, str]],
    keyword: str,
    items: list[dict[str, str]],
    max_new: int | None,
) -> tuple[int, int]:
    categories = keyword_category_map()
    category = categories.get(keyword, "unclassified")

    existing_urls = {
        canonical
        for row in rows
        if (canonical := canonical_video_url(row.get("url", "")))
    }

    source_number = next_source_number(rows)
    added = 0
    duplicates = 0

    for item in items:
        if max_new is not None and added >= max_new:
            break

        url = item["url"]

        if url in existing_urls:
            duplicates += 1
            continue

        rows.append(
            {
                "source_id": f"SRC{source_number:04d}",
                "video_id": video_id_from_url(url),
                "url": url,
                "platform": "tiktok",
                "keyword": keyword,
                "category": category,
                "creator": item.get("creator", ""),
                "author_name": "",
                "title": item.get("title", ""),
                "thumbnail_url": "",
                "relevance_score": "",
                "relevance_label": "",
                "status": "new",
                "notes": "auto_discovered_from_tiktok_search",
            }
        )

        existing_urls.add(url)
        source_number += 1
        added += 1

    return added, duplicates


def select_keywords(args: argparse.Namespace) -> list[str]:
    if args.keyword:
        return [args.keyword.strip()]

    rows = load_keyword_rows()

    if args.priority != "all":
        rows = [
            row
            for row in rows
            if row.get("priority", "").strip().lower() == args.priority
        ]

    if args.max_keywords is not None:
        rows = rows[: args.max_keywords]

    return [
        row["keyword"].strip()
        for row in rows
        if row.get("keyword")
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Search TikTok recipe keywords concurrently, collect video URLs, "
            "deduplicate them, and append them safely to video_sources.csv."
        )
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--keyword")
    mode.add_argument("--from-seed", action="store_true")

    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--target-new",
        type=int,
        default=None,
        help="Stop saving after N new unique URLs in this run.",
    )
    target.add_argument(
        "--target-total",
        type=int,
        default=None,
        help="Stop saving when the CSV reaches N unique URLs total.",
    )

    parser.add_argument(
        "--priority",
        choices=["high", "medium", "low", "all"],
        default="high",
    )
    parser.add_argument("--max-keywords", type=int, default=None)
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Maximum links collected per keyword.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent TikTok keyword pages (default: 4).",
    )
    parser.add_argument("--max-scrolls", type=int, default=30)
    parser.add_argument("--scroll-wait-ms", type=int, default=1400)
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

    if args.limit <= 0:
        raise SystemExit("--limit must be greater than 0")

    keywords = select_keywords(args)
    if not keywords:
        raise SystemExit("No keywords selected.")

    rows = load_source_rows()
    initial_total = current_unique_count(rows)

    if args.target_total is not None:
        goal_new = max(0, args.target_total - initial_total)
    else:
        goal_new = args.target_new

    if goal_new == 0:
        print(
            f"Already have {initial_total} unique URLs; "
            "requested target is satisfied."
        )
        return

    workers = max(1, min(args.workers, len(keywords)))
    semaphore = asyncio.Semaphore(workers)

    print("=" * 72)
    print("TikTok Recipe URL Discovery - Parallel Keyword Mode")
    print("=" * 72)
    print(f"Existing URLs : {initial_total}")
    print(f"Keywords      : {len(keywords)}")
    print(f"Workers       : {workers}")
    print(f"Limit/keyword : {args.limit}")
    print(
        f"Target new    : "
        f"{goal_new if goal_new is not None else 'unlimited'}"
    )

    total_found = 0
    total_added = 0
    total_duplicates = 0
    failed_keywords = 0

    try:
        async with async_playwright() as playwright:
            context = await launch_context(
                playwright=playwright,
                browser_name=args.browser,
                profile_dir=Path(args.profile_dir),
                headless=args.headless,
            )

            tasks = [
                asyncio.create_task(
                    crawl_keyword(
                        context=context,
                        semaphore=semaphore,
                        keyword=keyword,
                        limit=args.limit,
                        max_scrolls=args.max_scrolls,
                        scroll_wait_ms=args.scroll_wait_ms,
                    )
                )
                for keyword in keywords
            ]

            for task in asyncio.as_completed(tasks):
                keyword, items, error = await task

                if error:
                    failed_keywords += 1
                    print(
                        f"[ERROR] {keyword!r}: {error}"
                    )
                    continue

                remaining = (
                    None
                    if goal_new is None
                    else max(0, goal_new - total_added)
                )

                added, duplicates = append_discovered(
                    rows=rows,
                    keyword=keyword,
                    items=items,
                    max_new=remaining,
                )

                total_found += len(items)
                total_added += added
                total_duplicates += duplicates

                # Only this main event-loop task writes the shared CSV.
                write_source_rows(rows)

                print(
                    f"[SAVED] {keyword!r} "
                    f"found={len(items)} "
                    f"new={added} dup={duplicates} "
                    f"total_new={total_added}"
                )

            await context.close()

    except Exception as exc:
        print(
            f"\n[ERROR] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    final_total = current_unique_count(rows)

    print()
    print("=" * 72)
    print("DONE")
    print(f"Links observed      : {total_found}")
    print(f"New URLs saved      : {total_added}")
    print(f"Duplicates skipped  : {total_duplicates}")
    print(f"Failed keywords     : {failed_keywords}")
    print(f"Total unique URLs   : {final_total}")
    print(f"CSV                 : {SOURCES_PATH}")

    if goal_new is not None and total_added < goal_new:
        print(
            f"NOTE: {goal_new - total_added} additional new URLs are "
            "still needed. Run again or widen keyword priority."
        )

    print("=" * 72)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
