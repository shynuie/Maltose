from __future__ import annotations

from dataclasses import dataclass

from .audio import AudioStats, measure_utterance
from .listening import Utterance


ENROLLMENT_PROMPTS: tuple[str, ...] = (
    "麥芽糖。",
    "你好，我是這台電腦的使用者。",
    "今天天氣怎麼樣？",
    "天空是藍色的，雲朵是白色的。",
    "請在下午三點提醒我喝水。",
    "我想知道明天早上會不會下雨。",
    "一二三四五六七八九十，春夏秋冬，東南西北。",
    "這是一段用來建立聲音特徵的測試語音，請以自然速度完整讀完。",
)


@dataclass(frozen=True)
class EnrollmentQuality:
    valid: bool
    reason: str | None
    stats: AudioStats


def evaluate_enrollment_utterance(
    utterance: Utterance,
    *,
    min_duration: float = 0.8,
    max_duration: float = 12.0,
    min_rms: int = 250,
    min_peak: int = 1000,
    max_peak: int = 32000,
) -> EnrollmentQuality:
    stats = measure_utterance(utterance)
    if stats.duration_seconds < min_duration:
        return EnrollmentQuality(False, f"語音太短（{stats.duration_seconds:.2f} 秒）", stats)
    if stats.duration_seconds > max_duration:
        return EnrollmentQuality(False, f"語音太長（{stats.duration_seconds:.2f} 秒）", stats)
    if stats.rms < min_rms or stats.peak < min_peak:
        return EnrollmentQuality(False, "音量太小或沒有錄到清楚的人聲", stats)
    if stats.peak > max_peak:
        return EnrollmentQuality(False, "音量過大，錄音可能爆音", stats)
    return EnrollmentQuality(True, None, stats)
