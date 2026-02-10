#!/usr/bin/env python3
from __future__ import annotations

import argparse
import cgi
import hashlib
import hmac
import html
import json
import re
import secrets
import subprocess
import socket
import sqlite3
from urllib.parse import parse_qs
from datetime import datetime, timedelta, timezone
from http import cookies
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

try:
    from min_loop import render_markdown, rule_dfm, rule_iso273_hole, rule_iso2768_linear, to_result
except ModuleNotFoundError:
    from mvp.min_loop import render_markdown, rule_dfm, rule_iso273_hole, rule_iso2768_linear, to_result

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEFAULT_PROFILE = Path("mvp/standards/iso_profile_public.json")
DB_PATH = Path("mvp/data/app.db")
SESSION_DAYS = 7
SECRET = "change-this-secret"

CSS = """
body { font-family: Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif; background:#f3f4f6; margin:0; padding:24px; }
.container { max-width: 980px; margin:0 auto; }
.card { background:#fff; border-radius:10px; padding:16px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
.error { border-left:4px solid #dc2626; }
.tip { border-left:4px solid #2563eb; }
.ok { border-left:4px solid #16a34a; }
form { display:grid; gap:10px; }
button { width:220px; padding:10px; border:none; border-radius:8px; background:#2563eb; color:#fff; cursor:pointer; }
input { padding:10px; border-radius:8px; border:1px solid #d1d5db; }
pre { white-space: pre-wrap; background:#f9fafb; padding:10px; border-radius:8px; overflow:auto; }
code { font-size: 0.9em; }
a { color:#2563eb; }
.topbar { display:flex; justify-content:space-between; align-items:center; gap:10px; }
.inline { display:flex; gap:10px; align-items:center; }
.inline form { display:inline; }
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()


def _hash_password(password: str) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), SECRET.encode("utf-8"), 120_000)
    return digest.hex()


def _verify_password(password: str, hashed: str) -> bool:
    return hmac.compare_digest(_hash_password(password), hashed)


def _hash_token(token: str) -> str:
    return hashlib.sha256((token + SECRET).encode("utf-8")).hexdigest()


def _create_user(email: str, password: str) -> tuple[bool, str]:
    _init_db()
    if "@" not in email or len(email) < 5:
        return False, "邮箱格式不正确"
    if len(password) < 6:
        return False, "密码至少 6 位"
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO users(email, password_hash, created_at) VALUES(?,?,?)",
                (email.lower().strip(), _hash_password(password), _utc_now().isoformat()),
            )
            conn.commit()
        return True, "注册成功，请登录"
    except sqlite3.IntegrityError:
        return False, "该邮箱已注册"


def _create_session(email: str, password: str) -> tuple[bool, str, str | None]:
    _init_db()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT id, password_hash FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
        if not row or not _verify_password(password, row[1]):
            return False, "邮箱或密码错误", None
        token = secrets.token_urlsafe(32)
        token_hash = _hash_token(token)
        expires_at = (_utc_now() + timedelta(days=SESSION_DAYS)).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO sessions(token_hash, user_id, expires_at, created_at) VALUES(?,?,?,?)",
            (token_hash, row[0], expires_at, _utc_now().isoformat()),
        )
        conn.commit()
        return True, "登录成功", token


def _find_user_by_token(raw_cookie: str | None) -> dict[str, Any] | None:
    _init_db()
    if not raw_cookie:
        return None
    ck = cookies.SimpleCookie()
    ck.load(raw_cookie)
    morsel = ck.get("session_token")
    if not morsel:
        return None
    token_hash = _hash_token(morsel.value)
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT users.id, users.email, sessions.expires_at
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash=?
            """,
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row[2]) < _utc_now():
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
            conn.commit()
            return None
        return {"id": row[0], "email": row[1]}


def _clear_session(raw_cookie: str | None) -> None:
    _init_db()
    if not raw_cookie:
        return
    ck = cookies.SimpleCookie()
    ck.load(raw_cookie)
    morsel = ck.get("session_token")
    if morsel:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(morsel.value),))
            conn.commit()


def _load_json_bytes(raw: bytes) -> dict[str, Any]:
    if not raw:
        raise ValueError("上传文件为空")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"JSON 解析失败: {exc}") from exc


