#!/usr/bin/env python3
"""零件审核 + 工艺建议 最小闭环示例

用法:
python3 mvp/min_loop.py \
  --part mvp/examples/part_input.json \
  --drawing mvp/examples/drawing_input.json \
  --out mvp/output/report.md
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class RuleHit:
    rule_id: str
    severity: str
    message: str
    suggestion: str


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def check_rules(part: dict[str, Any], drawing: dict[str, Any]) -> list[RuleHit]:
    hits: list[RuleHit] = []
    geo = part["geometry"]

    # DFM-HOLE-001: 深径比
    for hole in geo.get("holes", []):
        d = hole["diameter_mm"]
        depth = hole["depth_mm"]
        ratio = depth / d if d else 0
        if ratio > 8:
            hits.append(
                RuleHit(
                    "DFM-HOLE-001",
                    "high",
                    f"孔 {hole['id']} 深径比 {ratio:.1f} > 8，钻削风险高。",
                    "改通孔/增大孔径/改分步钻削或枪钻工艺。",
                )
            )

    # DFM-WALL-001: 最小壁厚
    if geo.get("min_wall_thickness_mm", 999) < 2.0:
        hits.append(
            RuleHit(
                "DFM-WALL-001",
                "high",
                f"最小壁厚 {geo['min_wall_thickness_mm']}mm < 2.0mm，易变形。",
                "增厚薄壁区或增加工艺筋，优化装夹位置。",
            )
        )

    # DFM-FEATURE-001: 非必要装饰倒角
    for ft in geo.get("features", []):
        if ft.get("type") == "decorative_chamfer" and ft.get("count", 0) >= 4:
            hits.append(
                RuleHit(
                    "DFM-FEATURE-001",
                    "medium",
                    f"发现 {ft['count']} 处装饰倒角，可能存在不必要加工特征。",
                    "保留功能倒角，删除非功能倒角以减少工时。",
                )
            )

    # 2D/3D 一致性: 孔径比对
    model_holes = {h["id"]: h["diameter_mm"] for h in geo.get("holes", [])}
    for h in drawing.get("dimensions", {}).get("holes", []):
        hid = h["id"]
        if hid in model_holes and abs(model_holes[hid] - h["diameter_mm"]) > 1e-6:
            hits.append(
                RuleHit(
                    "CONSISTENCY-2D3D-001",
                    "high",
                    f"孔 {hid} 2D={h['diameter_mm']}mm 与 3D={model_holes[hid]}mm 不一致。",
                    "核对版本并统一图纸与3D模型标注。",
                )
            )

    # 材料建议 (简单示例)
    if part.get("constraints", {}).get("load_level") == "medium" and part.get("material") == "45#":
        hits.append(
            RuleHit(
                "MAT-REC-001",
                "low",
                "当前 45# 可用，但若需要更高淬透性可考虑 40Cr。",
                "按强度余量和热处理成本比较 45# 与 40Cr。",
            )
        )

    return hits


def recommend_process(part: dict[str, Any], hits: list[RuleHit]) -> list[str]:
    steps = [
        "下料（锯切/棒料）",
        "粗加工（铣/钻）",
        "热处理（按需要）",
        "半精加工",
        "精加工（关键孔与基准面）",
        "去毛刺与清洗",
        "终检（尺寸+形位）",
    ]

    if any(h.rule_id == "DFM-HOLE-001" for h in hits):
        steps.insert(2, "深孔专用工序（分步钻削或枪钻）")
    return steps


def calc_score(hits: list[RuleHit]) -> tuple[int, str]:
    score = 100
    penalty = {"high": 18, "medium": 8, "low": 3}
    for h in hits:
        score -= penalty.get(h.severity, 0)
    score = max(score, 0)
    level = "A" if score >= 85 else "B" if score >= 70 else "C"
    return score, level


def render_report(part: dict[str, Any], hits: list[RuleHit], process_steps: list[str], score: int, level: str) -> str:
    lines = [
        f"# 零件审核最小闭环报告 - {part['part_id']}",
        "",
        "## 1) 审核结论",
        f"- 综合评分：**{score} / 100**",
        f"- 等级：**{level}**",
        f"- 规则命中数：**{len(hits)}**",
        "",
        "## 2) 风险与建议",
    ]
    if not hits:
        lines.append("- 无风险命中。")
    for i, h in enumerate(hits, start=1):
        lines.extend(
            [
                f"{i}. `{h.rule_id}` [{h.severity}] {h.message}",
                f"   - 建议：{h.suggestion}",
            ]
        )

    lines.extend(["", "## 3) 推荐工艺路径"])
    for idx, s in enumerate(process_steps, start=1):
        lines.append(f"{idx}. {s}")

    lines.extend([
        "",
        "## 4) 下一步",
        "- 工程师确认高风险项（2D/3D 一致性 + 深孔工艺可行性）。",
        "- 迭代修改后重新运行本脚本，观察评分改善。",
    ])

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", required=True)
    parser.add_argument("--drawing", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    part = load_json(Path(args.part))
    drawing = load_json(Path(args.drawing))
    hits = check_rules(part, drawing)
    process_steps = recommend_process(part, hits)
    score, level = calc_score(hits)
    report = render_report(part, hits, process_steps, score, level)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    print(f"[OK] report generated: {out_path}")
    print(f"[OK] score={score}, level={level}, hits={len(hits)}")


if __name__ == "__main__":
    main()
