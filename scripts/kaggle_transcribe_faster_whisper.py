from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_PROMPT = (
    "Đây là video nấu ăn bằng tiếng Việt. Ưu tiên nhận đúng tên nguyên liệu, "
    "gia vị và thao tác nấu ăn như thịt bằm, thịt ba chỉ, trứng, đậu hũ, "
    "đậu hũ trứng, nấm đông cô, hành lá, tỏi, nước mắm, nước tương, dầu hào, "
    "đường, muối, tiêu, bột ngọt, bột năng, bột bắp, áp chảo, chiên, xào, "
    "rim, kho, luộc, hấp, nướng, nước sốt, chảo và nồi cơm điện."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Transcribe VN food audio on Kaggle with faster-whisper. "
            "The model uses GPU-optimized batched inference."
        )
    )
    parser.add_argument(
        "--audio-dir",
        default="/kaggle/input/vn-food-audio/audio",
    )
    parser.add_argument(
        "--output-dir",
        default="/kaggle/working/transcripts",
    )
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    from faster_whisper import BatchedInferencePipeline, WhisperModel

    audio_dir = Path(args.audio_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(audio_dir.glob("*.flac"))
    if not files:
        raise SystemExit(f"No .flac files found in {audio_dir}")

    print("=" * 72)
    print("VN Food faster-whisper GPU Transcription")
    print("=" * 72)
    print(f"Model      : {args.model}")
    print(f"Files      : {len(files)}")
    print(f"Batch size : {args.batch_size}")

    model = WhisperModel(
        args.model,
        device="cuda",
        compute_type="float16",
    )
    batched_model = BatchedInferencePipeline(model=model)

    success = 0
    failed = 0

    for index, audio_path in enumerate(files, start=1):
        source_id = audio_path.stem
        output_path = output_dir / f"{source_id}.json"

        if output_path.exists() and not args.force:
            print(f"[{index}/{len(files)}] {source_id} skip_existing")
            continue

        print(f"[{index}/{len(files)}] {source_id}")

        try:
            segments, info = batched_model.transcribe(
                str(audio_path),
                batch_size=args.batch_size,
                language="vi",
                beam_size=args.beam_size,
                initial_prompt=DEFAULT_PROMPT,
                vad_filter=True,
            )

            segment_rows = []
            text_parts = []

            for segment in segments:
                text = str(segment.text or "").strip()
                if not text:
                    continue

                text_parts.append(text)
                segment_rows.append({
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": text,
                })

            text = " ".join(text_parts).strip()

            payload = {
                "source_id": source_id,
                "audio_file": audio_path.name,
                "provider": "faster-whisper",
                "model": args.model,
                "language": getattr(info, "language", "vi"),
                "language_probability": float(
                    getattr(info, "language_probability", 0.0)
                ),
                "text": text,
                "segments": segment_rows,
            }

            output_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            success += 1
            print(f"    chars : {len(text)}")

        except Exception as exc:
            failed += 1
            print(f"    ERROR {type(exc).__name__}: {exc}")

    print()
    print(f"Success : {success}")
    print(f"Failed  : {failed}")


if __name__ == "__main__":
    main()
