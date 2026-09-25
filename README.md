# VietPantry-TW

A Vietnamese student-food recommendation project for people living in Taiwan.

The project combines:

- TikTok recipe discovery
- external transcript generation
- transcript quality filtering
- structured recipe extraction
- ingredient normalization
- ingredient-image recognition
- recipe retrieval and RAG recommendation

## Current Architecture

```text
TikTok keyword search
        |
        v
video_sources.csv
        |
        v
Saveto TikTok Transcript Generator
(manual/external transcription provider)
        |
        v
SRCxxxx.txt
        |
        v
parallel transcript quality gate
        |
        +---- rejected / missing / junk
        |
        v
accepted transcripts
        |
        v
structured recipe extraction
        |
        v
recipe knowledge base
        |
        +-------------------------+
                                  |
Taiwan ingredient images         |
        |                         |
        v                         |
ingredient recognition           |
        |                         |
        +------ recipe retrieval -+
                    |
                    v
              RAG assistant
```

## Why Saveto is now the primary transcription path

Local Whisper/Kaggle transcription worked, but it added a large amount of engineering overhead around TikTok media extraction, FFmpeg, GPU inference and noisy speech.

For this project, transcript generation is infrastructure rather than the research contribution. The main research value is in:

1. building a Vietnamese student-recipe knowledge base,
2. recognizing ingredients available in Taiwan,
3. retrieving recipes from available ingredients,
4. evaluating recommendation quality.

Saveto is therefore treated as an **external transcript provider**.

The repository does not automate Saveto itself. Raw transcripts are copied/downloaded from Saveto and then processed locally.

## Phase 1 — First 10 Videos

The first experiment uses:

`data/transcripts/saveto_batch_10.csv`

Workflow:

### 1. Pull the repository

```powershell
git pull origin main
pip install -r requirements.txt
```

### 2. Generate/reset a 10-video batch if needed

```powershell
python scripts/prepare_saveto_batch.py --limit 10
```

### 3. Generate transcripts with Saveto

Open the TikTok transcript generator and process each URL from the manifest.

Save/copy each transcript as:

```text
data/transcripts/raw/
  SRC0001.txt
  SRC0002.txt
  ...
  SRC0010.txt
```

If a TikTok video cannot load, contains no useful speech, or produces a bad transcript, simply skip it.

### 4. Process all available transcripts in parallel

```powershell
python scripts/process_saveto_batch.py --workers 10
```

Output:

```text
data/processed/saveto/
  transcripts_review.csv
  transcripts_accepted.csv
  transcripts_rejected.csv
```

Missing files are logged and skipped automatically.

## Scaling Philosophy

The pipeline is **best effort**.

For 100–200+ source videos, individual failures are expected:

```text
200 discovered videos
       |
       +-- media/transcript failures -> skip
       +-- music/no speech            -> skip
       +-- non-recipe content         -> skip
       |
       v
clean usable recipe transcripts
```

The goal is not 100% extraction yield. The goal is a sufficiently large, clean recipe dataset.

## Recipe Schema

See:

`dataset/recipes/recipe_schema.json`

Main fields include:

- dish name
- source URL
- ingredients
- quantities
- cooking steps
- cooking time
- difficulty
- estimated cost in TWD
- equipment
- tags

## Ingredient Dataset

The starter ingredient mapping is:

`dataset/ingredients/ingredient_mapping.csv`

It contains Vietnamese, Traditional Chinese and English names for common ingredients available in Taiwan.

## Recommendation Baseline

```text
score =
    0.50 * ingredient_match
  + 0.15 * cooking_time_score
  + 0.15 * cost_score
  + 0.10 * difficulty_score
  + 0.10 * user_preference_score
```

## Repository Structure

```text
configs/
data/
  samples/
  sources/
  transcripts/
dataset/
  ingredients/
  recipes/
docs/
scripts/
src/
  recipe_extraction/
  recommendation/
  retrieval/
tests/
```

## Current Status

- [x] TikTok keyword crawler
- [x] first 10 TikTok sources
- [x] TikTok metadata enrichment
- [x] Saveto-first transcription architecture
- [x] parallel transcript quality processing
- [ ] validate first 10 Saveto transcripts
- [ ] structured recipe extraction
- [ ] scale recipe collection to 100–200+ videos
- [ ] ingredient vision dataset
- [ ] ingredient recognition baseline
- [ ] vector retrieval / RAG
