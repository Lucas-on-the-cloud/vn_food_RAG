from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

import yt_dlp


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
TRANSCRIPT_DIR = ROOT / "data" / "processed" / "transcripts"


TIMECODE_RE = re.compile(
    r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}\s+-->\s+"
    r"(?:\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}"
)
TAG_RE = re.compile(r"<[^>]+>")


def load_sources() -> list[dict[str, str]]:
    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def clean_subtitle_text(raw: str) -> str:
    """Convert SRT/VTT-like subtitle text into plain text."""

    lines: list[str] = []
    seen: set[str] = set()

    for line in raw.splitlines():
        value = line.strip()

        if not value:
            continue

        if value.upper() == "WEBVTT":
            continue

        if value.isdigit():
            continue

        if TIMECODE_RE.match(value):
            continue

        if value.startswith(("NOTE", "STYLE", "REGION")):
            continue

        value = TAG_RE.sub("", value).strip()

        if not value or value in seen:
            continue

        seen.add(value)
        lines.append(value)

    return " ".join(lines).strip()


def parse_json_subtitle(raw: str) -> tuple[str, list[dict[str, Any]]]:
    """Parse common TikTok/creator-caption JSON structures."""

    payload = json.loads(raw)

    utterances: list[dict[str, Any]] = []

    if isinstance(payload, dict):
        candidates = payload.get("utterances")
        if isinstance(candidates, list):
            utterances = candidates

        if not utterances:
            captions = payload.get("captions")
            if isinstance(captions, list):
                utterances = captions

    segments: list[dict[str, Any]] = []
    texts: list[str] = []

    for item in utterances:
        if not isinstance(item, dict):
            continue

        text = str(item.get("text", "") or "").strip()
        if not text:
            continue

        start = item.get("start_time", item.get("start", None))
        end = item.get("end_time", item.get("end", None))

        # TikTok caption JSON commonly stores milliseconds.
        if isinstance(start, (int, float)) and start > 1000:
            start = start / 1000
        if isinstance(end, (int, float)) and end > 1000:
            end = end / 1000

        segments.append(
            {
                "start": start,
                "end": end,
                "text": text,
            }
        )
        texts.append(text)

    return " ".join(texts).strip(), segments


def language_rank(language: str) -> int:
    value = language.lower()

    if value in {"vi", "vi-vn", "vie", "vietnamese"}:
        return 100
    if value.startswith("vi"):
        return 90
    if "vietnam" in value:
        return 80
    if value.startswith("en"):
        return 20
    return 0


def choose_subtitle_track(info: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    subtitle_groups = []

    for field in ("subtitles", "automatic_captions"):
        group = info.get(field)
        if isinstance(group, dict):
            subtitle_groups.append(group)

    candidates: list[tuple[int, str, dict[str, Any]]] = []

    for group in subtitle_groups:
        for language, tracks in group.items():
            if not isinstance(tracks, list):
                continue

            for track in tracks:
                if not isinstance(track, dict):
                    continue

                ext = str(track.get("ext", "") or "").lower()
                format_bonus = {
                    "vtt": 3,
                    "srt": 3,
                    "json": 2,
                }.get(ext, 0)

                candidates.append(
                    (
                        language_rank(str(language)) + format_bonus,
                        str(language),
                        track,
                    )
                )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, language, track = candidates[0]

    # Do not silently use unrelated-language subtitles.
    if language_rank(language) <= 0:
        return None

    return language, track


def fetch_subtitle_payload(
    track: dict[str, Any],
    info: dict[str, Any],
) -> str:
    if track.get("data"):
        return str(track["data"])

    url = track.get("url")
    if not url:
        raise RuntimeError("Selected subtitle track has neither data nor URL.")

    headers: dict[str, str] = {}
    for source in (info.get("http_headers"), track.get("http_headers")):
        if isinstance(source, dict):
            headers.update(
                {
                    str(key): str(value)
                    for key, value in source.items()
                    if value is not None
                }
            )

    request = Request(str(url), headers=headers)

    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_subtitle_transcript(
    info: dict[str, Any],
) -> dict[str, Any] | None:
    selected = choose_subtitle_track(info)
    if selected is None:
        return None

    language, track = selected
    raw = fetch_subtitle_payload(track, info)
    ext = str(track.get("ext", "") or "").lower()

    if ext == "json":
        text, segments = parse_json_subtitle(raw)
    else:
        text = clean_subtitle_text(raw)
        segments = []

    if not text:
        return None

    return {
        "method": "subtitle",
        "language": language,
        "text": text,
        "segments": segments,
    }


def build_ydl_options(quiet: bool = True) -> dict[str, Any]:
    return {
        "quiet": quiet,
        "no_warnings": quiet,
        "noplaylist": True,
        "skip_download": True,
    }


def extract_info(url: str) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(build_ydl_options()) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp returned no metadata.")

    return info


def download_audio_only(url: str, temp_dir: Path) -> Path:
    output_template = str(temp_dir / "%(id)s.%(ext)s")

    options: dict[str, Any] = {
        "quiet": False,
        "noplaylist": True,
        "format": "bestaudio",
        "outtmpl": output_template,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

        if not isinstance(info, dict):
            raise RuntimeError("Unable to download audio-only media.")

        requested = info.get("requested_downloads")
        candidate_paths: list[Path] = []

        if isinstance(requested, list):
            for item in requested:
                if isinstance(item, dict):
                    filepath = item.get("filepath")
                    if filepath:
                        candidate_paths.append(Path(str(filepath)))

        filename = ydl.prepare_filename(info)
        if filename:
            candidate_paths.append(Path(filename))

    for path in candidate_paths:
        if path.exists():
            return path

    files = [path for path in temp_dir.iterdir() if path.is_file()]
    if files:
        return files[0]

    raise RuntimeError("Audio download finished but no local audio file was found.")


def whisper_transcribe(audio_path: Path, model_name: str) -> dict[str, Any]:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "FFmpeg is required for Whisper audio decoding but was not found in PATH."
        )

    import whisper

    model = whisper.load_model(model_name)
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
        "method": "whisper",
        "language": str(result.get("language", "vi")),
        "text": str(result.get("text", "")).strip(),
        "segments": segments,
    }


