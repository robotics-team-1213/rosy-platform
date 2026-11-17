"""D-866 §4: hold_gpu.sh leaves a `gpu` lock that host_probe counts while the job runs and drops after."""
import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools/remote/hold_gpu.sh"


def test_the_lock_names_the_job_itself(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    seen = subprocess.run(["bash", str(SCRIPT), "4", "12", "bash", "-c", 'echo $$; cat ~/rosy-jobs/*.lock'],
                          env=env, capture_output=True, text=True, check=True).stdout.split("\n")
    assert re.fullmatch(r"\d+ gpu 4 12", seen[1])
    assert seen[1].split()[0] == seen[0]  # exec: the lock's pid is the job's, so it dies with the job


def test_children_get_the_lock_cores_as_their_thread_cap_unless_set(tmp_path):
    env = {k: v for k, v in os.environ.items() if k not in ("OMP_NUM_THREADS", "MKL_NUM_THREADS")}
    env["HOME"] = str(tmp_path)
    show = ["bash", "-c", 'echo "$OMP_NUM_THREADS $MKL_NUM_THREADS"']
    assert subprocess.run(["bash", str(SCRIPT), "8", "12", *show], env=env, capture_output=True, text=True,
                          check=True).stdout.strip() == "8 8"
    env["OMP_NUM_THREADS"] = "2"
    assert subprocess.run(["bash", str(SCRIPT), "8", "12", *show], env=env, capture_output=True, text=True,
                          check=True).stdout.split()[0] == "2"


def test_it_refuses_a_budget_that_is_not_whole_numbers(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    result = subprocess.run(["bash", str(SCRIPT), "4", "$(reboot)", "true"], env=env, capture_output=True, text=True)
    assert result.returncode == 2 and not (tmp_path / "rosy-jobs").exists()


def _fake_ollama(models):
    """An Ollama stand-in on a free port: /api/ps lists `models`, POST bodies are recorded."""
    import http.server
    import json
    import threading
    posted = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"models": [{"name": m} for m in models]}).encode()
            self.send_response(200), self.send_header("Content-Length", str(len(body))), self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            posted.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200), self.send_header("Content-Length", "2"), self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, posted


def test_an_on_demand_host_unloads_resident_ollama_models_and_others_leave_them(tmp_path):
    server, posted = _fake_ollama(["qwen3-vl:8b-instruct"])
    env = {**os.environ, "HOME": str(tmp_path), "ROSY_OLLAMA_URL": f"http://127.0.0.1:{server.server_port}"}
    try:
        subprocess.run(["bash", str(SCRIPT), "1", "1", "true"], env=env, check=True)
        assert posted == []  # no marker: the AI PC's Ollama is D-958 gpu_tenants' to lend, not ours to unload
        (tmp_path / "rosy-jobs" / "ollama-on-demand").touch()
        done = subprocess.run(["bash", str(SCRIPT), "1", "1", "bash", "-c", "echo ran"], env=env, check=True, capture_output=True, text=True)
        assert posted == [("/api/generate", {"model": "qwen3-vl:8b-instruct", "keep_alive": 0})] and done.stdout.strip() == "ran"
    finally:
        server.shutdown()
    env["ROSY_OLLAMA_URL"] = "http://127.0.0.1:9"  # Ollama down: the job still runs
    assert subprocess.run(["bash", str(SCRIPT), "1", "1", "bash", "-c", "echo ran"], env=env, check=True,
                          capture_output=True, text=True).stdout.strip() == "ran"
