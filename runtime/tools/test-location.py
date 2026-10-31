#!/usr/bin/env python3
"""直接測試 MyAgent 的 macOS Core Location helper。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Test the MyAgent location helper")
    parser.add_argument(
        "--helper",
        type=Path,
        default=Path("tools/location_helper.app/Contents/MacOS/location_helper"),
        help="Path to the compiled location helper",
    )
    parser.add_argument("--timeout", type=float, default=65.0)
    args = parser.parse_args()

    helper = args.helper.expanduser()
    if not helper.is_file():
        print(f"找不到 location helper：{helper}", file=sys.stderr)
        print("請先執行：./tools/build-location-helper.sh", file=sys.stderr)
        return 2

    try:
        result = subprocess.run(
            [str(helper)],
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("等待定位逾時。請確認 macOS 定位服務已開啟。", file=sys.stderr)
        return 124
    except OSError as exc:
        print(f"無法啟動 location helper：{exc}", file=sys.stderr)
        return 1

    output = result.stdout.strip()
    if not output:
        print("location helper 沒有回傳資料。", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        return result.returncode or 1

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        print(f"收到非 JSON 回應：{output}", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