def transcribe_source(
    row: dict[str, str],
    whisper_model: str,
    subtitle_only: bool,
) -> dict[str, Any]:
    url = row["url"]
    info = extract_info(url)

    subtitle_result = extract_subtitle_transcript(info)
    if subtitle_result is not None:
        return {
            "source_id": row["source_id"],
            "url": url,
            "video_id": str(info.get("id", "") or ""),
            "title": str(info.get("description") or info.get("title") or ""),
            **subtitle_result,
        }

    if subtitle_only:
        raise RuntimeError("No usable Vietnamese subtitle was found.")

    with tempfile.TemporaryDirectory(prefix="vn_food_rag_") as temp:
        audio_path = download_audio_only(url, Path(temp))
        whisper_result = whisper_transcribe(audio_path, whisper_model)

    return {
        "source_id": row["source_id"],
        "url": url,
        "video_id": str(info.get("id", "") or ""),
        "title": str(info.get("description") or info.get("title") or ""),
        **whisper_result,
    }


def save_transcript(result: dict[str, Any]) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    output = TRANSCRIPT_DIR / f"{result['source_id']}.json"

    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert TikTok source URLs into text. Prefer existing subtitles; "
            "otherwise download only temporary audio and transcribe with Whisper."
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
        help="Whisper model used only when subtitle fallback is needed.",
    )
    parser.add_argument(
        "--subtitle-only",
        action="store_true",
        help="Do not download audio; fail if usable subtitles are unavailable.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing transcript JSON.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_sources()

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    selected: list[dict[str, str]] = []

    for row in rows:
        if args.source_id and row.get("source_id") != args.source_id:
            continue

        output = TRANSCRIPT_DIR / f"{row.get('source_id', '')}.json"
        if output.exists() and not args.force:
            print(f"[SKIP] {row.get('source_id')} transcript already exists")
            continue

        selected.append(row)

        if args.limit is not None and len(selected) >= args.limit:
            break

    if not selected:
        print("No sources selected.")
        return

    print("=" * 72)
    print("TikTok URL -> Transcript")
    print("=" * 72)
    print(f"Selected       : {len(selected)}")
    print(f"Subtitle only  : {args.subtitle_only}")
    print(f"Whisper model  : {args.whisper_model}")
    print(f"Output folder  : {TRANSCRIPT_DIR}")

    success = 0
    failed = 0

    for index, row in enumerate(selected, start=1):
        source_id = row.get("source_id", "")
        print(f"\n[{index}/{len(selected)}] {source_id}")
        print(f"    {row.get('url', '')}")

        try:
            result = transcribe_source(
                row=row,
                whisper_model=args.whisper_model,
                subtitle_only=args.subtitle_only,
            )
            output = save_transcript(result)

            success += 1
            print(f"    method : {result['method']}")
            print(f"    chars  : {len(result['text'])}")
            print(f"    saved  : {output}")

        except Exception as exc:
            failed += 1
            print(f"    ERROR {type(exc).__name__}: {exc}")

    print("\n" + "=" * 72)
    print("DONE")
    print(f"Success : {success}")
    print(f"Failed  : {failed}")
    print("=" * 72)


if __name__ == "__main__":
    main()
