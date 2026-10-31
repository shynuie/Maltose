from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from myagent.logging import configure_logging
from .enrollment import evaluate_enrollment_utterance
from .listening import VADSettings, microphone_events, write_utterance_wav
from .speaker import (
    ProfileSpeakerIdentifier,
    SpeakerIdentityManager,
    SpeakerProfileStore,
    SpeechBrainECAPAEncoder,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Continuously test local speaker recognition from the microphone."
    )
    parser.add_argument("--profiles", type=Path, default=Path("data/speaker/speaker_profiles.sqlite3"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/speechbrain-ecapa"))
    parser.add_argument("--device", help="sounddevice input device id or name.")
    parser.add_argument("--max-wait", type=float, default=None, help="Seconds to wait for each utterance.")
    parser.add_argument("--low-threshold", type=float, default=0.20)
    parser.add_argument("--high-threshold", type=float, default=0.35)
    parser.add_argument("--min-duration", type=float, default=0.5)
    parser.add_argument("--max-duration", type=float, default=20.0)
    parser.add_argument("--min-rms", type=int, default=150)
    parser.add_argument("--min-peak", type=int, default=700)
    parser.add_argument("--max-peak", type=int, default=32000)
    parser.add_argument("--vad-aggressiveness", type=int, default=2)
    parser.add_argument("--frame-ms", type=int, default=20)
    parser.add_argument("--start-trigger-ms", type=int, default=160)
    parser.add_argument("--end-silence-ms", type=int, default=700)
    parser.add_argument("--pre-roll-ms", type=int, default=300)
    return parser


def _parse_device(device: str | None) -> str | int | None:
    if device is None:
        return None
    try:
        return int(device)
    except ValueError:
        return device


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    if not 0.0 <= args.low_threshold < args.high_threshold <= 1.0:
        raise SystemExit("thresholds must satisfy 0 <= low < high <= 1")

    store = SpeakerProfileStore(args.profiles)
    encoder = SpeechBrainECAPAEncoder(savedir=args.model_dir)
    # Use -1 here so the manager can display the best raw match even when it
    # falls below the acceptance threshold.
    identifier = ProfileSpeakerIdentifier(store, encoder, threshold=-1.0)
    manager = SpeakerIdentityManager(
        identifier,
        low_threshold=args.low_threshold,
        high_threshold=args.high_threshold,
    )
    settings = VADSettings(
        frame_ms=args.frame_ms,
        aggressiveness=args.vad_aggressiveness,
        start_trigger_ms=args.start_trigger_ms,
        end_silence_ms=args.end_silence_ms,
        pre_roll_ms=args.pre_roll_ms,
    )

    profiles = store.list_profiles()
    print("目前已註冊的聲紋：", flush=True)
    for profile in profiles:
        print(
            f"  {profile['user_id']} samples={profile['sample_count']} "
            f"model={profile['embedding_model']}",
            flush=True,
        )
    print("\n開始監聽；請逐句說話，按 Ctrl-C 結束。", flush=True)

    try:
        with tempfile.TemporaryDirectory(prefix="myagent-speaker-test-") as temp_dir:
            sequence = 0
            for event in microphone_events(
                settings=settings,
                device=_parse_device(args.device),
                standby_timeout=args.max_wait,
            ):
                if event.kind == "speech_started":
                    print("\n[錄音中]", flush=True)
                    continue
                if event.kind == "standby_timeout":
                    print("等待逾時，測試結束。", flush=True)
                    break
                if event.kind != "speech_ended" or event.utterance is None:
                    continue

                quality = evaluate_enrollment_utterance(
                    event.utterance,
                    min_duration=args.min_duration,
                    max_duration=args.max_duration,
                    min_rms=args.min_rms,
                    min_peak=args.min_peak,
                    max_peak=args.max_peak,
                )
                print(
                    f"[錄音完成] duration={quality.stats.duration_seconds:.2f}s "
                    f"rms={quality.stats.rms} peak={quality.stats.peak}",
                    flush=True,
                )
                if not quality.valid:
                    print(f"[跳過] {quality.reason or '錄音品質不合格'}", flush=True)
                    continue

                sequence += 1
                path = Path(temp_dir) / f"utterance-{sequence:04d}.wav"
                write_utterance_wav(path, event.utterance)
                future = manager.submit(path)
                candidate = future.result()
                deadline = time.monotonic() + 1.0
                while manager.snapshot().score != candidate.score and time.monotonic() < deadline:
                    time.sleep(0.001)
                state = manager.snapshot()
                print(
                    json.dumps(
                        {
                            "candidate_user": candidate.user_id,
                            "candidate_score": candidate.score,
                            "current_user": state.user_id,
                            "current_score": state.score,
                            "status": state.status,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    except KeyboardInterrupt:
        print("\n已停止語音辨識測試。", flush=True)
    finally:
        manager.close()
        store.close()


if __name__ == "__main__":
    main()
