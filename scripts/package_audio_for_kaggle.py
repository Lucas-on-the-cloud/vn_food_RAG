from __future__ import annotations

import argparse
import csv
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "data" / "raw" / "audio"
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
EXPORT_DIR = ROOT / "exports"


def load_sources() -> dict[str, dict[str, str]]:
    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        return {
            row["source_id"]: row
            for row in csv.DictReader(file)
            if row.get("source_id")
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package extracted TikTok audio + metadata for Kaggle."
    )
    parser.add_argument(
        "--name",
        default="vn_food_audio_kaggle.zip",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    files = sorted(AUDIO_DIR.glob("SRC*.flac"))
    if not files:
        raise SystemExit(
            f"No FLAC files found in {AUDIO_DIR}. "
            "Run scripts/extract_tiktok_audio_parallel.py first."
        )

    sources = load_sources()
    manifest = []

    for audio_file in files:
        source_id = audio_file.stem
        source = sources.get(source_id, {})

        manifest.append({
            "source_id": source_id,
            "audio_file": f"audio/{audio_file.name}",
            "url": source.get("url", ""),
            "title": source.get("title", ""),
            "creator": source.get("creator", ""),
            "keyword": source.get("keyword", ""),
            "relevance_label": source.get("relevance_label", ""),
        })

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = EXPORT_DIR / args.name

    with zipfile.ZipFile(
        output_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for audio_file in files:
            archive.write(
                audio_file,
                arcname=f"audio/{audio_file.name}",
            )

        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )

    print("=" * 72)
    print("Kaggle Audio Package")
    print("=" * 72)
    print(f"Audio files : {len(files)}")
    print(f"Output      : {output_path}")
    print(
        f"Size        : "
        f"{output_path.stat().st_size / 1024 / 1024:.2f} MiB"
    )


if __name__ == "__main__":
    main()
