#!/usr/bin/env python3
from __future__ import annotations

import argparse
import cgi
import html
import json
import socket
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


CSS = """
body { font-family: Arial, 'PingFang SC', 'Microsoft YaHei', sans-serif; background:#f3f4f6; margin:0; padding:24px; }
.container { max-width: 920px; margin:0 auto; }
.card { background:#fff; border-radius:10px; padding:16px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,.08); }
.error { border-left:4px solid #dc2626; }
.tip { border-left:4px solid #2563eb; }
form { display:grid; gap:10px; }
button { width:140px; padding:10px; border:none; border-radius:8px; background:#2563eb; color:#fff; cursor:pointer; }
pre { white-space: pre-wrap; background:#f9fafb; padding:10px; border-radius:8px; }
code { font-size: 0.9em; }
"""


def _load_json_bytes(raw: bytes) -> dict[str, Any]:
    if not raw:
        raise ValueError("上传文件为空")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"JSON 解析失败: {exc}") from exc


def _render_page(errors: list[str] | None = None, result: dict[str, Any] | None = None, report_md: str = "") -> str:
    err_html = ""
    if errors:
        items = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
        err_html = f'<section class="card error"><h2>输入错误</h2><ul>{items}</ul></section>'

    result_html = ""
    if result:
        hits = result.get("hits", [])
        hits_html = "<p>未命中问题。</p>"
        if hits:
            lines = []
            for h in hits:
                lines.append(
                    "<li>"
                    f"<p><code>{html.escape(h['rule_id'])}</code> [{html.escape(h['severity'])}] ({html.escape(h['clause'])}) {html.escape(h['message'])}</p>"
                    f"<p><strong>建议：</strong>{html.escape(h['suggestion'])}</p>"
                    f"<p><strong>证据：</strong><code>{html.escape(json.dumps(h['evidence'], ensure_ascii=False))}</code></p>"
                    "</li>"
                )
            hits_html = "<ol>" + "".join(lines) + "</ol>"

        process_html = "<ol>" + "".join(f"<li>{html.escape(s)}</li>" for s in result.get("recommended_process", [])) + "</ol>"

        result_html = f"""
<section class="card">
  <h2>评审总览</h2>
  <p><strong>零件：</strong>{html.escape(str(result['part_id']))}</p>
  <p><strong>评分：</strong>{result['summary']['score']} / 100</p>
  <p><strong>等级：</strong>{html.escape(result['summary']['grade'])}</p>
  <p><strong>结论：</strong>{html.escape(result['summary']['decision'])}</p>
  <p><strong>命中：</strong>{result['summary']['hit_count']}（高风险 {result['summary']['high_risk_count']}）</p>
</section>
<section class="card">
  <h2>问题清单</h2>
  {hits_html}
</section>
<section class="card">
  <h2>推荐工艺路径</h2>
  {process_html}
</section>
<section class="card">
  <h2>完整报告（Markdown）</h2>
  <pre>{html.escape(report_md)}</pre>
</section>
"""

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>零件评审助手（公开标准）</title><style>{CSS}</style></head>
<body><main class="container">
  <h1>零件评审助手（ISO 2768-1 / ISO 273）</h1>
  <p>上传 3D/2D 结构化图纸 JSON，分析后直接在网页显示评审建议。</p>
  <section class="card tip">
    <strong>访问方式：</strong>请用 <code>http://localhost:8000</code> 或 <code>http://127.0.0.1:8000</code>，<b>不要输入 mvp 这种主机名</b>。
  </section>
  <section class="card">
    <form action="/analyze" method="post" enctype="multipart/form-data">
      <label>3D 结构化输入（必填）</label>
      <input type="file" name="part_file" accept="application/json" required>
      <label>2D 图纸结构化输入（必填）</label>
      <input type="file" name="drawing_file" accept="application/json" required>
      <label>标准配置（可选，不上传则使用内置 ISO 配置）</label>
      <input type="file" name="profile_file" accept="application/json">
      <button type="submit">开始分析</button>
    </form>
  </section>
  {err_html}
  {result_html}
</main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send_html(self, content: str, status: int = 200) -> None:
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            self._send_html(_render_page())
        elif self.path == "/health":
            self._send_html("ok")
        else:
            self._send_html("<h1>404</h1>", status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/analyze":
            self._send_html("<h1>404</h1>", status=404)
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers.get("Content-Type", "")},
        )

        errors: list[str] = []
        result: dict[str, Any] | None = None
        report_md = ""

        def get_file_bytes(name: str) -> bytes | None:
            item = form[name] if name in form else None
            if item is None or not getattr(item, "file", None):
                return None
            return item.file.read()

        part_raw = get_file_bytes("part_file")
        drawing_raw = get_file_bytes("drawing_file")
        profile_raw = get_file_bytes("profile_file")

        part = drawing = profile = None
        try:
            part = _load_json_bytes(part_raw or b"")
        except ValueError as exc:
            errors.append(f"3D 输入错误: {exc}")

        try:
            drawing = _load_json_bytes(drawing_raw or b"")
        except ValueError as exc:
            errors.append(f"2D 输入错误: {exc}")

        try:
            if profile_raw:
                profile = _load_json_bytes(profile_raw)
            else:
                profile = json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
        except (ValueError, FileNotFoundError) as exc:
            errors.append(f"标准配置错误: {exc}")

        if part and drawing and profile:
            hits = []
            hits.extend(rule_dfm(part, profile))
            hits.extend(rule_iso273_hole(part, drawing, profile))
            hits.extend(rule_iso2768_linear(part, drawing, profile))
            result = to_result(part, drawing, profile, hits)
            report_md = render_markdown(result)

        self._send_html(_render_page(errors=errors, result=result, report_md=report_md))


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
    args = parser.parse_args()

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
    print("[TIP] 浏览器不要输入 mvp 作为网址，使用 localhost 或 127.0.0.1")
    server.serve_forever()


if __name__ == "__main__":
    main()
