# Phase 1B — TikTok Metadata Enrichment

After URL discovery, enrich each TikTok URL with metadata before doing any audio transcription.

TikTok documents an official oEmbed endpoint that accepts a TikTok video URL and returns metadata such as title/description, creator name and thumbnail.

## Why this step exists

The search crawler can reliably collect video links, but text rendered on TikTok search cards is not reliable metadata. For example, it can accidentally capture a like count instead of the caption.

This step replaces that noisy text with oEmbed metadata.

## 1. Pull the latest repository

```bash
git pull origin main
```

## 2. Test only one URL

```bash
python scripts/enrich_tiktok_metadata.py --source-id SRC0001
```

Expected output:

```text
[1] SRC0001
    https://www.tiktok.com/@.../video/...
    title     : ...
    author    : ...
    relevance : high (5)
```

Then open:

`data/sources/video_sources.csv`

New fields include:

- `video_id`
- `author_name`
- `thumbnail_url`
- `relevance_score`
- `relevance_label`

A successful row gets:

`status = metadata_ready`

## 3. If the first URL works, process all 10

```bash
python scripts/enrich_tiktok_metadata.py --limit 10
```

The script saves after every request, so an interrupted run keeps completed rows.

## 4. Inspect the result

The first baseline relevance labels are:

- `high`: very likely worth sending to transcription
- `medium`: possible recipe; keep for now
- `low`: probably not useful recipe content

The relevance score is only an interpretable heuristic based on caption + search keyword. It is **not** our final AI classifier.

Do not delete low-scoring rows yet. They become useful negative examples later.

## 5. Commit enriched metadata

After checking the CSV:

```bash
git status
git add data/sources/video_sources.csv
git commit -m "data: enrich initial TikTok recipe sources"
git push origin main
```

## Next step

Once the first 10 rows contain real captions, we inspect the distribution and decide which sources should enter URL-to-text transcription.
