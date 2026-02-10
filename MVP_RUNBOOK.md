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

启动后会打印访问地址，默认请用：
- `http://localhost:8000`
- `http://127.0.0.1:8000`

如果你要让同网段其它机器访问：
```bash
python3 mvp/web_app.py --host 0.0.0.0 --port 8000
```
然后在其它机器访问 `http://你的局域网IP:8000`。

---

## 5) 你这个报错（DNS_PROBE_FINISHED_NXDOMAIN）怎么处理

你截图里是访问了 `mvp`，这是一个不存在的域名，所以浏览器报 DNS 错误。

### 正确做法
1. 先在项目目录启动服务：
   ```bash
   python3 mvp/web_app.py
   ```
2. 浏览器输入：
   - `http://localhost:8000`
   - 或 `http://127.0.0.1:8000`
3. **不要输入 `mvp`**。

### 若仍打不开
- 检查服务是否启动成功（终端应显示 `[OK] web app running`）。
- 若提示端口占用，换端口启动：
  ```bash
  python3 mvp/web_app.py --port 8010
  ```
  然后访问 `http://localhost:8010`。
- 若跨机器访问，确认防火墙已放行该端口。

---

## 6) 页面上传后会显示什么
- 评分与等级
- 问题清单（规则、严重度、建议、证据）
- 推荐工艺路径
- 完整 Markdown 报告

---

## 7) 当前规则
- `DFM-HOLE-001`：孔深径比
- `DFM-WALL-001`：最小壁厚
- `ISO273-HOLE-001`：孔径是否符合 ISO 273 normal
- `CONSISTENCY-2D3D-001`：2D/3D 孔径一致性
- `ISO2768-LIN-001`：线性尺寸按 ISO 2768-1 class m 超差检查
