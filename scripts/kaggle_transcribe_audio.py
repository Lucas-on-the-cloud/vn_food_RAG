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
        description="Transcribe packaged VN food audio on a GPU machine."
    )
    parser.add_argument(
        "--audio-dir",
        default="/kaggle/input/vn-food-audio/audio",
    )
    parser.add_argument(
        "--output-dir",
        default="/kaggle/working/transcripts",
    )
    parser.add_argument(
        "--model",
        default="large-v3",
        help="Whisper model, e.g. medium, large-v3, turbo.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    import torch
    import whisper

    audio_dir = Path(args.audio_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(audio_dir.glob("*.flac"))
    if not files:
        raise SystemExit(f"No .flac files found in {audio_dir}")

    device = "cuda" if torch.cuda.is_available() else "cpu"

    print("=" * 72)
    print("VN Food Whisper Transcription")
    print("=" * 72)
    print(f"Device : {device}")
    print(f"Model  : {args.model}")
    print(f"Files  : {len(files)}")

    model = whisper.load_model(args.model, device=device)

    for index, audio_path in enumerate(files, start=1):
        source_id = audio_path.stem
        print(f"\n[{index}/{len(files)}] {source_id}")

        result = model.transcribe(
            str(audio_path),
            language="vi",
            temperature=0,
            beam_size=5,
            initial_prompt=DEFAULT_PROMPT,
            condition_on_previous_text=True,
            verbose=False,
        )

        output = {
            "source_id": source_id,
            "audio_file": audio_path.name,
            "model": args.model,
            "device": device,
            "language": result.get("language", "vi"),
            "text": str(result.get("text", "")).strip(),
            "segments": [
                {
                    "start": segment.get("start"),
                    "end": segment.get("end"),
                    "text": str(segment.get("text", "")).strip(),
                }
                for segment in result.get("segments", [])
                if str(segment.get("text", "")).strip()
            ],
        }

        output_path = output_dir / f"{source_id}.json"
        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"    chars : {len(output['text'])}")
        print(f"    saved : {output_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
