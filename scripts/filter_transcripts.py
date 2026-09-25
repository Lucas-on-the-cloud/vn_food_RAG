from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path


DEFAULT_MIN_WORDS = 80
DEFAULT_MAX_REPEAT5 = 0.55

RECIPE_TERMS = {
    "nau", "mon", "com", "canh", "xao", "chien", "kho", "rim", "luoc",
    "hap", "nuong", "thit", "trung", "dau hu", "nam", "rau", "hanh",
    "toi", "nuoc mam", "nuoc tuong", "dau hao", "bot nang", "bot bap",
    "ap chao", "gia vi", "nguyen lieu",
}

JUNK_TERMS = {
    "subscribe", "dang ky kenh", "khong bo lo", "official audio",
}


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFD", text or "")
    value = "".join(
        ch for ch in value
        if unicodedata.category(ch) != "Mn"
    )
    return value.replace("đ", "d").replace("Đ", "D").lower()


def repeat_ratio(text: str, n: int = 5) -> float:
    words = (text or "").split()
    if len(words) < n:
        return 0.0

    shingles = [
        " ".join(words[i:i+n])
        for i in range(len(words) - n + 1)
    ]
    return 1.0 - (len(set(shingles)) / len(shingles))


def single_token_dominance(text: str) -> float:
    words = re.findall(r"\w+", normalize(text))
    if not words:
        return 1.0

    counts: dict[str, int] = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1

    return max(counts.values()) / len(words)


def recipe_term_hits(text: str) -> int:
    value = normalize(text)
    return sum(term in value for term in RECIPE_TERMS)


def classify(text: str) -> tuple[str, str, dict[str, float | int]]:
    words = (text or "").split()
    word_count = len(words)
    rep5 = repeat_ratio(text, 5)
    dominance = single_token_dominance(text)
    hits = recipe_term_hits(text)
    normalized = normalize(text)

    metrics = {
        "word_count": word_count,
        "repeat5_ratio": round(rep5, 3),
        "single_token_dominance": round(dominance, 3),
        "recipe_term_hits": hits,
    }

    if word_count < 20:
        return "rejected", "too_short", metrics

    if rep5 >= 0.80:
        return "rejected", "severe_repetition", metrics

    if dominance >= 0.30:
        return "rejected", "token_hallucination", metrics

    if any(term in normalized for term in JUNK_TERMS) and hits < 2:
        return "rejected", "junk_or_subscription", metrics

    if word_count < DEFAULT_MIN_WORDS and hits < 3:
        return "rejected", "low_recipe_signal", metrics

    if rep5 >= DEFAULT_MAX_REPEAT5:
        return "review", "high_repetition", metrics

    if hits < 2:
        return "review", "weak_recipe_signal", metrics

    return "accepted", "recipe_candidate", metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter noisy Whisper transcripts before recipe extraction."
    )
    parser.add_argument(
        "input_csv",
        help="Path to transcripts_review.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="data/processed/transcript_filter",
        help="Where accepted/rejected CSV files are written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input_csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    enriched = []

    for row in rows:
        status, reason, metrics = classify(row.get("text", ""))

        enriched.append(
            {
                **row,
                "quality_status": status,
                "quality_reason": reason,
                **metrics,
            }
        )

    if not enriched:
        raise SystemExit("No transcript rows found.")

    fieldnames = list(enriched[0].keys())

    all_path = output_dir / "transcripts_quality.csv"
    accepted_path = output_dir / "transcripts_accepted.csv"
    rejected_path = output_dir / "transcripts_rejected.csv"

    def write(path: Path, items: list[dict]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(items)

    write(all_path, enriched)
    write(
        accepted_path,
        [row for row in enriched if row["quality_status"] == "accepted"],
    )
    write(
        rejected_path,
        [row for row in enriched if row["quality_status"] != "accepted"],
    )

    counts: dict[str, int] = {}
    for row in enriched:
        counts[row["quality_status"]] = counts.get(row["quality_status"], 0) + 1

    print("=" * 72)
    print("Transcript Quality Gate")
    print("=" * 72)
    print(f"Total    : {len(enriched)}")
    print(f"Accepted : {counts.get('accepted', 0)}")
    print(f"Review   : {counts.get('review', 0)}")
    print(f"Rejected : {counts.get('rejected', 0)}")
    print()

    for row in enriched:
        print(
            f"{row.get('source_id',''):8} "
            f"{row['quality_status']:8} "
            f"{row['quality_reason']:22} "
            f"words={row['word_count']:4} "
            f"repeat={row['repeat5_ratio']}"
        )

    print()
    print(f"Accepted CSV: {accepted_path}")
    print(f"Rejected CSV: {rejected_path}")


if __name__ == "__main__":
    main()
