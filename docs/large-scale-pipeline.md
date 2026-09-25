# Large-Scale Recipe Data Pipeline

This is the production workflow after the initial 10-video smoke test.

## Goal

Collect roughly 100–200+ usable Vietnamese cooking-video transcripts.

Because some videos are unavailable, music-only, non-recipe, or poorly transcribed, discovery should intentionally oversample.

A practical starting point is:

```text
200–250 discovered TikTok videos
            ↓
metadata + relevance filtering
            ↓
Saveto transcription
            ↓
quality gate
            ↓
~100+ usable recipe transcripts
```

The exact yield depends on the source mix.

## Stage 1 — Discover TikTok URLs

Start with high-priority cooking keywords:

```powershell
python scripts/crawl_tiktok_search.py --from-seed --priority high --target-new 200 --limit 30
```

The crawler:

- searches TikTok keyword pages,
- auto-scrolls,
- collects video URLs,
- canonicalizes URLs,
- removes duplicates,
- appends only new sources,
- preserves the full metadata CSV schema,
- stops when the requested number of new URLs is reached.

If high-priority keywords do not produce enough unique URLs, continue with all priorities:

```powershell
python scripts/crawl_tiktok_search.py --from-seed --priority all --target-new 100 --limit 30
```

Because the CSV deduplicates URLs, repeating a crawl is safe.

## Stage 2 — Enrich metadata and score relevance

```powershell
python scripts/enrich_tiktok_metadata.py
```

This fills:

- video ID,
- title/description,
- author,
- thumbnail,
- relevance score,
- relevance label.

Rows are labeled high / medium / low.

Individual metadata failures are kept but marked as errors.

## Stage 3 — Prepare transcription manifest

Build a large batch from high + medium candidates:

```powershell
python scripts/prepare_saveto_batch.py --limit 200 --min-relevance medium
```

Output:

```text
data/transcripts/saveto_batch.csv
```

High-relevance sources are ordered first.

## Stage 4 — Acquire transcripts with Saveto + Playwright

Start conservatively:

```powershell
python scripts/crawl_saveto_playwright.py --workers 3
```

The script now processes the entire manifest by default.

It is resumable:

- existing TXT + JSON files are skipped,
- failed videos do not stop the batch,
- rerunning the same command continues unfinished sources.

If stable, increase concurrency:

```powershell
python scripts/crawl_saveto_playwright.py --workers 5
```

Do not use `--force` during normal resume runs.

Output:

```text
data/transcripts/raw/SRCxxxx.txt
data/transcripts/json/SRCxxxx.json
data/processed/saveto/acquisition_report.csv
```

## Stage 5 — Quality gate

```powershell
python scripts/process_saveto_batch.py --workers 16
```

Outputs:

```text
data/processed/saveto/transcripts_review.csv
data/processed/saveto/transcripts_accepted.csv
data/processed/saveto/transcripts_rejected.csv
```

Only `transcripts_accepted.csv` enters recipe extraction.

## Resume strategy

Every stage writes persistent outputs, so the workflow can be interrupted safely.

```text
crawl URL      -> video_sources.csv
metadata       -> same CSV with status/relevance
manifest       -> saveto_batch.csv
transcription  -> per-source TXT/JSON
quality        -> accepted/rejected CSV
```

For a 200-video run, do not restart from zero after a failure. Rerun the failed stage.