def _parse_dxf_pairs(text: str) -> list[tuple[str, str]]:
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    pairs: list[tuple[str, str]] = []
    i = 0
    while i + 1 < len(lines):
        pairs.append((lines[i].strip(), lines[i + 1].strip()))
        i += 2
    return pairs


def _extract_dims_from_text(text: str) -> list[dict[str, Any]]:
    dims: list[dict[str, Any]] = []
    idx = 1
    for line in text.splitlines():
        for m in re.finditer(r"(?<![A-Za-z0-9])(\d+(?:\.\d+)?)\s*(?:±\s*(\d+(?:\.\d+)?))?", line):
            nominal = float(m.group(1))
            if nominal <= 0:
                continue
            dim: dict[str, Any] = {"id": f"TXT_DIM_{idx}", "nominal_mm": nominal}
            if m.group(2):
                dim["explicit_tolerance_mm"] = float(m.group(2))
            dims.append(dim)
            idx += 1
    return dims


def parse_dxf_to_drawing(filename: str, raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="ignore")
    pairs = _parse_dxf_pairs(text)
    holes: list[dict[str, Any]] = []
    linear_dims: list[dict[str, Any]] = []
    text_chunks: list[str] = []

    i = 0
    while i < len(pairs):
        code, value = pairs[i]
        if code == "0" and value == "CIRCLE":
            handle = f"DXF_H{len(holes)+1}"
            radius = None
            j = i + 1
            while j < len(pairs):
                c, v = pairs[j]
                if c == "0":
                    break
                if c == "5":
                    handle = f"DXF_{v}"
                elif c == "40":
                    try:
                        radius = float(v)
                    except ValueError:
                        pass
                j += 1
            if radius and radius > 0:
                holes.append({"id": handle, "diameter_mm": round(radius * 2.0, 4)})
            i = j
            continue

        if code == "0" and value in {"TEXT", "MTEXT"}:
            j = i + 1
            while j < len(pairs):
                c, v = pairs[j]
                if c == "0":
                    break
                if c in {"1", "3"} and v:
                    text_chunks.append(v)
                j += 1
            i = j
            continue

        i += 1

    linear_dims.extend(_extract_dims_from_text("\n".join(text_chunks)))
    if not holes and not linear_dims:
        raise ValueError("DXF 中未提取到可用孔/尺寸信息；请改用结构化 JSON")

    return {
        "drawing_id": Path(filename).name,
        "holes": holes,
        "linear_dims": linear_dims,
        "standard_notes": {"general_tolerance_standard": "ISO 2768-1", "general_tolerance_class": "m"},
    }


def _load_drawing_from_upload(filename: str, raw: bytes) -> dict[str, Any]:
    ext = Path(filename or "").suffix.lower()
    if ext == ".json" or not ext:
        return _load_json_bytes(raw)
    if ext == ".dxf":
        return parse_dxf_to_drawing(filename, raw)
    raise ValueError("仅支持 JSON 或 DXF（PDF 请走下方‘二维 PDF 分析’）")




def parse_pdf_to_drawing(filename: str, raw: bytes) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=raw,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("未安装 pdftotext（poppler），无法解析 PDF；请先安装或改传 DXF/JSON") from exc

    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", errors="ignore").strip()
        raise ValueError(f"PDF 解析失败: {msg or 'pdftotext 执行失败'}")

    text = proc.stdout.decode("utf-8", errors="ignore")
    linear_dims = _extract_dims_from_text(text)
    if not linear_dims:
        raise ValueError("PDF 中未提取到可用尺寸文本；建议先转 DXF 或结构化 JSON")

    return {
        "drawing_id": Path(filename).name,
        "holes": [],
        "linear_dims": linear_dims,
        "standard_notes": {"general_tolerance_standard": "ISO 2768-1", "general_tolerance_class": "m"},
    }


