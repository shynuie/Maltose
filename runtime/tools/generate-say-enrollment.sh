#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VOICE="${MYAGENT_SAY_VOICE:-Tingting}"
OUTPUT_DIR="${1:-recordings/say-enrollment-test}"

mkdir -p "$OUTPUT_DIR"

phrases=(
  '麥芽糖。'
  '你好，我是這台電腦的使用者。'
  '今天天氣怎麼樣？'
  '天空是藍色的，雲朵是白色的。'
  '請在下午三點提醒我喝水。'
  '我想知道明天早上會不會下雨。'
  '一二三四五六七八九十，春夏秋冬，東南西北。'
  '這是一段用來建立聲音特徵的測試語音，請以自然速度完整讀完。'
)

echo "Generating macOS say samples with voice: $VOICE"
for index in "${!phrases[@]}"; do
  number=$((index + 1))
  aiff_path="$OUTPUT_DIR/$(printf '%02d' "$number").aiff"
  wav_path="$OUTPUT_DIR/$(printf '%02d' "$number").wav"

  say -v "$VOICE" -o "$aiff_path" "${phrases[$index]}"
  afconvert -f WAVE -d LEI16@16000 "$aiff_path" "$wav_path"

  audio_bytes=$(afinfo "$wav_path" | awk -F': ' '/audio bytes:/ {print $2; exit}')
  if [[ -z "$audio_bytes" || "$audio_bytes" == "0" ]]; then
    echo "ERROR: generated empty audio: $wav_path" >&2
    exit 1
  fi
  echo "[$number/8] $wav_path ($audio_bytes bytes)"
done

echo "Generated 8 WAV files in $OUTPUT_DIR"
echo "The original enrollment files remain in recordings/enrollment."
