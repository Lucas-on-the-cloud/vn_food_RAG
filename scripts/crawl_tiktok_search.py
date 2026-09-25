from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
KEYWORDS_PATH = ROOT / "data" / "sources" / "seed_keywords.csv"
DEFAULT_PROFILE_DIR = ROOT / ".browser" / "tiktok-profile"

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

VIDEO_URL_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@([^/?#]+)/video/(\d+)",
    re.IGNORECASE,
)
SOURCE_ID_RE = re.compile(r"^SRC(\d+)$")


def canonical_video_url(url: str) -> str | None:
    """Return a stable TikTok video URL or None if this is not a video URL."""

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
        return list(csv.DictReader(file))


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


def launch_context(
    playwright: Playwright,
    browser_name: str,
    profile_dir: Path,
    headless: bool,
) -> BrowserContext:
    """Launch a persistent normal browser profile.

    We intentionally do not implement CAPTCHA or anti-bot bypasses. If TikTok
    asks for verification, use the visible browser and complete it manually.
    """

    profile_dir.mkdir(parents=True, exist_ok=True)

    common = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "viewport": {"width": 1440, "height": 1000},
        "locale": "vi-VN",
    }

    if browser_name == "edge":
        return playwright.chromium.launch_persistent_context(
            channel="msedge",
            **common,
        )

    if browser_name == "chrome":
        return playwright.chromium.launch_persistent_context(
            channel="chrome",
            **common,
        )

    return playwright.chromium.launch_persistent_context(**common)


def extract_visible_video_links(page: Page) -> list[dict[str, str]]:
    """Collect currently rendered TikTok video anchors from the search DOM."""

    raw_items = page.locator('a[href*="/video/"]').evaluate_all(
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


def crawl_keyword(
    page: Page,
    keyword: str,
    limit: int,
    max_scrolls: int,
    scroll_wait_ms: int,
    headless: bool,
) -> list[dict[str, str]]:
    search_url = f"https://www.tiktok.com/search?q={quote(keyword)}"

    print(f"\n[SEARCH] {keyword}")
    print(f"         {search_url}")

    page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3_000)

    found: dict[str, dict[str, str]] = {}
    stagnant_rounds = 0
    previous_count = 0

    for scroll_index in range(max_scrolls + 1):
        for item in extract_visible_video_links(page):
            found[item["url"]] = item

        print(
            f"  scroll {scroll_index:02d}/{max_scrolls}: "
            f"{len(found)}/{limit} unique video links"
        )

        if len(found) >= limit:
            break

        if len(found) == previous_count:
            stagnant_rounds += 1
        else:
            stagnant_rounds = 0
            previous_count = len(found)

        # TikTok can show a verification/login wall. We do not bypass it.
        # In visible mode, give the user one chance to resolve it normally.
        if stagnant_rounds == 3 and not headless and len(found) == 0:
            print(
                "\n[NOTICE] No video links are visible yet. "
                "If TikTok is showing login/CAPTCHA/verification, complete it "
                "in the browser window, then press ENTER here."
            )
            try:
                input()
            except EOFError:
                pass
            stagnant_rounds = 0

        if stagnant_rounds >= 6:
            print("  No new links after several scrolls; stopping this keyword.")
            break

        page.mouse.wheel(0, 5000)
        page.wait_for_timeout(scroll_wait_ms)

    return list(found.values())[:limit]


def save_discovered(
    keyword: str,
    items: list[dict[str, str]],
) -> tuple[int, int]:
    rows = load_source_rows()
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
        url = item["url"]

        if url in existing_urls:
            duplicates += 1
            continue

        rows.append(
            {
                "source_id": f"SRC{source_number:04d}",
                "url": url,
                "platform": "tiktok",
                "keyword": keyword,
                "category": category,
                "creator": item.get("creator", ""),
                "title": item.get("title", ""),
                "status": "new",
                "notes": "auto_discovered_from_tiktok_search",
            }
        )

        existing_urls.add(url)
        source_number += 1
        added += 1

    write_source_rows(rows)
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

    return [row["keyword"].strip() for row in rows if row.get("keyword")]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Search TikTok by keyword, auto-scroll results, collect video URLs, "
            "deduplicate them, and append them to video_sources.csv."
        )
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--keyword",
        help='One keyword, e.g. "món ăn sinh viên"',
    )
    mode.add_argument(
        "--from-seed",
        action="store_true",
        help="Read keywords from data/sources/seed_keywords.csv",
    )

    parser.add_argument(
        "--priority",
        choices=["high", "medium", "low", "all"],
        default="high",
        help="When using --from-seed, select seed priority (default: high)",
    )
    parser.add_argument(
        "--max-keywords",
        type=int,
        default=None,
        help="When using --from-seed, crawl only the first N selected keywords",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum discovered video links per keyword (default: 20)",
    )
    parser.add_argument(
        "--max-scrolls",
        type=int,
        default=25,
        help="Maximum scroll attempts per keyword (default: 25)",
    )
    parser.add_argument(
        "--scroll-wait-ms",
        type=int,
        default=1400,
        help="Wait after each scroll for lazy loading (default: 1400ms)",
    )
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome", "chromium"],
        default="edge",
        help="Browser controlled by Playwright (default: edge)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without a visible browser. Visible mode is recommended first.",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help="Persistent browser profile directory",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.limit <= 0:
        raise SystemExit("--limit must be greater than 0")

    keywords = select_keywords(args)
    if not keywords:
        raise SystemExit("No keywords selected.")

    print("=" * 70)
    print("TikTok Recipe URL Discovery")
    print("=" * 70)
    print(f"Keywords      : {len(keywords)}")
    print(f"Limit/keyword : {args.limit}")
    print(f"Browser       : {args.browser}")
    print(f"Headless      : {args.headless}")
    print(f"Output        : {SOURCES_PATH}")

    total_found = 0
    total_added = 0
    total_duplicates = 0

    try:
        with sync_playwright() as playwright:
            context = launch_context(
                playwright=playwright,
                browser_name=args.browser,
                profile_dir=Path(args.profile_dir),
                headless=args.headless,
            )

            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15_000)

            for keyword in keywords:
                items = crawl_keyword(
                    page=page,
                    keyword=keyword,
                    limit=args.limit,
                    max_scrolls=args.max_scrolls,
                    scroll_wait_ms=args.scroll_wait_ms,
                    headless=args.headless,
                )

                added, duplicates = save_discovered(keyword, items)

                total_found += len(items)
                total_added += added
                total_duplicates += duplicates

                print(
                    f"[SAVED] keyword={keyword!r} "
                    f"found={len(items)} new={added} duplicates={duplicates}"
                )

            context.close()

    except Exception as exc:
        print(f"\n[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        print(
            "\nIf the browser could not launch:\n"
            "  Edge:    python scripts/crawl_tiktok_search.py ... --browser edge\n"
            "  Chrome:  python scripts/crawl_tiktok_search.py ... --browser chrome\n"
            "  Chromium: python -m playwright install chromium\n",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    print("\n" + "=" * 70)
    print("DONE")
    print(f"Collected this run : {total_found}")
    print(f"New URLs saved     : {total_added}")
    print(f"Duplicates skipped : {total_duplicates}")
    print(f"CSV                 : {SOURCES_PATH}")
    print("=" * 70)


if __name__ == "__main__":
    main()
