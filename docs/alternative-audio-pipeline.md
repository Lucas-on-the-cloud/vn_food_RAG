# Alternative Pipeline: Parallel Audio + GPU Whisper

Saveto is no longer required for the main pipeline.

## Architecture

```text
TikTok URL discovery
        ↓
parallel metadata enrichment
        ↓
high/medium recipe candidates
        ↓
parallel TikTok media capture
        ↓
parallel FFmpeg audio extraction
        ↓
FLAC dataset
        ↓
Kaggle GPU
        ↓
faster-whisper large-v3 batched inference
        ↓
transcript quality gate
        ↓
structured recipe extraction
```

## Why this pipeline

- no guest quota
- no external transcript-service dependency
- resumable
- audio extraction runs concurrently
- transcription uses GPU-optimized batched inference
- failed videos are skipped

## 1. Extract audio locally

```powershell
python scripts/extract_tiktok_audio_parallel.py --workers 4 --min-relevance medium
```

If stable:

```powershell
python scripts/extract_tiktok_audio_parallel.py --workers 6 --min-relevance medium
```

Existing FLAC files are skipped automatically.

## 2. Package for Kaggle

```powershell
python scripts/package_audio_for_kaggle.py
```

Output:

```text
exports/vn_food_audio_kaggle.zip
```

Upload the ZIP to Kaggle and expose its audio folder as a dataset/input.

## 3. Kaggle setup

In a Kaggle GPU notebook:

```python
!pip install -q faster-whisper
```

Then upload/run:

```text
scripts/kaggle_transcribe_faster_whisper.py
```

Example:

```bash
python kaggle_transcribe_faster_whisper.py \
  --audio-dir /kaggle/input/vn-food-audio/audio \
  --batch-size 16
```

For a T4 with memory pressure, reduce to:

```bash
--batch-size 8
```

## 4. Import transcript JSON

Download the transcript JSON directory from Kaggle.

The next repository stage should normalize these JSON files into the same transcript format used by the quality gate.

## Parallelism

- TikTok URL crawl: parallel keyword pages
- metadata: parallel video pages
- audio extraction: parallel video pages + FFmpeg jobs
- Whisper: GPU batched inference
- quality filtering: thread-pool parallelism

The only serialized operations are shared CSV writes and one model instance on a single GPU.
