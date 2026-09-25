from __future__ import annotations

import argparse
import asyncio
import csv
import re
import shutil
import subprocess
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
AUDIO_DIR = ROOT / "data" / "raw" / "audio"
DEFAULT_PROFILE_DIR = ROOT / ".browser" / "tiktok-profile"

VIDEO_ID_RE = re.compile(r"/video/(\d+)")


def load_sources() -> list[dict[str, str]]:
    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


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


def is_http_media_url(url: str) -> bool:
    return (url or "").lower().startswith(("http://", "https://"))


def looks_like_media(url: str, content_type: str = "") -> bool:
    lower_url = (url or "").lower()
    lower_type = (content_type or "").lower()

    return (
        lower_type.startswith("video/")
        or lower_type.startswith("audio/")
        or "mime_type=video" in lower_url
        or "mime_type=audio" in lower_url
        or "tiktokcdn.com/video/" in lower_url
        or "tiktok.com/video/" in lower_url
    )


def build_media_candidates(
    current_src: str,
    captured: list[dict[str, str]],
) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    if is_http_media_url(current_src):
        candidates.append({
            "url": current_src,
            "content_type": "",
            "source": "video.currentSrc",
        })

    for item in captured:
        media_url = item.get("url", "")
        content_type = item.get("content_type", "")

        if not is_http_media_url(media_url):
            continue

        if not looks_like_media(media_url, content_type):
            continue

        candidates.append({
            "url": media_url,
            "content_type": content_type,
            "source": "network",
        })

    unique: list[dict[str, str]] = []
    seen: set[str] = set()

    for item in candidates:
        if item["url"] in seen:
            continue

        seen.add(item["url"])
        unique.append(item)

    def priority(item: dict[str, str]) -> tuple[int, int]:
        url = item["url"].lower()
        content_type = item.get("content_type", "").lower()

        audio_like = (
            content_type.startswith("audio/")
            or "mime_type=audio" in url
            or "/audio/" in url
        )
        video_like = (
            content_type.startswith("video/")
            or "mime_type=video" in url
            or "/video/" in url
        )

        if audio_like:
            kind_rank = 0
        elif video_like:
            kind_rank = 1
        else:
            kind_rank = 2

        source_rank = 0 if item.get("source") == "network" else 1
        return kind_rank, source_rank

    unique.sort(key=priority)
    return unique


async def get_current_video_src(page: Page) -> str:
    locator = page.locator("video")

    if await locator.count() == 0:
        return ""

    try:
        return str(
            await locator.first.evaluate(
                "(video) => video.currentSrc || video.src || ''"
            )
            or ""
        )
    except Exception:
        return ""


async def collect_media_candidates(
    page: Page,
    url: str,
    wait_ms: int,
) -> tuple[list[dict[str, str]], str]:
    captured: list[dict[str, str]] = []

    async def inspect_response(response: Any) -> None:
        try:
            response_url = str(response.url)
            content_type = str(
                response.headers.get("content-type", "") or ""
            )

            if looks_like_media(response_url, content_type):
                captured.append({
                    "url": response_url,
                    "content_type": content_type,
                })
        except Exception:
            pass

    def on_response(response: Any) -> None:
        asyncio.create_task(inspect_response(response))

    page.on("response", on_response)

    await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    await page.wait_for_timeout(wait_ms)

    video = page.locator("video")
    if await video.count() > 0:
        try:
            await video.first.evaluate(
                """async (v) => {
                    try {
                        v.muted = true;
                        await v.play();
                    } catch (_) {}
                }"""
            )
        except Exception:
            pass

    await page.wait_for_timeout(1_500)

    current_src = await get_current_video_src(page)
    candidates = build_media_candidates(current_src, captured)

    if not candidates:
        raise RuntimeError("No HTTP media stream captured.")

    user_agent = str(
        await page.evaluate("() => navigator.userAgent") or ""
    ).strip()

    return candidates, user_agent


async def build_cookie_header(
    context: BrowserContext,
    media_url: str,
) -> str:
    try:
        cookies = await context.cookies([media_url])
    except Exception:
        cookies = []

    return "; ".join(
        f"{cookie.get('name')}={cookie.get('value')}"
        for cookie in cookies
        if cookie.get("name")
    )


