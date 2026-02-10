#!/usr/bin/env python3
"""公开标准驱动的零件评审最小闭环

输入：
- 3D 结构化数据（由 CAD 特征提取或人工整理）
- 2D 图纸结构化数据（由 OCR+后处理或人工整理）
- 公开标准配置（ISO 2768-1 + ISO 273）

输出：
- Markdown 评审报告
- JSON 评审结果（便于系统集成）
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class RuleHit:
    rule_id: str
    severity: str
    clause: str
    message: str
    suggestion: str
    evidence: dict[str, Any]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_iso_2768_m_tol(nominal_mm: float, profile: dict[str, Any]) -> float:
    table = profile["iso_2768_m_linear_tolerance_mm"]
    for row in table:
        if nominal_mm > row["range_gt"] and nominal_mm <= row["range_le"]:
            return float(row["tol"])
    return float(table[-1]["tol"])


def rule_dfm(part: dict[str, Any], profile: dict[str, Any]) -> list[RuleHit]:
    hits: list[RuleHit] = []
    geo = part.get("geometry", {})
    t = profile["dfm_thresholds"]

    for hole in geo.get("holes", []):
        d = float(hole["diameter_mm"])
        depth = float(hole["depth_mm"])
        ratio = depth / d if d > 0 else 0
        if ratio > t["hole_depth_ratio_max"]:
            hits.append(
                RuleHit(
                    rule_id="DFM-HOLE-001",
                    severity="high",
                    clause="Internal DFM baseline",
                    message=f"孔 {hole['id']} 深径比 {ratio:.2f} 超过阈值 {t['hole_depth_ratio_max']}",
                    suggestion="改通孔、增大孔径、分步钻削或改枪钻工艺。",
                    evidence={"hole_id": hole["id"], "diameter_mm": d, "depth_mm": depth, "ratio": round(ratio, 3)},
                )
            )

    min_wall = float(geo.get("min_wall_thickness_mm", 999))
    if min_wall < float(t["min_wall_thickness_mm"]):
        hits.append(
            RuleHit(
                rule_id="DFM-WALL-001",
                severity="high",
                clause="Internal DFM baseline",
                message=f"最小壁厚 {min_wall}mm 低于阈值 {t['min_wall_thickness_mm']}mm",
                suggestion="提高薄壁厚度或增加工艺筋，减少装夹变形风险。",
                evidence={"min_wall_thickness_mm": min_wall},
            )
        )

    return hits


def rule_iso273_hole(part: dict[str, Any], drawing: dict[str, Any], profile: dict[str, Any]) -> list[RuleHit]:
    hits: list[RuleHit] = []
    clr = profile["iso_273_normal_clearance_mm"]

    model_holes = {h["id"]: h for h in part.get("geometry", {}).get("holes", [])}
    drawing_holes = drawing.get("holes", [])

    for h2d in drawing_holes:
        hid = h2d["id"]
        fastener = h2d.get("intended_fastener")
        if fastener and fastener in clr:
            iso_nom = float(clr[fastener])
            d2d = float(h2d["diameter_mm"])
            if abs(d2d - iso_nom) > 1e-6:
                hits.append(
                    RuleHit(
                        rule_id="ISO273-HOLE-001",
                        severity="medium",
                        clause="ISO 273 normal clearance",
                        message=f"图纸孔 {hid} 标注 {d2d}mm 与 {fastener} 常用间隙孔 {iso_nom}mm 不一致",
                        suggestion="确认是否为过渡/紧配设计；若无特殊需求，建议采用 ISO 273 常用值。",
                        evidence={"hole_id": hid, "fastener": fastener, "drawing_diameter_mm": d2d, "iso273_nominal_mm": iso_nom},
                    )
                )

        if hid in model_holes:
            d3d = float(model_holes[hid]["diameter_mm"])
            d2d = float(h2d["diameter_mm"])
            if abs(d2d - d3d) > 1e-6:
                hits.append(
                    RuleHit(
                        rule_id="CONSISTENCY-2D3D-001",
                        severity="high",
                        clause="2D/3D consistency",
                        message=f"孔 {hid} 2D={d2d}mm 与 3D={d3d}mm 不一致",
                        suggestion="核对版本并统一 2D/3D 数据源；优先冻结单一主数据。",
                        evidence={"hole_id": hid, "drawing_diameter_mm": d2d, "model_diameter_mm": d3d},
                    )
                )

    return hits


def rule_iso2768_linear(part: dict[str, Any], drawing: dict[str, Any], profile: dict[str, Any]) -> list[RuleHit]:
    hits: list[RuleHit] = []
    model_dims = {d["id"]: float(d["value_mm"]) for d in part.get("geometry", {}).get("linear_dims", [])}

    for d2d in drawing.get("linear_dims", []):
        dim_id = d2d["id"]
        nominal = float(d2d["nominal_mm"])
        tol = float(d2d.get("explicit_tolerance_mm", get_iso_2768_m_tol(nominal, profile)))

        if dim_id in model_dims:
            model_v = model_dims[dim_id]
            delta = abs(model_v - nominal)
            if delta > tol:
                hits.append(
                    RuleHit(
                        rule_id="ISO2768-LIN-001",
                        severity="high",
                        clause="ISO 2768-1 class m",
                        message=f"尺寸 {dim_id} 模型值 {model_v}mm 与图纸名义值 {nominal}mm 偏差 {delta:.3f}mm 超差(±{tol}mm)",
                        suggestion="修订图纸或修订模型，保持单一尺寸主数据并重新发版。",
                        evidence={"dim_id": dim_id, "model_mm": model_v, "drawing_nominal_mm": nominal, "delta_mm": round(delta, 4), "allowed_tol_mm": tol},
                    )
                )

    return hits


def recommend_process(hits: list[RuleHit]) -> list[str]:
    steps = [
        "下料",
        "粗加工（铣/钻）",
        "半精加工",
        "精加工（关键孔与基准）",
        "去毛刺与清洗",
        "终检（尺寸/形位/一致性）",
    ]
    if any(h.rule_id == "DFM-HOLE-001" for h in hits):
        steps.insert(2, "深孔专用工序（分步钻削/枪钻）")
    if any(h.rule_id == "CONSISTENCY-2D3D-001" for h in hits):
        steps.insert(0, "工程数据冻结（先统一2D/3D版本）")
    return steps


def calc_score(hits: list[RuleHit]) -> tuple[int, str]:
    score = 100
    penalty = {"high": 20, "medium": 8, "low": 3}
    for h in hits:
        score -= penalty.get(h.severity, 0)
    score = max(score, 0)
    grade = "A" if score >= 85 else "B" if score >= 70 else "C"
    return score, grade


def to_result(part: dict[str, Any], drawing: dict[str, Any], profile: dict[str, Any], hits: list[RuleHit]) -> dict[str, Any]:
    score, grade = calc_score(hits)
    process_steps = recommend_process(hits)
    high_count = sum(1 for h in hits if h.severity == "high")

    return {
        "part_id": part.get("part_id"),
        "profile": profile.get("profile_id"),
        "standards": profile.get("sources", []),
        "summary": {
            "score": score,
            "grade": grade,
            "hit_count": len(hits),
            "high_risk_count": high_count,
            "decision": "建议返修后再试制" if grade == "C" else "可试制",
        },
        "hits": [asdict(h) for h in hits],
        "recommended_process": process_steps,
        "input_refs": {
            "drawing_general_tolerance": drawing.get("standard_notes", {}).get("general_tolerance_standard"),
            "drawing_tolerance_class": drawing.get("standard_notes", {}).get("general_tolerance_class"),
        },
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# 零件评审报告（公开标准）- {result['part_id']}",
        "",
        "## 1. 结论总览",
        f"- 评分：**{result['summary']['score']} / 100**",
        f"- 等级：**{result['summary']['grade']}**",
        f"- 判定：**{result['summary']['decision']}**",
        f"- 风险命中：**{result['summary']['hit_count']}**（高风险 {result['summary']['high_risk_count']}）",
        "",
        "## 2. 采用规范",
    ]
    for s in result.get("standards", []):
        lines.append(f"- {s}")

    lines.extend(["", "## 3. 评审问题清单"])
    if not result["hits"]:
        lines.append("- 未命中问题。")
    else:
        for i, h in enumerate(result["hits"], 1):
            lines.append(f"{i}. `{h['rule_id']}` [{h['severity']}] ({h['clause']}) {h['message']}")
            lines.append(f"   - 建议：{h['suggestion']}")
            lines.append(f"   - 证据：`{json.dumps(h['evidence'], ensure_ascii=False)}`")

    lines.extend(["", "## 4. 推荐工艺路径"])
    for i, step in enumerate(result["recommended_process"], 1):
        lines.append(f"{i}. {step}")

    lines.extend([
        "",
        "## 5. 可执行下一步",
        "1. 先修复 2D/3D 冲突后再下发加工。",
        "2. 对所有孔按 ISO 273 目标系列复核一次（若无特殊配合要求）。",
        "3. 修订后再次运行评审脚本，比较评分变化。",
    ])

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", required=True, help="3D结构化输入 JSON")
    parser.add_argument("--drawing", required=True, help="2D结构化输入 JSON")
    parser.add_argument("--profile", required=True, help="标准配置 JSON")
    parser.add_argument("--out-md", required=True, help="输出 Markdown 报告")
    parser.add_argument("--out-json", required=True, help="输出 JSON 结果")
    args = parser.parse_args()

    part = load_json(Path(args.part))
    drawing = load_json(Path(args.drawing))
    profile = load_json(Path(args.profile))

    hits: list[RuleHit] = []
    hits.extend(rule_dfm(part, profile))
    hits.extend(rule_iso273_hole(part, drawing, profile))
    hits.extend(rule_iso2768_linear(part, drawing, profile))

    result = to_result(part, drawing, profile, hits)
    md = render_markdown(result)

    out_md = Path(args.out_md)
    out_json = Path(args.out_json)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    out_md.write_text(md, encoding="utf-8")
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] markdown report: {out_md}")
    print(f"[OK] json result: {out_json}")
    print(f"[OK] score={result['summary']['score']} grade={result['summary']['grade']} hits={result['summary']['hit_count']}")


if __name__ == "__main__":
    main()
