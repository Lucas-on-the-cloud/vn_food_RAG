from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
TRANSCRIPT_DIR = ROOT / "data" / "processed" / "transcripts"
DEFAULT_PROFILE_DIR = ROOT / ".browser" / "tiktok-profile"

VIDEO_ID_RE = re.compile(r"/video/(\d+)")


def load_sources() -> list[dict[str, str]]:
    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def extract_video_id(url: str) -> str:
    match = VIDEO_ID_RE.search(url)
    return match.group(1) if match else ""


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
    value = (url or "").lower()
    return value.startswith(("http://", "https://"))


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


def choose_media_url(
    current_src: str,
    captured: list[dict[str, str]],
) -> str | None:
    """Prefer the exact media source used by the <video> element.

    If TikTok exposes only a blob: URL, fall back to HTTP media responses
    captured while the browser loaded the page.
    """

    if is_http_media_url(current_src):
        return current_src

    usable = [
        item
        for item in captured
        if is_http_media_url(item.get("url", ""))
        and looks_like_media(
            item.get("url", ""),
            item.get("content_type", ""),
        )
    ]

    if not usable:
        return None

    # Prefer video responses because they contain the exact mixed audio heard
    # in the TikTok video. Separate audio requests may represent only a music
    # track rather than the creator's full spoken audio.
    video_candidates = [
        item
        for item in usable
        if item.get("content_type", "").lower().startswith("video/")
        or "mime_type=video" in item.get("url", "").lower()
    ]

    selected = video_candidates[-1] if video_candidates else usable[-1]
    return selected["url"]


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


def collect_media_url(
    page: Page,
    url: str,
    wait_ms: int,
    headless: bool,
) -> tuple[str, str]:
    captured: list[dict[str, str]] = []

    def on_response(response: Any) -> None:
        try:
            response_url = str(response.url)
            headers = response.headers
            content_type = str(headers.get("content-type", "") or "")

            if looks_like_media(response_url, content_type):
                captured.append(
                    {
                        "url": response_url,
                        "content_type": content_type,
                    }
                )
        except Exception:
            # Network-event parsing should never crash the transcription run.
            pass

    page.on("response", on_response)

    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(wait_ms)

    current_src = get_current_video_src(page)
    media_url = choose_media_url(current_src, captured)

    if media_url is None and not headless:
        print(
            "    No media URL found yet. If TikTok shows login/CAPTCHA/"
            "verification, complete it in Edge, then press ENTER here."
        )
        try:
            input()
        except EOFError:
            pass

        page.wait_for_timeout(2_000)

        # Encourage the media element to actually load/play.
        video = page.locator("video")
        if video.count() > 0:
            try:
                video.first.evaluate(
                    """async (v) => {
                        v.muted = true;
                        try { await v.play(); } catch (_) {}
                    }"""
                )
            except Exception:
                pass

        page.wait_for_timeout(2_000)
        current_src = get_current_video_src(page)
        media_url = choose_media_url(current_src, captured)

    if media_url is None:
        raise RuntimeError(
            "TikTok page opened, but no HTTP media stream could be captured."
        )

    user_agent = str(
        page.evaluate("() => navigator.userAgent") or ""
    ).strip()

    return media_url, user_agent


def build_cookie_header(
    context: BrowserContext,
    media_url: str,
) -> str:
    try:
        cookies = context.cookies([media_url])
    except Exception:
        cookies = []

    pairs = [
        f"{cookie.get('name')}={cookie.get('value')}"
        for cookie in cookies
        if cookie.get("name")
    ]

    return "; ".join(pairs)


def stream_media_to_wav(
    media_url: str,
    wav_path: Path,
    user_agent: str,
    referer: str,
    cookie_header: str,
) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "FFmpeg was not found in PATH. Run: ffmpeg -version"
        )

    headers = [f"Referer: {referer}"]

    if cookie_header:
        headers.append(f"Cookie: {cookie_header}")

    # FFmpeg expects CRLF-separated HTTP headers.
    header_value = "\r\n".join(headers) + "\r\n"

    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
    ]

    if user_agent:
        command.extend(["-user_agent", user_agent])

    command.extend(
        [
            "-headers",
            header_value,
            "-i",
            media_url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav_path),
        ]
    )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            "FFmpeg could not read the TikTok media stream. "
            f"Details: {details[-1000:]}"
        )

    if not wav_path.exists() or wav_path.stat().st_size == 0:
        raise RuntimeError("FFmpeg completed but produced no audio WAV file.")


