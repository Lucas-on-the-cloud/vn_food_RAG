# Phase 1 — Saveto Transcript Workflow

## Decision

Saveto is the primary transcript provider for the recipe-data pipeline.

Saveto currently advertises a free TikTok transcript generator with no sign-up requirement.

This repository **does not automate or scrape Saveto**. The provider's terms prohibit bots/scripts/scrapers without prior written consent.

Automation begins only after transcript text is saved locally.

## First 10 Videos

The repository contains:

`data/transcripts/saveto_batch_10.csv`

For every row:

1. Copy the TikTok URL.
2. Generate the transcript in Saveto.
3. Copy/download the transcript.
4. Save it as:

`data/transcripts/raw/<source_id>.txt`

Example:

```text
data/transcripts/raw/
  SRC0001.txt
  SRC0002.txt
  ...
  SRC0010.txt
```

A missing transcript is fine. Do not spend time fixing isolated failures.

## Parallel Post-processing

Run:

```powershell
python scripts/process_saveto_batch.py --workers 10
```

Each available transcript is quality-checked independently in a thread pool.

Outputs:

```text
data/processed/saveto/
  transcripts_review.csv
  transcripts_accepted.csv
  transcripts_rejected.csv
```

Missing transcript files get:

`quality_status = skipped`

and the rest of the batch continues.

## Scale Up

Create a larger manifest:

```powershell
python scripts/prepare_saveto_batch.py --limit 100 --output data/transcripts/saveto_batch_100.csv
```

Then:

```powershell
python scripts/process_saveto_batch.py \
  --manifest data/transcripts/saveto_batch_100.csv \
  --workers 16
```

The worker count controls local post-processing only; it does not make automated requests to Saveto.

## Next Stage

Only:

`transcripts_accepted.csv`

should enter structured recipe extraction.
