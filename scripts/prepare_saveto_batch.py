from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
DEFAULT_OUTPUT = ROOT / "data" / "transcripts" / "saveto_batch_10.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a Saveto transcript manifest from discovered TikTok sources."
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--min-relevance",
        choices=["all", "medium", "high"],
        default="all",
    )
    return parser.parse_args()


def allowed(row: dict[str, str], threshold: str) -> bool:
    if threshold == "all":
        return True

    score = {"low": 0, "medium": 1, "high": 2}
    return score.get(row.get("relevance_label", ""), 0) >= score[threshold]


def main() -> None:
    args = parse_args()

    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        rows = [
            row
            for row in csv.DictReader(file)
            if allowed(row, args.min_relevance)
        ]

    rows = rows[: args.limit]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "source_id",
        "url",
        "title",
        "creator",
        "relevance_label",
        "transcript_provider",
        "transcript_file",
        "status",
    ]

    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            source_id = row["source_id"]
            writer.writerow(
                {
                    "source_id": source_id,
                    "url": row.get("url", ""),
                    "title": row.get("title", ""),
                    "creator": row.get("creator", ""),
                    "relevance_label": row.get("relevance_label", ""),
                    "transcript_provider": "saveto",
                    "transcript_file": f"data/transcripts/raw/{source_id}.txt",
                    "status": "pending_transcript",
                }
            )

    print("=" * 72)
    print("Saveto Batch Prepared")
    print("=" * 72)
    print(f"Rows   : {len(rows)}")
    print(f"Output : {output}")
    print()
    print("Use Saveto for each URL, then save/copy the transcript as:")
    print("data/transcripts/raw/SRCxxxx.txt")


if __name__ == "__main__":
    main()
