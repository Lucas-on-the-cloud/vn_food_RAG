from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import time
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright


ROOT = Path(__file__).resolve().parents[1]
SAVETO_URL = "https://saveto.ai/tiktok-transcript-generator/"
DEFAULT_MANIFEST = ROOT / "data" / "transcripts" / "saveto_batch.csv"
RAW_DIR = ROOT / "data" / "transcripts" / "raw"
JSON_DIR = ROOT / "data" / "transcripts" / "json"
REPORT_PATH = ROOT / "data" / "processed" / "saveto" / "acquisition_report.csv"
DEFAULT_PROFILE_DIR = ROOT / ".browser" / "saveto-profile"

STATUS_ENDPOINT = "/api/app/task/check_status"
SUBMIT_ENDPOINT = "/api/v2/app/tr/platform"

INPUT_SELECTORS = (
    'input[type="url"]',
    'input[placeholder*="TikTok" i]',
    'input[placeholder*="link" i]',
    'input[placeholder*="url" i]',
    'textarea[placeholder*="TikTok" i]',
    'textarea[placeholder*="link" i]',
    'textarea[placeholder*="url" i]',
)

BUTTON_TEXT_RE = re.compile(
    r"generate|transcrib|convert|start",
    re.IGNORECASE,
)

SUBMIT_SELECTORS = (
    "#app > div > div > div:nth-child(2) > button",
    "button[type='submit']",
)


class SavetoBrowserError(RuntimeError):
    pass


def extract_completed_transcript(body: dict[str, Any]) -> dict[str, Any] | None:
    """Return completed transcript payload from a Saveto status response."""
    if int(body.get("code", 0) or 0) != 200:
        return None

    data = body.get("data")
    if not isinstance(data, dict):
        return None

    if int(data.get("status", -1)) != 2:
        return None

    segments = data.get("data")
    if not isinstance(segments, list):
        return None

    cleaned_segments = [
        segment
        for segment in segments
        if isinstance(segment, dict)
        and str(segment.get("text", "")).strip()
    ]

    text = "\n".join(
        str(segment.get("text", "")).strip()
        for segment in cleaned_segments
    ).strip()

    if not text:
        return None

    return {
        **data,
        "data": cleaned_segments,
        "text": text,
    }


def response_error(body: dict[str, Any]) -> str | None:
    """Extract an explicit Saveto API error from a frontend network response."""
    code = int(body.get("code", 0) or 0)
    if code in {0, 200}:
        return None

    message = (
        body.get("message")
        or body.get("msg")
        or body.get("error")
        or "unknown Saveto error"
    )
    return f"code={code}: {message}"


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
        "locale": "en-US",
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


async def first_visible(locator) -> Any | None:
    count = await locator.count()

    for index in range(count):
        item = locator.nth(index)
        try:
            if await item.is_visible():
                return item
        except Exception:
            continue

    return None


async def find_url_input(page: Page):
    for selector in INPUT_SELECTORS:
        item = await first_visible(page.locator(selector))
        if item is not None:
            return item

    # Final fallback: choose the first visible text-like input.
    item = await first_visible(
        page.locator(
            'input:not([type]), input[type="text"], textarea'
        )
    )
    if item is not None:
        return item

    raise SavetoBrowserError("Could not find the TikTok URL input on Saveto.")


async def click_generate(page: Page, url_input) -> None:
    # Prefer the exact selector observed in the current Saveto UI.
    for selector in SUBMIT_SELECTORS:
        button = await first_visible(page.locator(selector))
        if button is None:
            continue

        try:
            await button.click(timeout=5_000)
            return
        except Exception:
            continue

    # Fall back to semantic button matching if the DOM layout changes.
    candidates = [
        page.get_by_role("button", name=BUTTON_TEXT_RE),
        page.locator("button").filter(has_text=BUTTON_TEXT_RE),
    ]

    for locator in candidates:
        button = await first_visible(locator)
        if button is None:
            continue

        try:
            await button.click(timeout=5_000)
            return
        except Exception:
            continue

    # Final fallback: some layouts submit on Enter.
    await url_input.press("Enter")


