# 机械设计评审助手运行说明（GitHub + PDF）

现在支持：**可分享访问 + 邮箱注册登录 + 2D 图纸评审（JSON / DXF / PDF）**。

## 1) 你最关心的两个问题

### Q1: 我的初始文件是 PDF，必须支持吗？
支持。现在 2D 主分析入口已经支持 `.pdf` 上传。

### Q2: 代码在 GitHub 上，我怎么跑起来？
按下面 4 步走即可：克隆仓库 → 安装依赖 → 启动服务 → 浏览器访问。

---

## 2) 从 GitHub 拉代码

```bash
git clone <你的仓库地址>
cd Mechanical-Design-Review
```

---

## 3) 环境准备

### 必备
- Python 3.10+

### PDF 支持必备（必须安装）
本项目解析 PDF 依赖 `pdftotext`（poppler）：

```bash
# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y poppler-utils

# macOS
brew install poppler
```

---

## 4) 启动服务

```bash
python3 mvp/web_app.py --host 0.0.0.0 --port 8000 --secret "replace-with-a-strong-secret"
```

访问：
- 本机：`http://localhost:8000`
- 局域网：`http://你的IP:8000`

> 首次启动会自动创建 SQLite 数据库：`mvp/data/app.db`

---

## 5) 登录后怎么用

1. 先注册账号（邮箱+密码）
2. 登录进入评审工作台
3. 在“评审分析（JSON/DXF/PDF）”里上传 2D 图纸：
   - 支持 `.json` / `.dxf` / `.pdf`
4. 可选再上传 3D `.json`
5. 点击“开始分析”查看评分、问题清单与工艺建议

---

## 6) 分享给别人使用

如果你部署在云服务器并放通 8000 端口，别人可以直接访问：

`http://服务器IP:8000`

没有域名也能先跑和分享；后续要 HTTPS 或邮件验证码再加域名。

---

## 7) 合并冲突自检（建议每次提交前）

```bash
./scripts/check_conflicts.sh
```

若输出 `[OK] No unresolved conflict markers found in tracked files.`，表示无冲突标记残留。
