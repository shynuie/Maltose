from __future__ import annotations

import argparse
import audioop
import logging
import time
import wave
from dataclasses import replace
from pathlib import Path

from myagent.logging import configure_logging
from myagent.voice.wake import create_wake_word_detector, load_wake_word_config


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay WAV files through the wake-word detector."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("recordings/kws/positive"))
    parser.add_argument("--pattern", default="*.wav")
    parser.add_argument(
        "--dataset-kind",
        choices=("positive", "negative"),
        help="Dataset label for summary metrics; inferred from input directory when omitted.",
    )
    parser.add_argument("--wake-config", type=Path, default=Path("wake.toml"))
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument(
        "--threshold",
        type=float,
        help="Override sherpa-onnx keywords_threshold for this replay.",
    )
    parser.add_argument("--keywords-score", type=float, help="Override keyword score.")
    parser.add_argument(
        "--trailing-blanks",
        type=int,
        help="Override num_trailing_blanks.",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Disable the same per-frame peak normalization used by the live detector.",
    )
    parser.add_argument(
        "--preprocessor",
        choices=("raw", "peak", "smooth-rms", "highpass-smooth-rms", "spectral-gate"),
        help="Override KWS audio preprocessing for this replay.",
    )
    parser.add_argument("--rms-target", type=int, help="Smooth RMS AGC target.")
    parser.add_argument("--rms-noise-floor", type=int, help="Smooth RMS AGC noise floor.")
    parser.add_argument("--rms-max-gain", type=float, help="Smooth RMS AGC maximum gain.")
    parser.add_argument("--rms-attack", type=float, help="Smooth RMS AGC attack smoothing.")
    parser.add_argument("--rms-release", type=float, help="Smooth RMS AGC release smoothing.")
    return parser


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    if args.sample_rate <= 0 or args.frame_ms <= 0:
        raise ValueError("--sample-rate and --frame-ms must be greater than zero")

    paths = sorted(args.input_dir.glob(args.pattern))
    if not paths:
        raise FileNotFoundError(f"No WAV files found under {args.input_dir!s}")

    config = load_wake_word_config(args.wake_config)
    if args.threshold is not None:
        if config.sherpa_onnx is None:
            raise ValueError("The wake config does not contain sherpa-onnx settings.")
        config = replace(
            config,
            sherpa_onnx=replace(
                config.sherpa_onnx,
                keywords_threshold=args.threshold,
            ),
        )
    if args.keywords_score is not None or args.trailing_blanks is not None:
        if config.sherpa_onnx is None:
            raise ValueError("The wake config does not contain sherpa-onnx settings.")
        config = replace(
            config,
            sherpa_onnx=replace(
                config.sherpa_onnx,
                keywords_score=(
                    args.keywords_score
                    if args.keywords_score is not None
                    else config.sherpa_onnx.keywords_score
                ),
                num_trailing_blanks=(
                    args.trailing_blanks
                    if args.trailing_blanks is not None
                    else config.sherpa_onnx.num_trailing_blanks
                ),
            ),
        )
    if args.no_normalize:
        config = replace(config, normalize_audio=False)
    if args.preprocessor is not None:
        config = replace(
            config,
            normalize_audio=args.preprocessor != "raw",
            normalization_mode=args.preprocessor,
        )
    rms_overrides = {
        "rms_target": args.rms_target,
        "rms_noise_floor": args.rms_noise_floor,
        "rms_attack": args.rms_attack,
        "rms_release": args.rms_release,
    }
    if args.rms_max_gain is not None:
        rms_overrides["max_gain"] = args.rms_max_gain
    rms_overrides = {key: value for key, value in rms_overrides.items() if value is not None}
    if rms_overrides:
        config = replace(config, **rms_overrides)

    detector = create_wake_word_detector(config)
    if detector is None:
        raise ValueError("Wake word detection is disabled.")

    frame_bytes = args.sample_rate * args.frame_ms // 1000 * 2
    hits = 0
    latencies: list[float] = []
    started_at = time.perf_counter()
    dataset_kind = args.dataset_kind or _infer_dataset_kind(args.input_dir)
    logger.info(
        "kws_replay_started files=%d sample_rate=%d frame_ms=%d threshold=%s preprocessor=%s",
        len(paths),
        args.sample_rate,
        args.frame_ms,
        args.threshold if args.threshold is not None else "config",
        config.normalization_mode if config.normalize_audio else "raw",
    )
    for path in paths:
        sample_rate, pcm = read_wav(path)
        if sample_rate != args.sample_rate:
            raise ValueError(
                f"{path} has sample rate {sample_rate}, expected {args.sample_rate}"
            )
        detector.reset()
        hit = None
        hit_offset = 0
        for offset in range(0, len(pcm) - frame_bytes + 1, frame_bytes):
            hit = detector.process_frame(
                pcm[offset : offset + frame_bytes], args.sample_rate
            )
            if hit is not None:
                hit_offset = offset
                break

        rms = audioop.rms(pcm, 2)
        peak = audioop.max(pcm, 2)
        if hit is not None:
            hits += 1
            latencies.append(hit_offset / (args.sample_rate * 2))
        logger.info(
            "kws_replay_file path=%s duration=%.2fs rms=%d peak=%d hit=%s keyword=%s hit_at=%.3fs",
            path,
            len(pcm) / (args.sample_rate * 2),
            rms,
            peak,
            hit is not None,
            hit.keyword if hit is not None else "",
            hit_offset / (args.sample_rate * 2) if hit is not None else -1.0,
        )
    elapsed = time.perf_counter() - started_at
    misses = len(paths) - hits
    p50 = _percentile(latencies, 0.50)
    p95 = _percentile(latencies, 0.95)
    rate_name = "tpr" if dataset_kind == "positive" else "fpr"
    rate = hits / len(paths) if paths else 0.0
    logger.info(
        "kws_replay_summary dataset=%s total=%d hits=%d misses=%d %s=%.4f "
        "latency_p50=%.3fs latency_p95=%.3fs cpu_time=%.3fs",
        dataset_kind,
        len(paths),
        hits,
        misses,
        rate_name,
        rate,
        p50,
        p95,
        elapsed,
    )


def _infer_dataset_kind(input_dir: Path) -> str:
    return "negative" if input_dir.name.lower() == "negative" else "positive"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return -1.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * percentile))
    return ordered[index]


def read_wav(path: Path) -> tuple[int, bytes]:
    with wave.open(str(path), "rb") as wav_file:
        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
            raise ValueError(f"{path} must be mono 16-bit PCM")
        return wav_file.getframerate(), wav_file.readframes(wav_file.getnframes())


if __name__ == "__main__":
    main()
