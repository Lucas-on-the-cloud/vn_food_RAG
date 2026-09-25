from __future__ import annotations

import argparse
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "data" / "sources" / "video_sources.csv"
DEFAULT_OUTPUT = ROOT / "data" / "transcripts" / "saveto_batch.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a scalable Saveto transcript manifest from discovered "
            "TikTok recipe sources."
        )
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--min-relevance",
        choices=["all", "medium", "high"],
        default="medium",
        help="Default keeps high + medium recipe candidates.",
    )
    parser.add_argument(
        "--include-metadata-errors",
        action="store_true",
        help="Also include rows whose TikTok metadata enrichment failed.",
    )
    return parser.parse_args()


def allowed(row: dict[str, str], threshold: str) -> bool:
    if threshold == "all":
        return True

    score = {"": -1, "low": 0, "medium": 1, "high": 2}
    return score.get(row.get("relevance_label", ""), -1) >= score[threshold]


def relevance_rank(row: dict[str, str]) -> tuple[int, str]:
    score = {"high": 0, "medium": 1, "low": 2, "": 3}
    return (
        score.get(row.get("relevance_label", ""), 3),
        row.get("source_id", ""),
    )


def main() -> None:
    args = parse_args()

    with SOURCES_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        source_rows = list(csv.DictReader(file))

    rows: list[dict[str, str]] = []

    for row in source_rows:
        status = row.get("status", "")

        if (
            not args.include_metadata_errors
            and status == "metadata_error"
        ):
            continue

        if not allowed(row, args.min_relevance):
            continue

        rows.append(row)

    rows.sort(key=relevance_rank)
    rows = rows[: args.limit]

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "source_id",
        "url",
        "title",
        "creator",
        "relevance_score",
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
            transcript_path = (
                ROOT / "data" / "transcripts" / "raw" / f"{source_id}.txt"
            )

            writer.writerow(
                {
                    "source_id": source_id,
                    "url": row.get("url", ""),
                    "title": row.get("title", ""),
                    "creator": row.get("creator", ""),
                    "relevance_score": row.get("relevance_score", ""),
                    "relevance_label": row.get("relevance_label", ""),
                    "transcript_provider": "saveto_playwright",
                    "transcript_file": (
                        f"data/transcripts/raw/{source_id}.txt"
                    ),
                    "status": (
                        "transcript_exists"
                        if transcript_path.exists()
                        else "pending_transcript"
                    ),
                }
            )

    high = sum(row.get("relevance_label") == "high" for row in rows)
    medium = sum(row.get("relevance_label") == "medium" for row in rows)

    print("=" * 72)
    print("Saveto Batch Prepared")
    print("=" * 72)
    print(f"Rows       : {len(rows)}")
    print(f"High       : {high}")
    print(f"Medium     : {medium}")
    print(f"Output     : {output}")
    print()
    print("Next:")
    print(
        "python scripts/crawl_saveto_playwright.py "
        f"--manifest {output} --workers 3"
    )


if __name__ == "__main__":
    main()
