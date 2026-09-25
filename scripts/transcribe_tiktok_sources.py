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



def build_media_candidates(
    current_src: str,
    captured: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Return unique candidate media streams in audio-first order.

    TikTok may load separate video-only and audio-only streams. The previous
    implementation preferred the video response, which can contain no audio at
    all. This function keeps every useful response and tries likely audio
    streams first.
    """

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

        # Network responses usually carry more reliable content-type metadata
        # than video.currentSrc.
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
            pass

    page.on("response", on_response)

    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(wait_ms)

    # Ask the actual video element to play so TikTok has a chance to request
    # any separate audio stream.
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
            "verification, complete it in Edge, then press ENTER here."
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

    user_agent = str(page.evaluate("() => navigator.userAgent") or "").strip()

    return candidates, user_agent


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



def stream_one_candidate_to_wav(
    media_url: str,
    wav_path: Path,
    user_agent: str,
    referer: str,
    cookie_header: str,
) -> tuple[bool, str]:
    headers = [f"Referer: {referer}"]

    if cookie_header:
        headers.append(f"Cookie: {cookie_header}")

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
            "-map",
            "0:a:0",
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

    ok = (
        result.returncode == 0
        and wav_path.exists()
        and wav_path.stat().st_size > 44
    )

    details = (result.stderr or result.stdout or "").strip()
    return ok, details


def stream_candidates_to_wav(
    context: BrowserContext,
    candidates: list[dict[str, str]],
    wav_path: Path,
    user_agent: str,
    referer: str,
) -> dict[str, str]:
    """Try captured TikTok media responses until one yields an audio stream."""

    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "FFmpeg was not found in PATH. Run: ffmpeg -version"
        )

    errors: list[str] = []

    for index, candidate in enumerate(candidates, start=1):
        media_url = candidate["url"]
        content_type = candidate.get("content_type", "")
        cookie_header = build_cookie_header(context, media_url)

        if wav_path.exists():
            wav_path.unlink()

        print(
            f"    try    : media candidate {index}/{len(candidates)} "
            f"[{content_type or 'unknown'}]"
        )

        ok, details = stream_one_candidate_to_wav(
            media_url=media_url,
            wav_path=wav_path,
            user_agent=user_agent,
            referer=referer,
            cookie_header=cookie_header,
        )

        if ok:
            return candidate

        compact = " ".join(details.split())
        if len(compact) > 300:
            compact = compact[-300:]

        errors.append(
            f"candidate {index} ({content_type or 'unknown'}): {compact}"
        )

    raise RuntimeError(
        "Captured TikTok media streams, but none contained readable audio. "
        + " | ".join(errors[-3:])
    )


def whisper_transcribe(
    audio_path: Path,
    model: Any,
    title: str = "",
) -> dict[str, Any]:
    context_title = " ".join((title or "").split())[:300]
    initial_prompt = RECIPE_VOCAB_PROMPT

    if context_title:
        initial_prompt += f" Tiêu đề/caption của video: {context_title}"

    result = model.transcribe(
        str(audio_path),
        language="vi",
        verbose=False,
        temperature=0,
        beam_size=5,
        initial_prompt=initial_prompt,
        carry_initial_prompt=True,
        condition_on_previous_text=True,
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
        default="small",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model (default: small for better Vietnamese accuracy).",
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
                candidates, user_agent = collect_media_candidates(
                    page=page,
                    url=source_url,
                    wait_ms=args.wait_ms,
                    headless=args.headless,
                )

                print(
                    f"    media  : captured {len(candidates)} "
                    "candidate stream(s)"
                )

                with tempfile.TemporaryDirectory(
                    prefix="vn_food_rag_"
                ) as temp_dir:
                    wav_path = Path(temp_dir) / f"{source_id}.wav"

                    selected_media = stream_candidates_to_wav(
                        context=context,
                        candidates=candidates,
                        wav_path=wav_path,
                        user_agent=user_agent,
                        referer=source_url,
                    )

                    print(
                        f"    audio  : temporary WAV "
                        f"({wav_path.stat().st_size // 1024} KiB)"
                    )
                    print(
                        "    source : "
                        f"{selected_media.get('content_type') or 'unknown'}"
                    )

                    transcript = whisper_transcribe(
                        audio_path=wav_path,
                        model=model,
                        title=row.get("title", ""),
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
