from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from maltose.logging import configure_logging
from .enrollment import ENROLLMENT_PROMPTS, evaluate_enrollment_utterance
from .listening import VADSettings, microphone_events, write_utterance_wav
from .speaker import SpeakerProfileStore, SpeechBrainECAPAEncoder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactively record and enroll a speaker voice profile."
    )
    parser.add_argument(
        "--user-id",
        help="Stable user id; defaults to the next sequential user-NNN id.",
    )
    parser.add_argument("--profiles", type=Path, default=Path("data/speaker/speaker_profiles.sqlite3"))
    parser.add_argument("--model-dir", type=Path, default=Path("models/speechbrain-ecapa"))
    parser.add_argument("--device", help="sounddevice input device id or name.")
    parser.add_argument("--max-wait", type=float, default=20.0)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--min-duration", type=float, default=0.8)
    parser.add_argument("--max-duration", type=float, default=12.0)
    parser.add_argument("--min-rms", type=int, default=250)
    parser.add_argument("--min-peak", type=int, default=1000)
    parser.add_argument("--max-peak", type=int, default=32000)
    parser.add_argument("--vad-aggressiveness", type=int, default=2)
    parser.add_argument("--end-silence-ms", type=int, default=700)
    parser.add_argument(
        "--keep-recordings",
        type=Path,
        help="Optional directory for keeping accepted enrollment recordings.",
    )
    return parser


def _parse_device(device: str | None) -> str | int | None:
    if device is None:
        return None
    try:
        return int(device)
    except ValueError:
        return device


def _record_one(args: argparse.Namespace, prompt: str, index: int):
    print(f"\n第 {index}/{len(ENROLLMENT_PROMPTS)} 句：{prompt}", flush=True)
    print("請直接說話；系統會自動偵測開始與結束。", flush=True)
    settings = VADSettings(
        aggressiveness=args.vad_aggressiveness,
        end_silence_ms=args.end_silence_ms,
    )
    for event in microphone_events(
        settings=settings,
        device=_parse_device(args.device),
        standby_timeout=args.max_wait,
    ):
        if event.kind == "speech_started":
            print("已偵測到說話。", flush=True)
        elif event.kind == "standby_timeout":
            return None, "等待說話逾時"
        elif event.kind == "speech_ended" and event.utterance is not None:
            quality = evaluate_enrollment_utterance(
                event.utterance,
                min_duration=args.min_duration,
                max_duration=args.max_duration,
                min_rms=args.min_rms,
                min_peak=args.min_peak,
                max_peak=args.max_peak,
            )
            print(
                f"錄音完成：{quality.stats.duration_seconds:.2f}s "
                f"rms={quality.stats.rms} peak={quality.stats.peak}",
                flush=True,
            )
            if not quality.valid:
                return None, quality.reason or "錄音品質不合格"
            return event.utterance, None
    return None, "錄音流程提前結束"


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    if args.attempts < 1:
        raise SystemExit("--attempts must be positive")

    encoder = SpeechBrainECAPAEncoder(savedir=args.model_dir)
    store = SpeakerProfileStore(args.profiles)
    try:
        user_id = args.user_id or store.peek_next_user_id()
        print(f"本次註冊身份 ID：{user_id}", flush=True)
        with tempfile.TemporaryDirectory(prefix="myagent-enrollment-") as temp_dir:
            embeddings = []
            for index, prompt in enumerate(ENROLLMENT_PROMPTS, start=1):
                accepted = None
                for attempt in range(1, args.attempts + 1):
                    try:
                        accepted, reason = _record_one(args, prompt, index)
                    except KeyboardInterrupt:
                        print("\n已取消聲音註冊。", flush=True)
                        return
                    if accepted is not None:
                        break
                    print(
                        f"這句錄音不合格：{reason}。請重新錄製 "
                        f"（{attempt}/{args.attempts}）。",
                        flush=True,
                    )
                if accepted is None:
                    raise SystemExit(f"第 {index} 句連續錄音失敗，已取消註冊。")

                path = Path(temp_dir) / f"sample-{index:02d}.wav"
                if args.keep_recordings is not None:
                    path = args.keep_recordings / f"{user_id}-{index:02d}.wav"
                write_utterance_wav(path, accepted)
                embeddings.append(encoder.encode(path))

            print("\n所有句子都已完成。", flush=True)
            confirmation = input(f"確認將這些聲音註冊為 {user_id!r}？[y/N] ")
            if confirmation.strip().lower() not in {"y", "yes", "是"}:
                print("已取消，沒有寫入聲紋資料。", flush=True)
                return
            if args.user_id is None:
                user_id = store.next_user_id()
            result = store.enroll(
                user_id,
                embeddings,
                model_name=encoder.model_name,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