def whisper_transcribe(
    audio_path: Path,
    model: Any,
) -> dict[str, Any]:
    result = model.transcribe(
        str(audio_path),
        language="vi",
        verbose=False,
    )

    segments = [
        {
            "start": segment.get("start"),
            "end": segment.get("end"),
            "text": str(segment.get("text", "")).strip(),
        }
        for segment in result.get("segments", [])
        if str(segment.get("text", "")).strip()
    ]

    return {
        "method": "browser_stream_whisper",
        "language": str(result.get("language", "vi")),
        "text": str(result.get("text", "")).strip(),
        "segments": segments,
    }


def save_transcript(result: dict[str, Any]) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    output = TRANSCRIPT_DIR / f"{result['source_id']}.json"

    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return output


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

        output = TRANSCRIPT_DIR / f"{row.get('source_id', '')}.json"

        if output.exists() and not force:
            print(f"[SKIP] {row.get('source_id')} transcript already exists")
            continue

        selected.append(row)

        if limit is not None and len(selected) >= limit:
            break

    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Open each TikTok URL in the existing browser session, capture the "
            "media stream, extract temporary audio with FFmpeg, and transcribe "
            "Vietnamese speech with Whisper. No full video is saved."
        )
    )
    parser.add_argument(
        "--source-id",
        help="Process one source, e.g. SRC0001.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N rows.",
    )
    parser.add_argument(
        "--whisper-model",
        default="base",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model (default: base).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing transcript JSON.",
    )
    parser.add_argument(
        "--browser",
        choices=["edge", "chrome", "chromium"],
        default="edge",
        help="Browser controlled by Playwright (default: edge).",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help="Persistent browser profile used by discovery/metadata steps.",
    )
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=4500,
        help="Wait after opening each TikTok page (default: 4500ms).",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser invisibly. Visible mode is recommended first.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Pause between sources (default: 1 second).",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_sources()

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    selected = select_rows(
        rows=rows,
        source_id=args.source_id,
        limit=args.limit,
        force=args.force,
    )

    if not selected:
        print("No sources selected.")
        return

    if shutil.which("ffmpeg") is None:
        raise SystemExit(
            "FFmpeg is required but was not found. Run 'ffmpeg -version'."
        )

    print("=" * 72)
    print("TikTok URL -> Transcript (Browser Stream)")
    print("=" * 72)
    print(f"Selected       : {len(selected)}")
    print(f"Browser        : {args.browser}")
    print(f"Headless       : {args.headless}")
    print(f"Whisper model  : {args.whisper_model}")
    print(f"Output folder  : {TRANSCRIPT_DIR}")

    # Import/load Whisper only after basic environment validation.
    import whisper

    print("\n[MODEL] Loading Whisper...")
    model = whisper.load_model(args.whisper_model)

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

            print(f"\n[{index}/{len(selected)}] {source_id}")
            print(f"    {source_url}")

            try:
                media_url, user_agent = collect_media_url(
                    page=page,
                    url=source_url,
                    wait_ms=args.wait_ms,
                    headless=args.headless,
                )

                print("    media  : captured from browser")

                cookie_header = build_cookie_header(context, media_url)

                with tempfile.TemporaryDirectory(
                    prefix="vn_food_rag_"
                ) as temp_dir:
                    wav_path = Path(temp_dir) / f"{source_id}.wav"

                    stream_media_to_wav(
                        media_url=media_url,
                        wav_path=wav_path,
                        user_agent=user_agent,
                        referer=source_url,
                        cookie_header=cookie_header,
                    )

                    print(
                        f"    audio  : temporary WAV "
                        f"({wav_path.stat().st_size // 1024} KiB)"
                    )

                    transcript = whisper_transcribe(
                        audio_path=wav_path,
                        model=model,
                    )

                result = {
                    "source_id": source_id,
                    "url": source_url,
                    "video_id": extract_video_id(source_url),
                    "title": row.get("title", ""),
                    **transcript,
                }

                output = save_transcript(result)

                success += 1
                print(f"    chars  : {len(result['text'])}")
                print(f"    saved  : {output}")

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
