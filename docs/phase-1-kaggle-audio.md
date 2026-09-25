# Phase 1C — Local Audio, Kaggle GPU Transcription

This is the recommended transcription workflow.

## Why

GPU does not make the same Whisper model inherently more accurate.

The benefit is that Kaggle GPU lets us run a **larger model** such as:

- `medium`
- `large-v3`

which can improve difficult Vietnamese TikTok speech compared with `base` or `small`.

## Pipeline

```text
TikTok URLs
   |
   v
Local Edge/Playwright
   |
   v
audio-only FLAC files
   |
   v
ZIP package
   |
   v
Kaggle Dataset / Notebook
   |
   v
Whisper large-v3 on GPU
   |
   v
transcript JSON
```

## Local Step 1 — Extract one audio file

```powershell
git pull origin main
python scripts/extract_tiktok_audio.py --source-id SRC0001
```

Expected output:

```text
[1/1] SRC0001
    media  : captured ...
    try    : candidate ...
    saved  : ...\data\raw\audio\SRC0001.flac
```

## Local Step 2 — Listen to it

Open:

`data/raw/audio/SRC0001.flac`

Make sure it contains the actual TikTok voice/audio.

## Local Step 3 — Extract the first 10

```powershell
python scripts/extract_tiktok_audio.py --limit 10
```

Existing files are skipped.

## Local Step 4 — Create Kaggle ZIP

```powershell
python scripts/package_audio_for_kaggle.py
```

Output:

`exports/vn_food_audio_kaggle.zip`

The ZIP contains:

```text
audio/
  SRC0001.flac
  SRC0002.flac
  ...

manifest.json
```

## Kaggle Step 1 — Upload

Create a Kaggle Dataset from the extracted ZIP contents.

Suggested dataset name:

`vn-food-audio`

The resulting input path is typically similar to:

`/kaggle/input/vn-food-audio/audio`

## Kaggle Step 2 — Enable GPU

Notebook:

`Settings -> Accelerator -> GPU`

Then verify:

```python
import torch
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0))
```

## Kaggle Step 3 — Install Whisper

```python
!pip install -q openai-whisper
```

## Kaggle Step 4 — Upload/copy the project script

Use:

`scripts/kaggle_transcribe_audio.py`

or copy its content into a notebook cell.

Run:

```bash
!python scripts/kaggle_transcribe_audio.py \
  --audio-dir /kaggle/input/vn-food-audio/audio \
  --output-dir /kaggle/working/transcripts \
  --model large-v3
```

If `large-v3` is too slow or VRAM-limited:

```bash
--model medium
```

## Kaggle Output

```text
/kaggle/working/transcripts/
  SRC0001.json
  SRC0002.json
  ...
```

Download this folder after transcription.

## Important

Do not scale to 1,000 videos yet.

First compare:

- local `base`
- local `small`
- Kaggle `medium`
- Kaggle `large-v3`

on the **same 5-10 audio files**.

Then choose the best accuracy/cost/speed tradeoff.
