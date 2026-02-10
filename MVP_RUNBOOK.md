# 最小闭环真实运行说明（2D优先版）

现在不要求 3D 模型：你可以直接上传 **2D 图纸** 做评审。

## 1) 当前支持的输入

### 必填：2D 图纸
- `.json`（结构化图纸）
- `.dxf`（经典 CAD 交换格式，当前实现了最小可用解析）

### 可选：3D
- `.json`（如果上传，会做 2D/3D 一致性校核）
- 不上传也能跑：系统会基于 2D 自动构造最小 3D 代理数据

### 暂不直接支持
- `.dwg` / `.pdf`（建议先转 DXF 或结构化 JSON）

---

## 2) 使用的公开规范
- **ISO 2768-1**：一般线性尺寸公差（示例采用 `class m`）
- **ISO 273**：公制螺栓间隙孔（示例采用 normal 系列）

规范配置：`mvp/standards/iso_profile_public.json`

---

## 3) 网页运行（推荐）

```bash
python3 mvp/web_app.py
```

浏览器访问：
- `http://localhost:8000`
- `http://127.0.0.1:8000`

> 如果你给同事演示：
> ```bash
> python3 mvp/web_app.py --host 0.0.0.0 --port 8000
> ```
> 然后同网段访问 `http://你的局域网IP:8000`。

---

## 4) 示例输入

- 2D JSON：`mvp/examples/public_drawing_2d.json`
- 2D DXF：`mvp/examples/public_drawing_2d_minimal.dxf`
- 3D JSON（可选）：`mvp/examples/public_part_3d.json`

---

## 5) CLI 跑法（仍可用）

如果你要走纯 JSON 的命令行模式：

```bash
python3 mvp/min_loop.py \
  --part mvp/examples/public_part_3d.json \
  --drawing mvp/examples/public_drawing_2d.json \
  --profile mvp/standards/iso_profile_public.json \
  --out-md mvp/output/public_review_report.md \
  --out-json mvp/output/public_review_result.json
```

---

## 6) 常见问题

### Q: 一定要 JSON 吗？
不是。网页已支持直接上传 `DXF`。JSON 只是最稳定的结构化接口。

### Q: 我现在不想处理 3D，可以吗？
可以。3D 输入是可选项，不上传也会输出评审建议。

### Q: 访问报 `DNS_PROBE_FINISHED_NXDOMAIN`？
你输入了无效主机名（例如 `mvp`）。请使用 `localhost` / `127.0.0.1` / 局域网 IP。

---

## 7) 页面输出
- 评分与等级
- 问题清单（规则、严重度、建议、证据）
- 推荐工艺路径
- Markdown 全报告
