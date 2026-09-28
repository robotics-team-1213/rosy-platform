#!/usr/bin/env python3
"""Read-only LAN landing page while a moved SD card awaits new registration."""

from __future__ import annotations

import argparse
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


STATUS = Path("/run/rosy-boot/boot-status.json")
DEVICE_NAME = re.compile(r"^rosy-pinky-[a-hj-km-np-z2-9]{4}$")


def response(path: str, status_path: Path) -> tuple[int, dict[str, str], bytes]:
    """Expose setup status, never the previous device's CORE or credentials."""
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        status = {}
    if not isinstance(status, dict) or status.get("stage") != "SETUP":
        return 503, {"Content-Type": "text/plain; charset=utf-8"}, b"Setup status unavailable\n"

    route = urlsplit(path).path
    if route.startswith("/api/"):
        body = json.dumps({"state": "NEW_DEVICE_SETUP", "ready": False}).encode("ascii")
        return 503, {"Content-Type": "application/json; charset=utf-8"}, body
    if route not in {"/", "/dashboard"}:
        return 404, {"Content-Type": "text/plain; charset=utf-8"}, b"Not found\n"

    candidate = status.get("device_name")
    name = candidate if isinstance(candidate, str) and DEVICE_NAME.fullmatch(candidate) else "New Rosy device"
    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>ROSY 새 장치 등록</title>
<style>
:root {{ color-scheme: light; font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
  color: #18232b; background: #f3f6f5; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: clamp(1rem, 5vw, 3rem); }}
main {{ width: min(100%, 42rem); margin: 0 auto; }}
.eyebrow {{ margin: 0 0 .35rem; color: #47665c; font-size: .8rem; font-weight: 700;
  letter-spacing: .08em; }}
h1 {{ margin: 0; font-size: clamp(1.65rem, 5vw, 2.15rem); line-height: 1.2; }}
.intro {{ margin: .75rem 0 1.25rem; color: #43515a; }}
.state {{ padding: 1rem 1.1rem; border: 1px solid #e2bf78; border-left: .3rem solid #b27615;
  background: #fff9ed; }}
.state strong {{ display: block; margin-bottom: .25rem; }}
.state p {{ margin: 0; }}
section {{ margin-top: 1.25rem; padding: 1.2rem; border: 1px solid #d6dfdc;
  background: #fff; }}
h2 {{ margin: 0 0 .75rem; font-size: 1.1rem; }}
ol {{ display: grid; gap: .85rem; margin: 0; padding: 0; list-style: none; counter-reset: step; }}
li {{ position: relative; min-height: 2.4rem; padding-left: 2.6rem; counter-increment: step; }}
li::before {{ position: absolute; left: 0; top: .05rem; display: grid; width: 1.9rem; height: 1.9rem;
  place-items: center; border-radius: 50%; background: #e5efeb; color: #254f40;
  content: counter(step); font-weight: 700; }}
li strong {{ display: block; }}
.device {{ display: inline-block; margin-top: .75rem; padding: .25rem .55rem; border: 1px solid #d6dfdc;
  background: #f6f8f7; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
.command {{ overflow-wrap: anywhere; margin: .75rem 0 0; padding: .7rem .8rem; background: #eef3f1;
  font: .9rem/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; }}
.note {{ margin: .85rem 0 0; color: #53616a; font-size: .92rem; }}
@media (max-width: 28rem) {{ section {{ padding: 1rem; }} }}
</style>
</head>
<body><main aria-labelledby="page-title">
<p class="eyebrow">장치 등록 · SETUP</p>
<h1 id="page-title">새 로봇 등록이 필요합니다</h1>
<p class="intro">고장 상태가 아닙니다. 이 SD 카드가 다른 Raspberry Pi에서 시작되어 새 등록을 기다리고 있습니다.</p>
<div class="state" role="status">
  <strong>이전 로봇 정보는 자동으로 사용하지 않습니다</strong>
  <p>기존 로봇 번호와 접근 권한은 안전을 위해 잠겨 있습니다. 현장 Wi-Fi 연결은 유지됩니다.</p>
</div>
<section aria-labelledby="steps-title">
  <h2 id="steps-title">가장 간단한 등록 방법</h2>
  <ol>
    <li><strong>Windows 운영 PC에서 새 SD 카드를 준비합니다.</strong>
      새 SD 카드와 이 로봇이 쓰는 현장 Wi-Fi 프로필을 준비하세요.</li>
    <li><strong>아래 도우미를 실행합니다.</strong>
      서명된 이미지와 SETUP 상태를 확인하고 새 번호를 제안합니다. 요약을 확인한 뒤,
      카드 지우기 확인을 직접 입력해야 기록이 시작됩니다.</li>
    <li><strong>완료된 카드를 이 Raspberry Pi에 넣고 전원을 켭니다.</strong>
      부팅 후 대시보드에서 새 장치 상태를 확인하세요.</li>
  </ol>
  <p class="command"><code>.\deploy\sd\setup-moved-device.ps1 -RobotAddress &lt;이 페이지의 로봇 IP&gt;</code></p>
  <p class="note">Windows 운영 PC의 Rosy OS 저장소 폴더에서 실행하세요. 도우미가 이미지 폴더와 저장된 Wi-Fi 프로필을 안내하고,
    카드 쓰기는 기존 서명·일련번호 검증기를 사용합니다.</p>
  <p class="device">임시 장치 이름: {escape(name)}</p>
  <p class="note">기존 SD 카드는 보관해 두세요. 자세한 절차는
    <code>docs/deployment/pinky-pro-first-device-runbook.md</code>의
    “Moving a personalized SD to another Pi”를 참고하세요. 이전 지도나 설정은 새 장치 확인 후 필요한 항목만 복원합니다.</p>
</section>
</main></body></html>"""
    return 200, {"Content-Type": "text/html; charset=utf-8"}, page.encode("utf-8")


def handler(status_path: Path):
    class SetupHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib interface
            code, headers, body = response(self.path, status_path)
            self.send_response(code)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802 - stdlib interface
            self.send_error(405, "Registration changes are not accepted here")

        def log_message(self, _format, *_args):
            return

    return SetupHandler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    with ThreadingHTTPServer(("0.0.0.0", args.port), handler(STATUS)) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
