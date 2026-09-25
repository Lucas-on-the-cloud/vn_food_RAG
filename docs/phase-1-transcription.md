# Phase 1C — TikTok URL to Transcript

## Current implementation

As of September 2026, TikTok extraction through yt-dlp can fail with:

`Unexpected response from webpage request`

The project therefore does not depend on yt-dlp for the main transcription path.

Instead it reuses the Playwright/Edge session that already works for discovery and metadata:

```text
TikTok URL
    |
    v
Edge / Playwright
    |
    | capture the media URL the browser is already playing
    v
signed TikTok media URL
    |
    v
FFmpeg
    |
    | extract audio only into a temporary WAV
    v
Whisper
    |
    v
transcript JSON
    |
    v
temporary WAV deleted
```

No full MP4 is intentionally saved to disk.

Note: to transcribe the full clip, FFmpeg still has to transfer enough of the remote media stream to decode its audio. The difference is that the full video file is not persisted locally.

## 1. Pull the fix

```bash
git pull origin main
```

## 2. Update packages

```bash
pip install -r requirements.txt
```

## 3. Verify FFmpeg

```bash
ffmpeg -version
```

If Windows cannot find FFmpeg:

```bash
winget install Gyan.FFmpeg
```

Then reopen PowerShell and verify again.

## 4. Test SRC0001

Run:

```bash
python scripts/transcribe_tiktok_sources.py --source-id SRC0001
```

Expected flow:

1. Whisper loads.
2. Edge opens SRC0001 using the persistent TikTok profile.
3. The script captures the media stream URL.
4. FFmpeg writes a temporary 16 kHz mono WAV.
5. Whisper transcribes Vietnamese speech.
6. The temporary audio is deleted.
7. The transcript is saved to:

`data/processed/transcripts/SRC0001.json`

Example output:

```text
[1/1] SRC0001
    https://www.tiktok.com/@.../video/...
    media  : captured from browser
    audio  : temporary WAV (840 KiB)
    chars  : 412
    saved  : .../data/processed/transcripts/SRC0001.json
```

## 5. Verification/login

If TikTok presents login, CAPTCHA or another normal verification screen, complete it manually in the opened Edge window.

Return to PowerShell and press ENTER when prompted.

The project does not implement CAPTCHA bypassing.

## 6. Inspect the transcript

Open:

`data/processed/transcripts/SRC0001.json`

Important fields:

```json
{
  "source_id": "SRC0001",
  "method": "browser_stream_whisper",
  "language": "vi",
  "text": "...",
  "segments": []
}
```

## 7. Then process more

Only after SRC0001 is correct:

```bash
python scripts/transcribe_tiktok_sources.py --limit 10
```

Existing transcript JSON files are skipped automatically.

To regenerate one:

```bash
python scripts/transcribe_tiktok_sources.py --source-id SRC0001 --force
```

For higher Vietnamese accuracy later:

```bash
python scripts/transcribe_tiktok_sources.py --source-id SRC0001 --force --whisper-model small
```

## Git policy

`data/processed/` remains ignored by Git while we are debugging the pipeline.

Once the transcript schema is stable, we will decide whether to version the final cleaned text dataset separately.

## Next stage

After 10 transcripts work:

`transcript -> recipe extraction -> ingredient normalization -> validated recipe JSON`
