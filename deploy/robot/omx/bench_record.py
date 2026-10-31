#!/usr/bin/env python3
"""Bench page that starts one leader recording and seals it (D-943 §3). Local only: 127.0.0.1.

A person at the bench presses Start after confirming a hand is on the follower power switch. The page
does not move anything itself; it hands the bus and cameras over and runs the existing tools:

1. stop the torque-OFF observers and camera units that hold the follower ports and V4L devices;
2. run record_session.py unchanged (caps, torque-OFF ending and session.lock stay its job);
3. after it exits and releases session.lock, start exactly the units stopped in step 1;
4. if session.json says safe_end in record mode and the exit was 0, run record_seal.py.

  bench_record.py --config ~/.config/rosy/omx-bench-record.json [--port 8771]
config: {"python": "<LeRobot 0.4.4 python>", "prep_root": "<folder with record-config*.json, caps*.json, tasks/>"}
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent
# Dependents first: camera-view's Requires= pulls readiness down with it (record_session note, 2026-10-24).
HANDOVER = (r"rosy-omx-camera-view\.service", r"rosy-omx-camera-readiness\.service",
            r"rosy-omx-camera@[\w-]+\.service", r"rosy-omx-observer@[\w-]+\.service")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{2,63}")


def systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=60)


def active_handover_units(run=systemctl):
    listed = run("list-units", "--state=active,activating", "--no-legend", "--plain", "rosy-omx-*").stdout.split()
    units = [u for u in listed if u.endswith(".service")]
    return [u for pattern in HANDOVER for u in units if re.fullmatch(pattern, u)]


class Bench:
    def __init__(self, config, *, run=systemctl, popen=subprocess.Popen, clock=time.time):
        self.python, self.prep = config["python"], Path(config["prep_root"]).expanduser()
        self.run, self.popen, self.clock = run, popen, clock
        self.lock, self.child, self.state = threading.Lock(), None, {"status": "idle"}

    def choices(self):
        pick = lambda pattern: sorted(p.name for p in self.prep.glob(pattern))
        return {"configs": pick("record-config*.json"), "caps": pick("caps*.json"),
                "tasks": sorted("tasks/" + p.name for p in (self.prep / "tasks").glob("*.yaml")),
                "calibrations": sorted(str(p) for p in (Path.home() / ".cache/huggingface/lerobot/calibration")
                                       .glob("*/*/*.json"))}

    def _file(self, name, allowed):
        if name not in allowed:
            raise ValueError("choose a listed file")
        return str(self.prep / name)

    def start(self, body):
        if body.get("at_bench") is not True:
            raise ValueError("confirm that a person is at the bench with a hand on the follower power switch")
        choices = self.choices()
        if not NAME.fullmatch(body.get("name", "")) or not NAME.fullmatch(body.get("rig_revision", "")):
            raise ValueError("collection name and rig revision: lowercase letters, digits and dashes")
        calibrations = body.get("calibrations") or []
        if not calibrations or any(c not in choices["calibrations"] for c in calibrations):
            raise ValueError("choose the calibration files used by these arms")
        command = [self.python, str(HERE / "record_session.py"), "--config", self._file(body.get("config"), choices["configs"]),
                   "--caps", self._file(body.get("caps"), choices["caps"])]
        if body.get("task"):
            command += ["--task-card", self._file(body["task"], choices["tasks"])]
        with self.lock:
            if self.state["status"] in ("handing_over", "recording", "restoring", "sealing"):
                raise ValueError("a bench session is already running")
            folder = self.prep / "sessions" / f"{time.strftime('%Y%m%d-%H%M%S')}-{body['name']}"
            folder.mkdir(parents=True)
            self.state = {"status": "handing_over", "name": body["name"], "folder": str(folder), "started": self.clock()}
        seal = [self.python, str(HERE / "record_seal.py"), "--session-dir", str(folder), "--name", body["name"],
                "--rig-revision", body["rig_revision"], *[a for c in calibrations for a in ("--calibration", c)]]
        threading.Thread(target=self._session, args=(command, seal, folder), daemon=True).start()
        return self.status()

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def _session(self, command, seal, folder):
        stopped = []
        try:
            for unit in active_handover_units(self.run):
                self.run("stop", unit)
                stopped.append(unit)
            self._set(status="recording", stopped=stopped)
            with (folder / "bench.log").open("ab") as log:
                self.child = self.popen(command, cwd=folder, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                code = self.child.wait()
        except Exception as exc:
            code = None
            self._set(error=f"{type(exc).__name__}: {exc}")
        finally:
            self._set(status="restoring")
            errors = [u for u in reversed(stopped) if self.run("start", u).returncode != 0]
            self._set(restored=[u for u in stopped if u not in errors], restore_errors=errors)
        session = folder / "session.json"
        record = json.loads(session.read_text()) if session.is_file() else {}
        safe = code == 0 and record.get("safe_end") is True
        self._set(exit_code=code, safe_end=record.get("safe_end"),
                  manual_attention=record.get("manual_attention_required"))
        if not safe:
            self._set(status="unsafe_or_failed" if code is not None else "failed")
            return
        self._set(status="sealing")
        with (folder / "bench.log").open("ab") as log:
            sealed = self.popen(seal, cwd=folder, stdout=log, stderr=subprocess.STDOUT).wait()
        self._set(status="sealed" if sealed == 0 else "seal_failed", seal_exit=sealed)

    def stop(self):
        child = self.child
        if child is None or child.poll() is not None:
            raise ValueError("no recording is running")
        child.send_signal(signal.SIGINT)  # record_session ends the episode and does its own torque-OFF ending
        return self.status()

    def status(self):
        with self.lock:
            return dict(self.state)


PAGE = """<!doctype html><meta charset="utf-8"><title>OMX 작업대 녹화</title>
<h1>OMX 작업대 녹화</h1><p>리더 팔을 잡고, 다른 손은 follower 전원 스위치에 둔 사람만 시작합니다. 중지는 언제든 누를 수 있고 팔 토크 OFF 종료는 record_session이 합니다.</p>
<form id="f"><label>수집 이름 <input name="name" required pattern="[a-z0-9][a-z0-9-]{2,63}"></label>
<label>작업대 배치 이름 <input name="rig_revision" required pattern="[a-z0-9][a-z0-9-]{2,63}"></label>
<label>녹화 설정 <select name="config"></select></label><label>caps <select name="caps"></select></label>
<label>과제 카드 <select name="task"><option value="">없음</option></select></label>
<fieldset id="cal"><legend>사용한 보정 파일</legend></fieldset>
<label><input type="checkbox" name="at_bench"> 작업대에 있고 전원 스위치를 잡고 있습니다</label>
<button>녹화 시작</button> <button type="button" id="stop">중지</button></form><pre id="s"></pre>
<script>
const H={'Content-Type':'application/json','X-Bench':'1'},f=document.getElementById('f');
async function call(path,body){const r=await fetch(path,body?{method:'POST',headers:H,body:JSON.stringify(body)}:{});const v=await r.json();if(!r.ok)throw new Error(v.error);return v;}
(async()=>{const c=await call('/choices.json');
for(const [k,list] of [['config',c.configs],['caps',c.caps],['task',c.tasks]])for(const v of list)f[k].append(new Option(v,v));
for(const v of c.calibrations){const l=document.createElement('label'),i=document.createElement('input');i.type='checkbox';i.value=v;l.append(i,' '+v.split('/').slice(-2).join('/'));document.getElementById('cal').append(l);}})();
f.onsubmit=async e=>{e.preventDefault();const b=Object.fromEntries(new FormData(f));b.at_bench=f.at_bench.checked;
b.calibrations=[...document.querySelectorAll('#cal input:checked')].map(i=>i.value);
try{show(await call('/start',b));}catch(x){document.getElementById('s').textContent=x.message;}};
document.getElementById('stop').onclick=async()=>{try{show(await call('/stop',{}));}catch(x){document.getElementById('s').textContent=x.message;}};
function show(v){document.getElementById('s').textContent=JSON.stringify(v,null,2);}
setInterval(async()=>show(await call('/status.json')),2000);
</script>"""


def make_server(bench, port):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, value, kind="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def local(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self.local():
                return self.reply(403, {"error": "local bench only"})
            routes = {"/": lambda: (PAGE.encode(), "text/html; charset=utf-8"),
                      "/choices.json": lambda: (bench.choices(), "application/json"),
                      "/status.json": lambda: (bench.status(), "application/json")}
            if self.path not in routes:
                return self.reply(404, {"error": "not found"})
            body, kind = routes[self.path]()
            self.reply(200, body, kind)

        def do_POST(self):
            # The custom header forces a CORS preflight, so another origin cannot start a session.
            if not self.local() or self.headers.get("X-Bench") != "1":
                return self.reply(403, {"error": "local bench only"})
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 65536)) or b"{}")
                if self.path == "/start":
                    return self.reply(200, bench.start(body))
                if self.path == "/stop":
                    return self.reply(200, bench.stop())
                self.reply(404, {"error": "not found"})
            except (ValueError, OSError) as exc:
                self.reply(400, {"error": str(exc)})

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config", type=Path, default=Path("~/.config/rosy/omx-bench-record.json").expanduser())
    parser.add_argument("--port", type=int, default=8771)
    args = parser.parse_args(argv)
    make_server(Bench(json.loads(args.config.read_text())), args.port).serve_forever()


if __name__ == "__main__":
    main()
