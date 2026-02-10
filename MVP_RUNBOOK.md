# 最小闭环真实运行说明（可分享 + 邮箱注册）

现在支持：**可分享访问 + 邮箱注册登录 + 2D 图纸评审（JSON/DXF）**。

## 1) 你问的核心问题：邮箱注册需要域名吗？

**不一定需要。**

- 如果你只需要“用户用邮箱+密码注册登录”（不发送验证码邮件）：**不需要域名**，本系统已支持。
- 如果你后续要“发送验证码/找回密码邮件”：建议用你自己的域名邮箱（或第三方邮件服务），这样送达率更稳。

---

## 2) 本地启动

```bash
python3 mvp/web_app.py --host 0.0.0.0 --port 8000 --secret "replace-with-a-strong-secret"
```

访问：
- 本机：`http://localhost:8000`
- 局域网：`http://你的IP:8000`

> 首次启动会自动创建 SQLite 数据库：`mvp/data/app.db`

---

## 3) 注册与登录

1. 打开首页，先注册账号（邮箱+密码）
2. 登录后进入评审工作台
3. 在工作台内：
   - 可先做 `DXF -> JSON` 转换
   - 再做 2D 图纸评审（3D 可选）

---

## 4) 支持的图纸格式

### 必填：2D
- `.json`
- `.dxf`

### 可选：3D
- `.json`

### 暂不直接支持
- `.dwg` / `.pdf`（先转 DXF 或 JSON）

---

## 5) 内置 DXF 转 JSON

### 网页方式（推荐）
登录后使用“先转换：DXF → JSON（内置）”表单。

### 命令行方式
```bash
python3 mvp/dxf_to_json.py \
  --in-dxf mvp/examples/public_drawing_2d_minimal.dxf \
  --out-json mvp/output/converted_from_dxf.json
```

---

## 6) 分享给别人用

你可以把服务部署到云主机，并开放 8000 端口；别人用 `http://服务器IP:8000` 访问即可。

如果你暂时没有域名，也可以先用 IP 分享。后续需要 HTTPS/正式邮件服务时，再加域名。
