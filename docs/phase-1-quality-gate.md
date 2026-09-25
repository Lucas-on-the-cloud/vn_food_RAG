# Phase 1D — Transcript Quality Gate

Before recipe extraction, automatically remove obviously unusable transcripts.

Typical failures:

- TikTok video cannot be loaded
- no spoken recipe
- music-only audio
- subscription/junk speech
- Whisper hallucination
- extreme phrase/token repetition

## Run

After downloading `transcripts_review.csv` from Kaggle:

```powershell
python scripts/filter_transcripts.py transcripts_review.csv
```

If the CSV is somewhere else, pass the full path.

Outputs:

```text
data/processed/transcript_filter/
  transcripts_quality.csv
  transcripts_accepted.csv
  transcripts_rejected.csv
```

Only `transcripts_accepted.csv` should go into structured recipe extraction.

The filter is intentionally conservative and interpretable. It is not meant to rescue bad audio. At larger scale, losing some samples is acceptable when the source pool contains hundreds of videos.
