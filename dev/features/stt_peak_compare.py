"""Compare Qwen ASR transcription after two peak-normalization targets."""

from __future__ import annotations

import argparse
import tempfile
import wave
from pathlib import Path

from myagent.voice import STTRequest, create_stt_provider


def normalize_pcm(pcm: bytes, target_peak: int) -> bytes:
    import numpy

    samples = numpy.frombuffer(pcm, dtype=numpy.int16).astype(numpy.float32)
    peak = float(numpy.max(numpy.abs(samples))) if len(samples) else 0.0
    if peak <= 0:
        return pcm
    scaled = numpy.clip(samples * (target_peak / peak), -32768, 32767)
    return scaled.astype(numpy.int16).tobytes()


def write_normalized(source: Path, target: Path, peak: int) -> None:
    with wave.open(str(source), "rb") as src:
        params = src.getparams()
        pcm = src.readframes(src.getnframes())
    with wave.open(str(target), "wb") as dst:
        dst.setparams(params)
        dst.writeframes(normalize_pcm(pcm, peak))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--provider", default="qwen3-asr-0.6b")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    paths = sorted(args.input_dir.rglob("*.wav"))
    transcriber = create_stt_provider(
        provider=args.provider,
        model="small",
        device=args.device,
        compute_type="int8",
    )
    totals = {1200: 0, 12000: 0}
    correct = {1200: 0, 12000: 0}
    with tempfile.TemporaryDirectory(prefix="myagent-stt-peak-") as tmp:
        tmp_path = Path(tmp)
        for index, source in enumerate(paths, 1):
            row = []
            for target_peak in (1200, 12000):
                normalized = tmp_path / f"{index:03d}-{target_peak}.wav"
                write_normalized(source, normalized, target_peak)
                result = transcriber.transcribe(
                    STTRequest(
                        audio_path=normalized,
                        language=args.language,
                        device=args.device,
                        compute_type="int8",
                    )
                )
                text = result.text.strip()
                ok = "麦芽糖" in text or "麥芽糖" in text
                totals[target_peak] += 1
                correct[target_peak] += ok
                row.append(f"peak={target_peak} ok={ok} text={text!r}")
            print(f"{source}: " + " | ".join(row))

    print("summary")
    for target_peak in (1200, 12000):
        print(f"peak={target_peak} correct_keyword={correct[target_peak]}/{totals[target_peak]}")


if __name__ == "__main__":
    main()
