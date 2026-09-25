from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from filter_transcripts import classify


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "transcripts" / "saveto_batch_10.csv"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "processed" / "saveto"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Process locally saved Saveto transcripts in parallel. "
            "Missing/bad samples are skipped instead of stopping the batch."
        )
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def read_transcript(path_value: str) -> str:
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path

    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8-sig", errors="replace").strip()


def process_row(row: dict[str, str]) -> dict[str, str | int | float]:
    source_id = row.get("source_id", "")
    text = read_transcript(row.get("transcript_file", ""))

    if not text:
        return {
            **row,
            "text": "",
            "quality_status": "skipped",
            "quality_reason": "missing_transcript",
            "word_count": 0,
            "repeat5_ratio": 0.0,
            "single_token_dominance": 0.0,
            "recipe_term_hits": 0,
        }

    status, reason, metrics = classify(text)

    return {
        **row,
        "text": text,
        "quality_status": status,
        "quality_reason": reason,
        **metrics,
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())

    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    manifest = Path(args.manifest)

    with manifest.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    if args.limit is not None:
        rows = rows[: args.limit]

    workers = max(1, min(args.workers, len(rows) or 1))

    print("=" * 72)
    print("Saveto Transcript Parallel Processor")
    print("=" * 72)
    print(f"Sources : {len(rows)}")
    print(f"Workers : {workers}")

    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(process_row, row): row.get("source_id", "")
            for row in rows
        }

        for future in as_completed(future_map):
            source_id = future_map[future]

            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "source_id": source_id,
                    "quality_status": "skipped",
                    "quality_reason": f"processing_error:{type(exc).__name__}",
                    "text": "",
                }

            results.append(result)
            print(
                f"{source_id:8} "
                f"{result.get('quality_status', ''):8} "
                f"{result.get('quality_reason', '')}"
            )

    # Restore manifest order after parallel execution.
    order = {
        row.get("source_id", ""): index
        for index, row in enumerate(rows)
    }
    results.sort(key=lambda row: order.get(row.get("source_id", ""), 999999))

    accepted = [
        row for row in results
        if row.get("quality_status") == "accepted"
    ]
    rejected = [
        row for row in results
        if row.get("quality_status") in {"rejected", "review"}
    ]

    output_dir = Path(args.output_dir)
    write_csv(output_dir / "transcripts_review.csv", results)
    write_csv(output_dir / "transcripts_accepted.csv", accepted)
    write_csv(output_dir / "transcripts_rejected.csv", rejected)

    skipped = sum(
        row.get("quality_status") == "skipped"
        for row in results
    )

    print()
    print("=" * 72)
    print("DONE")
    print(f"Accepted : {len(accepted)}")
    print(f"Rejected/review : {len(rejected)}")
    print(f"Skipped  : {skipped}")
    print(f"Output   : {output_dir}")


if __name__ == "__main__":
    main()
