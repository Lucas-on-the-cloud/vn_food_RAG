from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
AUDIO_DIR = ROOT / "data" / "raw" / "audio"
DEFAULT_PROFILE_DIR = ROOT / ".browser" / "tiktok-profile"

VIDEO_ID_RE = re.compile(r"/video/(\d+)")


def load_sources() -> list[dict[str, str]]:
    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def launch_context(
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
        candidates.append(
            {
                "url": current_src,
                "content_type": "",
                "source": "video.currentSrc",
            }
        )

    for item in captured:
        media_url = item.get("url", "")
        content_type = item.get("content_type", "")

        if not is_http_media_url(media_url):
            continue

        if not looks_like_media(media_url, content_type):
            continue

        candidates.append(
            {
                "url": media_url,
                "content_type": content_type,
                "source": "network",
            }
        )

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


def get_current_video_src(page: Page) -> str:
    locator = page.locator("video")
    if locator.count() == 0:
        return ""

    try:
        return str(
            locator.first.evaluate(
                "(video) => video.currentSrc || video.src || ''"
            )
            or ""
        )
    except Exception:
        return ""


def collect_media_candidates(
    page: Page,
    url: str,
    wait_ms: int,
    headless: bool,
) -> tuple[list[dict[str, str]], str]:
    captured: list[dict[str, str]] = []

    def on_response(response: Any) -> None:
        try:
            response_url = str(response.url)
            content_type = str(
                response.headers.get("content-type", "") or ""
            )

            if looks_like_media(response_url, content_type):
                captured.append(
                    {
                        "url": response_url,
                        "content_type": content_type,
                    }
                )
        except Exception:
            pass

    page.on("response", on_response)

    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(wait_ms)

    video = page.locator("video")
    if video.count() > 0:
        try:
            video.first.evaluate(
                """async (v) => {
                    try {
                        v.muted = false;
                        v.volume = 0.01;
                        await v.play();
                    } catch (_) {
                        try {
                            v.muted = true;
                            await v.play();
                        } catch (_) {}
                    }
                }"""
            )
        except Exception:
            pass

    page.wait_for_timeout(2_000)

    current_src = get_current_video_src(page)
    candidates = build_media_candidates(current_src, captured)

    if not candidates and not headless:
        print(
            "    No media stream found yet. If TikTok shows login/CAPTCHA/"
            "verification, complete it in Edge, then press ENTER."
        )
        try:
            input()
        except EOFError:
            pass

        page.wait_for_timeout(2_000)
        current_src = get_current_video_src(page)
        candidates = build_media_candidates(current_src, captured)

    if not candidates:
        raise RuntimeError(
            "TikTok page opened, but no HTTP media streams could be captured."
        )

    user_agent = str(
        page.evaluate("() => navigator.userAgent") or ""
    ).strip()

    return candidates, user_agent


def build_cookie_header(
    context: BrowserContext,
    media_url: str,
) -> str:
    try:
        cookies = context.cookies([media_url])
    except Exception:
        cookies = []

    return "; ".join(
        f"{cookie.get('name')}={cookie.get('value')}"
        for cookie in cookies
        if cookie.get("name")
    )


def extract_candidate_audio(
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

    command.extend(
        [
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
        ]
    )

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


def save_audio_from_candidates(
    context: BrowserContext,
    candidates: list[dict[str, str]],
    output_path: Path,
    user_agent: str,
    referer: str,
) -> dict[str, str]:
    errors: list[str] = []

    for index, candidate in enumerate(candidates, start=1):
        media_url = candidate["url"]
        content_type = candidate.get("content_type", "")
        cookie_header = build_cookie_header(context, media_url)

        if output_path.exists():
            output_path.unlink()

        print(
            f"    try    : candidate {index}/{len(candidates)} "
            f"[{content_type or 'unknown'}]"
        )

        ok, details = extract_candidate_audio(
            media_url=media_url,
            output_path=output_path,
            user_agent=user_agent,
            referer=referer,
            cookie_header=cookie_header,
        )

        if ok:
            return candidate

        compact = " ".join(details.split())
        if len(compact) > 300:
            compact = compact[-300:]
        errors.append(compact)

    raise RuntimeError(
        "No captured media candidate produced readable audio. "
        + " | ".join(errors[-3:])
    )


def select_rows(
    rows: list[dict[str, str]],
    source_id: str | None,
    limit: int | None,
    force: bool,
) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []

    for row in rows:
        if source_id and row.get("source_id") != source_id:
            continue

        output = AUDIO_DIR / f"{row.get('source_id', '')}.flac"

        if output.exists() and not force:
            print(f"[SKIP] {row.get('source_id')} audio already exists")
            continue

        selected.append(row)

        if limit is not None and len(selected) >= limit:
            break

    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open TikTok URLs in the persistent Edge/Chrome session and save "
            "audio-only FLAC files for later GPU transcription on Kaggle."
        )
    )
    parser.add_argument("--source-id", help="One source, e.g. SRC0001")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome", "chromium"],
        default="edge",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
    )
    parser.add_argument("--wait-ms", type=int, default=4500)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--sleep", type=float, default=1.0)

    return parser.parse_args()


def main() -> None:
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
    )

    if not selected:
        print("No sources selected.")
        return

    print("=" * 72)
    print("TikTok URL -> Local Audio Dataset")
    print("=" * 72)
    print(f"Selected      : {len(selected)}")
    print(f"Browser       : {args.browser}")
    print(f"Output folder : {AUDIO_DIR}")

    success = 0
    failed = 0

    with sync_playwright() as playwright:
        context = launch_context(
            playwright=playwright,
            browser_name=args.browser,
            profile_dir=Path(args.profile_dir),
            headless=args.headless,
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(15_000)

        for index, row in enumerate(selected, start=1):
            source_id = row.get("source_id", "")
            source_url = row.get("url", "")
            output_path = AUDIO_DIR / f"{source_id}.flac"

            print(f"\n[{index}/{len(selected)}] {source_id}")
            print(f"    {source_url}")

            try:
                candidates, user_agent = collect_media_candidates(
                    page=page,
                    url=source_url,
                    wait_ms=args.wait_ms,
                    headless=args.headless,
                )

                print(
                    f"    media  : captured {len(candidates)} candidate(s)"
                )

                selected_media = save_audio_from_candidates(
                    context=context,
                    candidates=candidates,
                    output_path=output_path,
                    user_agent=user_agent,
                    referer=source_url,
                )

                success += 1
                print(
                    f"    saved  : {output_path} "
                    f"({output_path.stat().st_size // 1024} KiB)"
                )
                print(
                    "    source : "
                    f"{selected_media.get('content_type') or 'unknown'}"
                )

            except Exception as exc:
                failed += 1
                print(f"    ERROR {type(exc).__name__}: {exc}")

            if args.sleep > 0:
                time.sleep(args.sleep)

        context.close()

    print("\n" + "=" * 72)
    print("DONE")
    print(f"Success : {success}")
    print(f"Failed  : {failed}")
    print("=" * 72)


if __name__ == "__main__":
    main()
