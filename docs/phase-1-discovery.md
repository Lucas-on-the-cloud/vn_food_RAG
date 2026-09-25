# Phase 1A — Automated Recipe Source Discovery

The discovery step is automated. The crawler searches TikTok by keyword, scrolls the search results, extracts public video URLs, removes duplicates and writes the results to:

`data/sources/video_sources.csv`

It does **not** attempt to bypass CAPTCHA, login or anti-bot challenges. Run it with a visible browser first. If TikTok asks for verification, complete it normally in the opened browser and return to the terminal.

## 1. Install dependencies

From the repository root:

```bash
pip install -r requirements.txt
```

If you use Microsoft Edge (recommended on Windows), no Playwright browser download is normally needed.

If Edge/Chrome launching does not work, install Playwright Chromium:

```bash
python -m playwright install chromium
```

## 2. Test one keyword first

```bash
python scripts/crawl_tiktok_search.py --keyword "món ăn sinh viên" --limit 10
```

Default browser: Microsoft Edge.

Expected behavior:

1. Edge opens.
2. TikTok search opens automatically.
3. The script scrolls.
4. Video URLs are collected.
5. Duplicates are skipped.
6. New rows are saved into `data/sources/video_sources.csv`.

Example output:

```text
[SEARCH] món ăn sinh viên
  scroll 00/25: 8/10 unique video links
  scroll 01/25: 14/10 unique video links

[SAVED] keyword='món ăn sinh viên' found=10 new=10 duplicates=0
```

## 3. If TikTok asks for verification

Do not close the browser.

Complete login/CAPTCHA/verification in the browser manually.

When the terminal shows:

```text
If TikTok is showing login/CAPTCHA/verification,
complete it in the browser window, then press ENTER here.
```

press ENTER after the page is usable.

The browser profile is stored locally in:

`.browser/tiktok-profile/`

so the same session can be reused on later runs.

## 4. Try 20 URLs for one keyword

After the first test works:

```bash
python scripts/crawl_tiktok_search.py --keyword "món ăn sinh viên" --limit 20
```

Re-running the command is safe: existing canonical video URLs are skipped.

## 5. Crawl seed keywords automatically

The seed file is:

`data/sources/seed_keywords.csv`

Test only the first 3 high-priority keywords:

```bash
python scripts/crawl_tiktok_search.py --from-seed --priority high --max-keywords 3 --limit 20
```

This requests up to about 60 discovered results before cross-keyword deduplication.

Once that works, increase gradually:

```bash
python scripts/crawl_tiktok_search.py --from-seed --priority high --max-keywords 10 --limit 30
```

## 6. Browser options

Use Edge:

```bash
python scripts/crawl_tiktok_search.py --keyword "món ăn sinh viên" --limit 10 --browser edge
```

Use installed Chrome:

```bash
python scripts/crawl_tiktok_search.py --keyword "món ăn sinh viên" --limit 10 --browser chrome
```

Use Playwright Chromium:

```bash
python scripts/crawl_tiktok_search.py --keyword "món ăn sinh viên" --limit 10 --browser chromium
```

Visible mode is recommended during development.

Headless mode is available later:

```bash
python scripts/crawl_tiktok_search.py --keyword "món ăn sinh viên" --limit 20 --headless
```

but TikTok may behave differently in headless mode.

## 7. Output columns

`video_sources.csv` contains:

- `source_id`
- `url`
- `platform`
- `keyword`
- `category`
- `creator`
- `title`
- `status`
- `notes`

The crawler currently extracts URL and creator reliably from the link. Title text is best-effort because TikTok's rendered search DOM can change.

## First milestone

Do not crawl 1,000 links immediately.

First run:

```bash
python scripts/crawl_tiktok_search.py --keyword "món ăn sinh viên" --limit 10
```

Inspect the resulting CSV. If the URLs are good, the next stage will add automatic metadata/relevance filtering and then URL-to-text extraction.
