# Phase 1C — URL to Transcript

This stage turns a TikTok source URL into text without keeping the full video file.

## Strategy

```text
TikTok URL
   |
   +--> subtitle available? --> save transcript text
   |
   +--> no subtitle
           |
           v
      audio-only download
      to a temporary folder
           |
           v
         Whisper
           |
           v
      transcript JSON
           |
           v
      temporary audio deleted
```

The script never intentionally downloads/stores the full TikTok video.

## 1. Pull new code

```bash
git pull origin main
```

## 2. Install/update Python packages

```bash
pip install -r requirements.txt
```

## 3. First try subtitle-only

This is the cheapest test because Whisper is not used:

```bash
python scripts/transcribe_tiktok_sources.py --source-id SRC0001 --subtitle-only
```

If TikTok exposes Vietnamese captions, output will look like:

```text
method : subtitle
chars  : 512
saved  : .../data/processed/transcripts/SRC0001.json
```

## 4. If subtitle is unavailable, use Whisper fallback

```bash
python scripts/transcribe_tiktok_sources.py --source-id SRC0001
```

Default Whisper model: `base`.

The first Whisper run downloads the model weights once.

For better Vietnamese accuracy later:

```bash
python scripts/transcribe_tiktok_sources.py --source-id SRC0001 --whisper-model small
```

## 5. FFmpeg requirement

Whisper needs FFmpeg to decode audio.

Check:

```bash
ffmpeg -version
```

If Windows says `ffmpeg` is not recognized, install FFmpeg and reopen the terminal. One common Windows option is:

```bash
winget install Gyan.FFmpeg
```

Then verify again:

```bash
ffmpeg -version
```

## 6. Process the first 10

Only after SRC0001 succeeds:

```bash
python scripts/transcribe_tiktok_sources.py --limit 10
```

Existing transcript JSON files are skipped automatically.

To overwrite:

```bash
python scripts/transcribe_tiktok_sources.py --source-id SRC0001 --force
```

## Output

Transcript files are stored locally:

```text
data/processed/transcripts/
    SRC0001.json
    SRC0002.json
    ...
```

Example:

```json
{
  "source_id": "SRC0001",
  "url": "https://www.tiktok.com/@.../video/...",
  "video_id": "...",
  "title": "...",
  "method": "subtitle",
  "language": "vi-VN",
  "text": "Hôm nay mình sẽ...",
  "segments": []
}
```

The `data/processed` directory is intentionally ignored by Git for now because these are intermediate artifacts.

## Next stage

After 10 transcripts are working, Phase 1D will convert each transcript into strict structured recipe JSON:

`transcript -> ingredients + quantities + steps -> validated recipe record`.