def extract_candidate_audio_sync(
    media_url: str,
    output_path: Path,
    user_agent: str,
    referer: str,
    cookie_header: str,
) -> tuple[bool, str]:
    headers = [f"Referer: {referer}"]

    if cookie_header:
        headers.append(f"Cookie: {cookie_header}")

    header_value = "\r\n".join(headers) + "\r\n"

    command = ["ffmpeg", "-y", "-loglevel", "error"]

    if user_agent:
        command.extend(["-user_agent", user_agent])

    command.extend([
        "-headers",
        header_value,
        "-i",
        media_url,
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "flac",
        "-compression_level",
        "8",
        str(output_path),
    ])

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    ok = (
        result.returncode == 0
        and output_path.exists()
        and output_path.stat().st_size > 100
    )

    details = (result.stderr or result.stdout or "").strip()
    return ok, details


async def save_audio_from_candidates(
    context: BrowserContext,
    candidates: list[dict[str, str]],
    output_path: Path,
    user_agent: str,
    referer: str,
) -> dict[str, str]:
    errors: list[str] = []

    for candidate in candidates:
        media_url = candidate["url"]
        cookie_header = await build_cookie_header(context, media_url)

        if output_path.exists():
            output_path.unlink()

        ok, details = await asyncio.to_thread(
            extract_candidate_audio_sync,
            media_url,
            output_path,
            user_agent,
            referer,
            cookie_header,
        )

        if ok:
            return candidate

        compact = " ".join(details.split())
        errors.append(compact[-300:])

    raise RuntimeError(
        "No media candidate produced readable audio. "
        + " | ".join(errors[-3:])
    )


def select_rows(
    rows: list[dict[str, str]],
    source_id: str | None,
    limit: int | None,
    force: bool,
    min_relevance: str,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    rank = {"": -1, "low": 0, "medium": 1, "high": 2}
    threshold = rank[min_relevance]

    for row in rows:
        if source_id and row.get("source_id") != source_id:
            continue

        if min_relevance != "all":
            if rank.get(row.get("relevance_label", ""), -1) < threshold:
                continue

        output = AUDIO_DIR / f"{row.get('source_id', '')}.flac"

        if output.exists() and not force:
            continue

        selected.append(row)

        if limit is not None and len(selected) >= limit:
            break

    return selected


async def process_one(
    context: BrowserContext,
    semaphore: asyncio.Semaphore,
    row: dict[str, str],
    wait_ms: int,
) -> dict[str, str]:
    async with semaphore:
        source_id = row.get("source_id", "")
        source_url = row.get("url", "")
        output_path = AUDIO_DIR / f"{source_id}.flac"
        page = await context.new_page()

        try:
            candidates, user_agent = await collect_media_candidates(
                page=page,
                url=source_url,
                wait_ms=wait_ms,
            )

            selected_media = await save_audio_from_candidates(
                context=context,
                candidates=candidates,
                output_path=output_path,
                user_agent=user_agent,
                referer=source_url,
            )

            return {
                "source_id": source_id,
                "status": "success",
                "detail": (
                    f"{output_path.stat().st_size // 1024} KiB; "
                    f"{selected_media.get('content_type') or 'unknown'}"
                ),
            }

        except Exception as exc:
            return {
                "source_id": source_id,
                "status": "failed",
                "detail": f"{type(exc).__name__}: {exc}",
            }

        finally:
            await page.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract TikTok audio concurrently for GPU transcription."
        )
    )
    parser.add_argument("--source-id")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--min-relevance",
        choices=["all", "medium", "high"],
        default="medium",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent TikTok pages + FFmpeg jobs (default: 4).",
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
    parser.add_argument("--wait-ms", type=int, default=3500)
    parser.add_argument("--headless", action="store_true")

    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()

    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "FFmpeg is required but was not found. Run: ffmpeg -version"
        )

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    rows = load_sources()
    selected = select_rows(
        rows=rows,
        source_id=args.source_id,
        limit=args.limit,
        force=args.force,
        min_relevance=args.min_relevance,
    )

    if not selected:
        print("No sources selected.")
        return

    workers = max(1, min(args.workers, len(selected)))
    semaphore = asyncio.Semaphore(workers)

    print("=" * 72)
    print("TikTok -> Parallel Local Audio Dataset")
    print("=" * 72)
    print(f"Selected : {len(selected)}")
    print(f"Workers  : {workers}")
    print(f"Output   : {AUDIO_DIR}")

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
                process_one(
                    context=context,
                    semaphore=semaphore,
                    row=row,
                    wait_ms=args.wait_ms,
                )
            )
            for row in selected
        ]

        for task in asyncio.as_completed(tasks):
            result = await task

            if result["status"] == "success":
                success += 1
            else:
                failed += 1

            print(
                f"{result['source_id']:8} "
                f"{result['status']:8} "
                f"{result['detail']}"
            )

        await context.close()

    print()
    print("=" * 72)
    print("DONE")
    print(f"Success : {success}")
    print(f"Failed  : {failed}")
    print("=" * 72)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
