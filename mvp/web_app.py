#!/usr/bin/env python3
from __future__ import annotations

import argparse
import cgi
import html
import json
import re
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
button { width:220px; padding:10px; border:none; border-radius:8px; background:#2563eb; color:#fff; cursor:pointer; }
pre { white-space: pre-wrap; background:#f9fafb; padding:10px; border-radius:8px; overflow:auto; }
code { font-size: 0.9em; }
a { color:#2563eb; }
"""


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
    raise ValueError("仅支持 JSON 或 DXF（当前不直接解析 PDF/DWG）")


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


def _render_page(
    errors: list[str] | None = None,
    result: dict[str, Any] | None = None,
    report_md: str = "",
    converted_drawing: dict[str, Any] | None = None,
) -> str:
    err_html = ""
    if errors:
        items = "".join(f"<li>{html.escape(e)}</li>" for e in errors)
        err_html = f'<section class="card error"><h2>输入错误</h2><ul>{items}</ul></section>'

    convert_html = ""
    if converted_drawing:
        payload = json.dumps(converted_drawing, ensure_ascii=False, indent=2)
        payload_esc = html.escape(payload)
        convert_html = f"""
<section class="card">
  <h2>DXF 转 JSON 结果</h2>
  <p>已成功提取结构化 2D 数据，你可以复制到本地保存为 <code>drawing.json</code>。</p>
  <pre>{payload_esc}</pre>
</section>
"""

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
<section class="card"><h2>评审总览</h2>
  <p><strong>零件：</strong>{html.escape(str(result['part_id']))}</p>
  <p><strong>评分：</strong>{result['summary']['score']} / 100</p>
  <p><strong>等级：</strong>{html.escape(result['summary']['grade'])}</p>
  <p><strong>结论：</strong>{html.escape(result['summary']['decision'])}</p>
  <p><strong>命中：</strong>{result['summary']['hit_count']}（高风险 {result['summary']['high_risk_count']}）</p>
</section>
<section class="card"><h2>问题清单</h2>{hits_html}</section>
<section class="card"><h2>推荐工艺路径</h2>{process_html}</section>
<section class="card"><h2>完整报告（Markdown）</h2><pre>{html.escape(report_md)}</pre></section>
"""

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>零件评审助手（公开标准）</title><style>{CSS}</style></head>
<body><main class="container">
  <h1>零件评审助手（ISO 2768-1 / ISO 273）</h1>
  <p>2D 图纸必填（JSON 或 DXF），3D 输入可选。</p>
  <section class="card tip"><strong>格式说明：</strong>2D 支持 <code>.json</code>/<code>.dxf</code>；<code>.dwg/.pdf</code> 请先转 DXF 或 JSON。</section>

  <section class="card">
    <h2>先转换：DXF → JSON（内置）</h2>
    <form action="/convert-dxf" method="post" enctype="multipart/form-data">
      <label>上传 DXF</label>
      <input type="file" name="dxf_file" accept=".dxf" required>
      <button type="submit">转换为 JSON</button>
    </form>
  </section>

  <section class="card">
    <h2>评审分析</h2>
    <form action="/analyze" method="post" enctype="multipart/form-data">
      <label>2D 图纸输入（必填，JSON 或 DXF）</label>
      <input type="file" name="drawing_file" accept="application/json,.dxf" required>
      <label>3D 结构化输入（可选，JSON）</label>
      <input type="file" name="part_file" accept="application/json">
      <label>标准配置（可选，不上传则使用内置 ISO 配置）</label>
      <input type="file" name="profile_file" accept="application/json">
      <button type="submit">开始分析</button>
    </form>
  </section>

  {err_html}
  {convert_html}
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
        if self.path not in {"/analyze", "/convert-dxf"}:
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
            self._send_html(_render_page(errors=errors, converted_drawing=converted))
            return

        errors: list[str] = []
        result: dict[str, Any] | None = None
        report_md = ""

        part_name, part_raw = get_file("part_file")
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
            if profile_raw:
                profile = _load_json_bytes(profile_raw)
            else:
                profile = json.loads(DEFAULT_PROFILE.read_text(encoding="utf-8"))
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
    print("[TIP] 2D 支持 JSON/DXF，3D 可选")
    server.serve_forever()


if __name__ == "__main__":
    main()
