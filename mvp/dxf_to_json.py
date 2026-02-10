#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from web_app import parse_dxf_to_drawing
except ModuleNotFoundError:
    from mvp.web_app import parse_dxf_to_drawing


def main() -> None:
    parser = argparse.ArgumentParser(description="DXF 转结构化 drawing JSON")
    parser.add_argument("--in-dxf", required=True, help="输入 DXF 文件路径")
    parser.add_argument("--out-json", required=True, help="输出 JSON 文件路径")
    args = parser.parse_args()

    in_path = Path(args.in_dxf)
    out_path = Path(args.out_json)

    raw = in_path.read_bytes()
    drawing = parse_dxf_to_drawing(in_path.name, raw)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(drawing, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] converted: {out_path}")


if __name__ == "__main__":
    main()