def _build_part_from_drawing(drawing: dict[str, Any]) -> dict[str, Any]:
    holes = []
    for h in drawing.get("holes", []):
        d = float(h.get("diameter_mm", 0) or 0)
        if d <= 0:
            continue
        holes.append({"id": str(h.get("id", f"H{len(holes)+1}")), "diameter_mm": d, "depth_mm": round(d * 2.0, 3)})

    linear_dims = []
    for d2d in drawing.get("linear_dims", []):
        nominal = d2d.get("nominal_mm")
        if nominal is None:
            continue
        linear_dims.append({"id": str(d2d.get("id", f"D{len(linear_dims)+1}")), "value_mm": float(nominal)})

    return {
        "part_id": drawing.get("drawing_id", "DRAWING_ONLY_REVIEW"),
        "geometry": {"holes": holes, "linear_dims": linear_dims, "min_wall_thickness_mm": 3.0},
    }


def _auth_page(title: str, action: str, button: str, msg: str = "") -> str:
    msg_html = f'<section class="card tip">{html.escape(msg)}</section>' if msg else ""
    alt = (
        '<p>已有账号？<a href="/login">去登录</a></p>'
        if action == "/register"
        else '<p>还没账号？<a href="/register">去注册</a></p>'
    )
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{CSS}</style></head>
<body><main class='container'>
<section class='card'><h1>{html.escape(title)}</h1>
<form method='post' action='{action}'>
<label>邮箱</label><input type='email' name='email' required placeholder='you@example.com'>
<label>密码（至少6位）</label><input type='password' name='password' required minlength='6'>
<button type='submit'>{button}</button></form>{alt}</section>{msg_html}</main></body></html>"""


def _dashboard_page(
    user_email: str,
    errors: list[str] | None = None,
    success_msg: str = "",
    result: dict[str, Any] | None = None,
    report_md: str = "",
    converted_drawing: dict[str, Any] | None = None,
) -> str:
    err_html = ""
    if errors:
        items = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
        err_html = f'<section class="card error"><h2>输入错误</h2><ul>{items}</ul></section>'

    ok_html = f'<section class="card ok">{html.escape(success_msg)}</section>' if success_msg else ""

    convert_html = ""
    if converted_drawing:
        payload = html.escape(json.dumps(converted_drawing, ensure_ascii=False, indent=2))
        convert_html = f"<section class='card'><h2>DXF 转 JSON 结果</h2><pre>{payload}</pre></section>"

    result_html = ""
    if result:
        hits = result.get("hits", [])
        hits_html = "<p>未命中问题。</p>"
        if hits:
            items = []
            for h in hits:
                items.append(
                    "<li>"
                    f"<p><code>{html.escape(h['rule_id'])}</code> [{html.escape(h['severity'])}] ({html.escape(h['clause'])}) {html.escape(h['message'])}</p>"
                    f"<p><strong>建议：</strong>{html.escape(h['suggestion'])}</p>"
                    f"<p><strong>证据：</strong><code>{html.escape(json.dumps(h['evidence'], ensure_ascii=False))}</code></p>"
                    "</li>"
                )
            hits_html = "<ol>" + "".join(items) + "</ol>"
        process_html = "<ol>" + "".join(f"<li>{html.escape(s)}</li>" for s in result.get("recommended_process", [])) + "</ol>"
        result_html = f"""
