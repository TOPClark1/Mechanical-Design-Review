# 最小闭环真实运行说明（2D优先版）

现在不要求 3D 模型：你可以直接上传 **2D 图纸** 做评审。

## 1) 当前支持的输入

### 必填：2D 图纸
- `.json`（结构化图纸）
- `.dxf`（经典 CAD 交换格式，已内置最小转换能力）

### 可选：3D
- `.json`（如果上传，会做 2D/3D 一致性校核）
- 不上传也能跑：系统会基于 2D 自动构造最小 3D 代理数据

### 暂不直接支持
- `.dwg` / `.pdf`（建议先转 DXF 或结构化 JSON）

---

## 2) 网页运行

```bash
python3 mvp/web_app.py
```

浏览器访问：
- `http://localhost:8000`
- `http://127.0.0.1:8000`

---

## 3) 内置工具：DXF 转 JSON

### 方式 A：网页内转换（推荐）
首页有“**先转换：DXF → JSON（内置）**”表单，上传 DXF 后页面会直接显示结构化 JSON，可复制保存。

### 方式 B：命令行转换
```bash
python3 mvp/dxf_to_json.py \
  --in-dxf mvp/examples/public_drawing_2d_minimal.dxf \
  --out-json mvp/output/converted_from_dxf.json
```

---

## 4) 网页评审（2D-only）

在“评审分析”表单中：
1. 上传 2D（JSON 或 DXF）
2. 3D 可不传
3. 点击“开始分析”

页面会输出：
- 评分与等级
- 问题清单
- 推荐工艺路径
- Markdown 全报告

---

## 5) 示例输入

- 2D JSON：`mvp/examples/public_drawing_2d.json`
- 2D DXF：`mvp/examples/public_drawing_2d_minimal.dxf`
- 3D JSON（可选）：`mvp/examples/public_part_3d.json`

---

## 6) 常见问题

### Q: 没办法看到结果？
- 确认访问的是：`localhost:8000`（不是 `mvp`）
- 上传后页面下方会显示“评审总览 / 问题清单”
- 若只想先确认 DXF 能否读取，先用“DXF → JSON”转换表单

### Q: 一定要 JSON 吗？
不是。现在网页支持直接上传 DXF，也有内置 DXF→JSON 工具。
