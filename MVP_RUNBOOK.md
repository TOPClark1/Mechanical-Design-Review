# 最小闭环运行说明（零件审核 + 工艺设计）

## 目标
在不接入复杂 CAD/OCR 模型的前提下，先验证“输入→规则审查→工艺建议→报告输出”闭环可跑通。

## 文件说明
- `mvp/min_loop.py`：最小闭环执行脚本
- `mvp/examples/part_input.json`：3D特征抽取后的示例输入
- `mvp/examples/drawing_input.json`：2D图纸结构化后的示例输入
- `mvp/output/report.md`：输出报告

## 运行命令
```bash
python3 mvp/min_loop.py \
  --part mvp/examples/part_input.json \
  --drawing mvp/examples/drawing_input.json \
  --out mvp/output/report.md
```

## 当前最小规则集（可扩展）
- `DFM-HOLE-001`：孔深径比 > 8 告警
- `DFM-WALL-001`：最小壁厚 < 2.0mm 告警
- `DFM-FEATURE-001`：过多装饰倒角导致潜在冗余加工
- `CONSISTENCY-2D3D-001`：2D/3D 孔径不一致
- `MAT-REC-001`：材料替代建议（45# ↔ 40Cr）

## 如何扩展成真实项目
1. 用 OCCT/FreeCAD 产出真实 `PartFeatureGraph` 替换示例 JSON。
2. 用 PaddleOCR + 检测模型产出真实 `DrawingSpec` 替换示例 JSON。
3. 将规则从脚本内嵌迁移到外部 YAML/JSON 规则库。
4. 接入 OR-Tools 做工艺路线排序优化。