async def submit_and_capture(
    page: Page,
    tiktok_url: str,
    timeout_seconds: float,
    submit_gate: asyncio.Lock,
    submit_state: dict[str, float],
    submit_gap_seconds: float,
) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    result_future: asyncio.Future[dict[str, Any]] = loop.create_future()

    async def inspect_response(response) -> None:
        if result_future.done():
            return

        if (
            STATUS_ENDPOINT not in response.url
            and SUBMIT_ENDPOINT not in response.url
        ):
            return

        try:
            body = await response.json()
        except Exception:
            body = None

        if response.status >= 400:
            try:
                raw_body = await response.text()
            except Exception:
                raw_body = ""

            request_body = response.request.post_data or ""
            detail = (
                f"HTTP {response.status} from {response.url}; "
                f"response={raw_body[:800]!r}; "
                f"request={request_body[:800]!r}"
            )
            if not result_future.done():
                result_future.set_exception(SavetoBrowserError(detail))
            return

        if not isinstance(body, dict):
            return

        error = response_error(body)
        if error:
            if not result_future.done():
                result_future.set_exception(SavetoBrowserError(error))
            return

        if STATUS_ENDPOINT in response.url:
            completed = extract_completed_transcript(body)
            if completed is not None and not result_future.done():
                result_future.set_result(completed)

    def on_response(response) -> None:
        asyncio.create_task(inspect_response(response))

    page.on("response", on_response)

    await page.goto(
        SAVETO_URL,
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    await page.wait_for_timeout(1_500)

    url_input = await find_url_input(page)
    await url_input.fill(tiktok_url)
    await page.wait_for_timeout(300)

    # Keep transcript generation parallel, but serialize/stagger the very
    # short submit step. This avoids a burst of simultaneous POST requests
    # from one shared browser session while all accepted tasks can continue
    # polling concurrently afterwards.
    async with submit_gate:
        now = time.monotonic()
        last_submit = submit_state.get("last_submit", 0.0)
        wait_for = submit_gap_seconds - (now - last_submit)

        if wait_for > 0:
            await asyncio.sleep(wait_for)

        await click_generate(page, url_input)
        submit_state["last_submit"] = time.monotonic()

    try:
        return await asyncio.wait_for(
            result_future,
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise SavetoBrowserError(
            f"Timed out after {timeout_seconds:.0f}s waiting for transcript."
        ) from exc


def save_result(
    row: dict[str, str],
    result: dict[str, Any],
) -> tuple[Path, Path]:
    source_id = row.get("source_id", "")
    url = row.get("url", "")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)

    txt_path = RAW_DIR / f"{source_id}.txt"
    json_path = JSON_DIR / f"{source_id}.json"

    text = str(result.get("text", "")).strip()
    txt_path.write_text(text, encoding="utf-8")

    payload = {
        "source_id": source_id,
        "url": url,
        "title": row.get("title", ""),
        "creator": row.get("creator", ""),
        "provider": "saveto_playwright",
        "status": result.get("status"),
        "segments": result.get("data") or [],
        "text": text,
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return txt_path, json_path


async def process_one(
    context: BrowserContext,
    semaphore: asyncio.Semaphore,
    row: dict[str, str],
    timeout_seconds: float,
    force: bool,
    submit_gate: asyncio.Lock,
    submit_state: dict[str, float],
    submit_gap_seconds: float,
    retries: int,
) -> dict[str, str]:
    source_id = row.get("source_id", "")
    url = row.get("url", "")
    txt_path = RAW_DIR / f"{source_id}.txt"
    json_path = JSON_DIR / f"{source_id}.json"

    if txt_path.exists() and json_path.exists() and not force:
        return {
            "source_id": source_id,
            "url": url,
            "status": "skipped_existing",
            "detail": str(txt_path),
        }

    async with semaphore:
        last_error = ""

        for attempt in range(retries + 1):
            page = await context.new_page()

            try:
                result = await submit_and_capture(
                    page=page,
                    tiktok_url=url,
                    timeout_seconds=timeout_seconds,
                    submit_gate=submit_gate,
                    submit_state=submit_state,
                    submit_gap_seconds=submit_gap_seconds,
                )

                txt_path, _ = save_result(row, result)

                return {
                    "source_id": source_id,
                    "url": url,
                    "status": "success",
                    "detail": (
                        f"{len(result.get('text', ''))} chars -> {txt_path}"
                    ),
                }

            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"

                if attempt < retries:
                    await asyncio.sleep(2.0 * (attempt + 1))

            finally:
                await page.close()

        return {
            "source_id": source_id,
            "url": url,
            "status": "failed",
            "detail": last_error,
        }


def write_report(results: list[dict[str, str]]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with REPORT_PATH.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["source_id", "url", "status", "detail"],
        )
        writer.writeheader()
        writer.writerows(results)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Use the Saveto website through Playwright, process multiple "
            "TikTok URLs concurrently, capture completed transcript responses, "
            "and skip individual failures."
        )
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process all manifest rows by default.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Concurrent Saveto pages (default: 3).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=180.0,
        help="Per-video timeout (default: 180 seconds).",
    )
    parser.add_argument(
        "--submit-gap",
        type=float,
        default=2.0,
        help=(
            "Minimum seconds between Saveto submit clicks in the shared "
            "session (default: 2.0). Polling still runs in parallel."
        ),
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retry failed videos with a fresh page (default: 2).",
    )
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome", "chromium"],
        default="edge",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without visible browser windows.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite transcripts that already exist.",
    )

    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    manifest = Path(args.manifest)

    with manifest.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    if args.limit is not None:
        rows = rows[: args.limit]

    if not rows:
        print("No sources selected.")
        return

    workers = max(1, min(args.workers, len(rows)))
    semaphore = asyncio.Semaphore(workers)
    submit_gate = asyncio.Lock()
    submit_state: dict[str, float] = {"last_submit": 0.0}

    print("=" * 72)
    print("Saveto Playwright Transcript Batch")
    print("=" * 72)
    print(f"Sources  : {len(rows)}")
    print(f"Workers  : {workers}")
    print(f"Browser  : {args.browser}")
    print(f"Headless : {args.headless}")
    print(f"Submit gap: {args.submit_gap}s")
    print(f"Retries   : {args.retries}")
    print()

    async with async_playwright() as playwright:
        context = await launch_context(
            playwright=playwright,
            browser_name=args.browser,
            profile_dir=Path(args.profile_dir),
            headless=args.headless,
        )

        tasks = [
            asyncio.create_task(
                process_one(
                    context=context,
                    semaphore=semaphore,
                    row=row,
                    timeout_seconds=args.timeout_seconds,
                    force=args.force,
                    submit_gate=submit_gate,
                    submit_state=submit_state,
                    submit_gap_seconds=args.submit_gap,
                    retries=args.retries,
                )
            )
            for row in rows
        ]

        results: list[dict[str, str]] = []

        for task in asyncio.as_completed(tasks):
            result = await task
            results.append(result)

            print(
                f"{result['source_id']:8} "
                f"{result['status']:18} "
                f"{result['detail']}"
            )

        await context.close()

    order = {
        row.get("source_id", ""): index
        for index, row in enumerate(rows)
    }
    results.sort(
        key=lambda item: order.get(item.get("source_id", ""), 999999)
    )

    write_report(results)

    success = sum(item["status"] == "success" for item in results)
    skipped = sum(
        item["status"].startswith("skipped")
        for item in results
    )
    failed = sum(item["status"] == "failed" for item in results)

    print()
    print("=" * 72)
    print("DONE")
    print(f"Success : {success}")
    print(f"Skipped : {skipped}")
    print(f"Failed  : {failed}")
    print(f"TXT     : {RAW_DIR}")
    print(f"JSON    : {JSON_DIR}")
    print(f"Report  : {REPORT_PATH}")
    print("=" * 72)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
