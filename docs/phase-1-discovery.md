# Phase 1A — Recipe Source Discovery

The first goal is intentionally small:

> Collect 5-10 good TikTok recipe URLs before building transcription.

Do not download 1,000 videos yet.

## Step 1 — Choose a keyword

Open:

`data/sources/seed_keywords.csv`

Start with high-priority keywords such as:

- món ăn sinh viên
- món ăn tiết kiệm
- món ngon dễ làm
- món ăn 15 phút
- món ăn nồi cơm điện

## Step 2 — Search TikTok manually

Search TikTok using one keyword.

Choose videos that are likely to contain an actual recipe, not only food entertainment.

Prefer videos with:

- visible ingredients;
- spoken instructions or captions;
- clear cooking steps;
- student-friendly equipment;
- affordable ingredients.

For the first experiment, collect only 5-10 URLs.

## Step 3 — Add each URL

From the repository root:

```bash
python scripts/add_source.py --url "TIKTOK_URL" --keyword "món ăn sinh viên"
```

Optional metadata:

```bash
python scripts/add_source.py ^
  --url "TIKTOK_URL" ^
  --keyword "món ăn sinh viên" ^
  --creator "creator_name" ^
  --title "video caption"
```

On PowerShell, either run the command on one line or use the PowerShell backtick instead of `^`.

## Step 4 — Check the registry

Open:

`data/sources/video_sources.csv`

Each accepted URL receives an ID such as:

`SRC0001`

The script also removes tracking query parameters and rejects duplicate URLs.

## Definition of done

This step is complete when `video_sources.csv` contains 5-10 useful TikTok cooking URLs.

The next step will enrich these URLs automatically using TikTok oEmbed metadata before any transcription is attempted.
