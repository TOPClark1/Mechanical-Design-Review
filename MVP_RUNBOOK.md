# 最小闭环真实运行说明（公开规范版 + 网页）

你可以把公开零件图纸（结构化 JSON）上传到网页，分析后直接在页面显示评审建议。

## 1) 使用的公开规范
- **ISO 2768-1**：一般线性尺寸公差（示例采用 `class m`）
- **ISO 273**：公制螺栓间隙孔（示例采用 normal 系列）

规范配置：`mvp/standards/iso_profile_public.json`

---

## 2) 输入格式

### 3D 输入 JSON
示例：`mvp/examples/public_part_3d.json`

### 2D 图纸输入 JSON
示例：`mvp/examples/public_drawing_2d.json`

> 当前 MVP 先接收结构化 JSON。你后续可在前端前面增加 OCR/图纸解析服务，将 PDF/DWG 转为此结构。

---

## 3) CLI 跑法（可选）

```bash
python3 mvp/min_loop.py \
  --part mvp/examples/public_part_3d.json \
  --drawing mvp/examples/public_drawing_2d.json \
  --profile mvp/standards/iso_profile_public.json \
  --out-md mvp/output/public_review_report.md \
  --out-json mvp/output/public_review_result.json
```

---

## 4) 网页运行（推荐）

```bash
python3 mvp/web_app.py
```

启动后访问：
- `http://localhost:8000`

在页面中上传：
1. 3D 结构化 JSON（必填）
2. 2D 结构化 JSON（必填）
3. 标准配置 JSON（可选，不传则用内置 ISO 配置）

点击“开始分析”后，网页会直接显示：
- 评分与等级
- 问题清单（规则、严重度、建议、证据）
- 推荐工艺路径
- 完整 Markdown 报告

---

## 5) 当前规则
- `DFM-HOLE-001`：孔深径比
- `DFM-WALL-001`：最小壁厚
- `ISO273-HOLE-001`：孔径是否符合 ISO 273 normal
- `CONSISTENCY-2D3D-001`：2D/3D 孔径一致性
- `ISO2768-LIN-001`：线性尺寸按 ISO 2768-1 class m 超差检查