<section class='card'><h2>评审总览</h2>
<p><strong>零件：</strong>{html.escape(str(result['part_id']))}</p>
<p><strong>评分：</strong>{result['summary']['score']} / 100</p>
<p><strong>等级：</strong>{html.escape(result['summary']['grade'])}</p>
<p><strong>结论：</strong>{html.escape(result['summary']['decision'])}</p>
<p><strong>命中：</strong>{result['summary']['hit_count']}（高风险 {result['summary']['high_risk_count']}）</p>
</section>
<section class='card'><h2>问题清单</h2>{hits_html}</section>
<section class='card'><h2>推荐工艺路径</h2>{process_html}</section>
<section class='card'><h2>完整报告（Markdown）</h2><pre>{html.escape(report_md)}</pre></section>
"""

    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>零件评审助手</title><style>{CSS}</style></head>
<body><main class='container'>
<section class='card topbar'>
<div><h1>零件评审助手（可分享 + 邮箱注册）</h1><p>2D图纸必填（JSON/DXF），3D可选。</p></div>
<div class='inline'><code>{html.escape(user_email)}</code><form method='post' action='/logout'><button type='submit'>退出登录</button></form></div>
</section>
<section class='card tip'><strong>格式说明：</strong>2D 支持 .json/.dxf；新增“二维 PDF 分析（实验）”板块。若做真实邮箱验证码邮件发送，建议使用你自己的域名邮箱。</section>

<section class='card'><h2>先转换：DXF → JSON（内置）</h2>
<form method='post' action='/convert-dxf' enctype='multipart/form-data'>
<label>上传 DXF</label><input type='file' name='dxf_file' accept='.dxf' required>
<button type='submit'>转换为 JSON</button></form></section>

<section class='card'><h2>评审分析（JSON/DXF）</h2>
<form method='post' action='/analyze' enctype='multipart/form-data'>
<label>2D图纸（必填，JSON或DXF）</label><input type='file' name='drawing_file' accept='application/json,.dxf' required>
<label>3D结构化输入（可选，JSON）</label><input type='file' name='part_file' accept='application/json'>
<label>标准配置（可选）</label><input type='file' name='profile_file' accept='application/json'>
<button type='submit'>开始分析</button></form></section>

<section class='card'><h2>二维 PDF 分析（实验）</h2>
<form method='post' action='/analyze-pdf' enctype='multipart/form-data'>
<label>2D PDF 图纸（必填）</label><input type='file' name='pdf_file' accept='application/pdf,.pdf' required>
<label>3D结构化输入（可选，JSON）</label><input type='file' name='part_file' accept='application/json'>
<label>标准配置（可选）</label><input type='file' name='profile_file' accept='application/json'>
<button type='submit'>PDF 开始分析</button></form>
<p><small>说明：该实验版通过文本提取做最小闭环，不适合复杂标注；建议优先 DXF/JSON。</small></p></section>

{ok_html}{err_html}{convert_html}{result_html}
</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send_html(self, content: str, status: int = 200, set_cookie: str | None = None) -> None:
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(encoded)

    def _get_user(self) -> dict[str, Any] | None:
        return _find_user_by_token(self.headers.get("Cookie"))

    def _redirect(self, location: str, set_cookie: str | None = None) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        user = self._get_user()
        if self.path == "/health":
            self._send_html("ok")
        elif self.path in {"/", "/dashboard"}:
            if not user:
                self._send_html(_auth_page("欢迎使用零件评审助手", "/login", "去登录", "请先登录，未注册请先创建账号。"))
            else:
                self._send_html(_dashboard_page(user["email"]))
        elif self.path == "/register":
            self._send_html(_auth_page("注册账号", "/register", "注册"))
        elif self.path == "/login":
            self._send_html(_auth_page("登录", "/login", "登录"))
        else:
            self._send_html("<h1>404</h1>", status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path in {"/register", "/login"}:
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length).decode("utf-8", errors="ignore")
            parsed = parse_qs(body, keep_blank_values=True)
            email = (parsed.get("email", [""])[0]).strip()
            password = parsed.get("password", [""])[0]

            if self.path == "/register":
                ok, msg = _create_user(email, password)
                self._send_html(_auth_page("注册账号", "/register", "注册", msg), status=200 if ok else 400)
                return

            ok, msg, token = _create_session(email, password)
            if not ok or not token:
                self._send_html(_auth_page("登录", "/login", "登录", msg), status=401)
                return
            cookie = f"session_token={token}; Path=/; HttpOnly; Max-Age={SESSION_DAYS*24*3600}; SameSite=Lax"
            self._redirect("/dashboard", set_cookie=cookie)
            return

        if self.path == "/logout":
            _clear_session(self.headers.get("Cookie"))
            self._redirect("/login", set_cookie="session_token=; Path=/; Max-Age=0")
            return

        user = self._get_user()
        if not user:
            self._redirect("/login")
            return

        if self.path not in {"/analyze", "/analyze-pdf", "/convert-dxf"}:
            self._send_html("<h1>404</h1>", status=404)
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")},
        )

        def get_file(name: str) -> tuple[str, bytes | None]:
            item = form[name] if name in form else None
            if item is None or not getattr(item, "file", None):
                return "", None
            return getattr(item, "filename", "") or "", item.file.read()

        if self.path == "/convert-dxf":
            errors: list[str] = []
            converted = None
            filename, raw = get_file("dxf_file")
            try:
                if not raw:
                    raise ValueError("请上传 DXF 文件")
                if Path(filename).suffix.lower() != ".dxf":
                    raise ValueError("请上传 .dxf 文件")
                converted = parse_dxf_to_drawing(filename, raw)
            except ValueError as exc:
                errors.append(f"DXF 转换失败: {exc}")
            self._send_html(_dashboard_page(user["email"], errors=errors, converted_drawing=converted))
            return

        if self.path == "/analyze-pdf":
            errors: list[str] = []
            result: dict[str, Any] | None = None
            report_md = ""

            pdf_name, pdf_raw = get_file("pdf_file")
            _, part_raw = get_file("part_file")
            _, profile_raw = get_file("profile_file")

            part = drawing = profile = None
            try:
                if not pdf_raw:
                    raise ValueError("请上传 PDF 文件")
                if Path(pdf_name).suffix.lower() != ".pdf":
                    raise ValueError("请上传 .pdf 文件")
                drawing = parse_pdf_to_drawing(pdf_name, pdf_raw)
            except ValueError as exc:
                errors.append(f"PDF 解析错误: {exc}")

            try:
                profile = _load_json_bytes(profile_raw) if profile_raw else json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
            except (ValueError, FileNotFoundError) as exc:
                errors.append(f"标准配置错误: {exc}")

            if part_raw:
                try:
                    part = _load_json_bytes(part_raw)
                except ValueError as exc:
                    errors.append(f"3D 输入错误: {exc}")
            elif drawing:
                part = _build_part_from_drawing(drawing)

            if part and drawing and profile:
                hits = []
                hits.extend(rule_dfm(part, profile))
                hits.extend(rule_iso273_hole(part, drawing, profile))
                hits.extend(rule_iso2768_linear(part, drawing, profile))
                result = to_result(part, drawing, profile, hits)
                report_md = render_markdown(result)

            self._send_html(_dashboard_page(user["email"], errors=errors, result=result, report_md=report_md))
            return

        errors: list[str] = []
        result: dict[str, Any] | None = None
        report_md = ""

        _, part_raw = get_file("part_file")
        drawing_name, drawing_raw = get_file("drawing_file")
        _, profile_raw = get_file("profile_file")

        part = drawing = profile = None
        try:
            if not drawing_raw:
                raise ValueError("请上传 2D 图纸文件")
            drawing = _load_drawing_from_upload(drawing_name, drawing_raw)
        except ValueError as exc:
            errors.append(f"2D 输入错误: {exc}")

        try:
            profile = _load_json_bytes(profile_raw) if profile_raw else json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
        except (ValueError, FileNotFoundError) as exc:
            errors.append(f"标准配置错误: {exc}")

        if part_raw:
            try:
                part = _load_json_bytes(part_raw)
            except ValueError as exc:
                errors.append(f"3D 输入错误: {exc}")
        elif drawing:
            part = _build_part_from_drawing(drawing)

        if part and drawing and profile:
            hits = []
            hits.extend(rule_dfm(part, profile))
            hits.extend(rule_iso273_hole(part, drawing, profile))
            hits.extend(rule_iso2768_linear(part, drawing, profile))
            result = to_result(part, drawing, profile, hits)
            report_md = render_markdown(result)

        self._send_html(_dashboard_page(user["email"], errors=errors, result=result, report_md=report_md))


def _guess_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="零件评审助手 Web")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--secret", default="change-this-secret", help="会话与密码哈希盐（生产环境请设置强随机字符串）")
    args = parser.parse_args()

    globals()["SECRET"] = args.secret

    _init_db()

    try:
        server = HTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        raise SystemExit(
            f"[ERROR] 端口启动失败: {exc}\n"
            f"建议改端口重试: python3 mvp/web_app.py --host {args.host} --port 8010"
        )

    lan_ip = _guess_lan_ip()
    print("[OK] web app running")
    print(f" - local: http://localhost:{args.port}")
    if args.host == "0.0.0.0":
        print(f" - lan:   http://{lan_ip}:{args.port}")
    print("[TIP] 已启用邮箱注册/登录；2D 支持 JSON/DXF")
    server.serve_forever()


if __name__ == "__main__":
    main()
