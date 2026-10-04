"""`payload-boot-smoke.yml` 계약 (D-444 P1.2).

같은 arm64 러너에서 payload artifact를 부팅해 세 웹 표면의 200+CSP를 관측한다.
수동 실행만, 비밀 없음(GITHUB_TOKEN 한정), 실패 시 로그 업로드 — D-437 워크플로
규율과 같은 문화다. 로컬 에뮬레이션 벤치는 binfmt 유실로 반복 불능이었음(2026-10-04,
3회) — 그래서 이 워크플로가 P1.2의 정본 자리다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/payload-boot-smoke.yml")


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_manual_dispatch_only_no_schedule_or_push():
    flow = _workflow()
    assert set(flow.get("on", {}).keys()) == {"workflow_dispatch"}, \
        "수동 실행만 허용한다 — push마다 돌면 payload 빌드 비용이 배가된다"


def test_runs_in_the_ros_container_on_the_arm_runner():
    job = _workflow()["jobs"]["boot-smoke"]
    assert job["runs-on"] == "ubuntu-24.04-arm", "native arm64 — 에뮬레이션 금지(D-161 취지)"
    assert job["container"] == "ros:jazzy-ros-base@sha256:c3706ef0a0aa45413c07803cf433602f543b22e45b4855f6fca955c2d8ecc4e8", "ROS apt 소스는 컨테이너가 제공한다"
    assert 0 < int(job["timeout-minutes"]) <= 30


def test_no_secrets_beyond_the_job_token():
    flow = _workflow()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert flow["permissions"] == {"contents": "read", "actions": "read"}
    assert "secrets." not in text, "서명 키·비밀은 이 워크플로에 없다(D-437)"


def test_probes_all_three_web_surfaces_and_fails_on_missing_csp():
    text = WORKFLOW.read_text(encoding="utf-8")
    for path in ("dashboard", "pilot", "console"):
        assert path in text and 'http://127.0.0.1:8080/$path' in text, f"/{path} 프로브가 없다"
    assert "content-security-policy" in text, "CSP 헤더 확인이 없다(D-444 R1)"
    assert "exit 1" in text


def test_boots_from_the_payload_install_with_pinned_rmw_and_identity():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "release/install/setup.bash" in text
    assert "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp" in text, "CycloneDDS 핀(D-117)"
    assert "ROSY_ROBOT_NUMBER=1" in text, "신원 없으면 런타임이 멈춘다(D-33)"
    assert 'grep -q "core up"' in text


def test_uploads_the_boot_log_even_on_failure():
    job = _workflow()["jobs"]["boot-smoke"]
    steps = {s.get("name", ""): s for s in job["steps"]}
    upload = steps.get("Upload the boot log")
    assert upload and upload.get("if") == "always()", "실패 로그가 사라지면 관측이 불가하다"

def _resolve_fixture(tmp_path, *, input_value="123", change=None, artifact_change=None):
    import json
    import os
    import shutil
    import subprocess
    sha = "a" * 40
    run = {"id": 123, "head_sha": sha, "path": ".github/workflows/build-native-payload.yml",
           "repository": {"full_name": "owner/repo"}, "head_repository": {"full_name": "owner/repo"},
           "event": "workflow_dispatch", "head_branch": "main", "status": "completed", "conclusion": "success"}
    run.update(change or {})
    artifact = {"name": "rosy-native-payload-unsigned-2026.10.04-001-" + sha, "expired": False, "id": 456}
    artifact.update(artifact_change or {})
    (tmp_path / "fixture-run.json").write_text(json.dumps(run))
    (tmp_path / "fixture-artifacts.json").write_text(json.dumps({"artifacts": [artifact]}))
    (tmp_path / "fixture-list.json").write_text(json.dumps({"workflow_runs": [run]}))
    import zipfile
    with zipfile.ZipFile(tmp_path / "fixture.zip", "w") as z:
        z.writestr("2026.10.04-001.unsigned.tar.gz", "fixture only")
    cli = tmp_path / "curl"
    cli.write_text('''curl() {
printf '%s\n' "$*" >> "$GH_TRACE"
url="${@: -1}"
case "$url" in
  *workflows/build-native-payload.yml/runs?*) cat "$FIXTURE/fixture-list.json" ;;
  */actions/runs/123/artifacts) cat "$FIXTURE/fixture-artifacts.json" ;;
  */actions/runs/123) cat "$FIXTURE/fixture-run.json" ;;
  */actions/artifacts/456/zip) cp "$FIXTURE/fixture.zip" payload/artifact.zip; touch "$FIXTURE/downloaded" ;;
  *) exit 90 ;;
esac
}
''')
    cli.chmod(0o755)
    step = next(s for s in _workflow()["jobs"]["boot-smoke"]["steps"]
                if s.get("name") == "Resolve the payload artifact")
    script = tmp_path / "resolve.sh"
    script.write_text(step["run"])
    env = dict(os.environ, PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
               GH_REPO="owner/repo", GH_TOKEN="fixture-token-not-a-credential", EXPECTED_SHA=sha, BUILD_RUN_ID=input_value,
               BASH_ENV=str(cli), GITHUB_ENV=str(tmp_path / "job-env"), GH_TRACE=str(tmp_path / "calls"), FIXTURE=str(tmp_path))
    bash = r"C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash, "shell resolver test requires bash"
    return subprocess.run([bash, str(script)], cwd=tmp_path, env=env, capture_output=True, text=True)


def test_resolver_downloads_only_the_exact_validated_artifact(tmp_path):
    result = _resolve_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "downloaded").exists()
    assert "https://api.github.com/repos/owner/repo/actions/artifacts/456/zip" in (tmp_path / "calls").read_text()


def test_empty_input_resolves_only_the_workflow_source_commit(tmp_path):
    result = _resolve_fixture(tmp_path, input_value="")
    assert result.returncode == 0, result.stderr
    assert "build-native-payload.yml/runs?status=success&head_sha=" + "a" * 40 in (tmp_path / "calls").read_text()


def test_shell_input_is_rejected_before_any_cli_call(tmp_path):
    result = _resolve_fixture(tmp_path, input_value='123"; touch injected; #')
    assert result.returncode != 0
    assert not (tmp_path / "calls").exists() and not (tmp_path / "injected").exists()


def test_untrusted_build_workflow_or_source_never_downloads(tmp_path):
    for index, change in enumerate(({"head_sha": "b" * 40}, {"path": ".github/workflows/other.yml"},
                                  {"conclusion": "failure"}, {"head_repository": {"full_name": "fork/repo"}})):
        case = tmp_path / str(index)
        case.mkdir()
        result = _resolve_fixture(case, change=change)
        assert result.returncode != 0 and not (case / "downloaded").exists()
        assert "/actions/runs/123/artifacts" in (case / "calls").read_text()


def test_expired_or_wrong_named_artifact_never_downloads(tmp_path):
    for index, change in enumerate(({"expired": True}, {"name": "unrelated-log"})):
        case = tmp_path / str(index)
        case.mkdir()
        result = _resolve_fixture(case, artifact_change=change)
        assert result.returncode != 0 and not (case / "downloaded").exists()
        assert "/actions/runs/123/artifacts" in (case / "calls").read_text()



def _run_step(tmp_path, name, *, env=None, replace=None):
    import os
    import shutil
    import subprocess
    step = next(s for s in _workflow()["jobs"]["boot-smoke"]["steps"] if s["name"].startswith(name))
    script = tmp_path / "step.sh"
    text = step["run"]
    if replace:
        text = text.replace(*replace)
    script.write_text(text)
    bash = r"C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    return subprocess.run([bash, str(script)], cwd=tmp_path, env=dict(os.environ, **(env or {})),
                          capture_output=True, text=True)


def _payload_fixture(tmp_path, *, change=None, tamper=False):
    import hashlib
    import io
    import json
    import tarfile
    sha = "a" * 40
    manifest = {"schema_version": 1, "release_id": "2026.10.04-001", "git_revision": sha,
                "target": {"board": "pinky_pro", "host": "raspberry-pi-5", "architecture": "arm64",
                           "os_family": "ubuntu-server", "os_release": "24.04"},
                "runtime": {"model": "native-systemd", "default_mode": "core"}}
    manifest.update(change or {})
    files = {"manifest.json": json.dumps(manifest).encode(), "install/.rosy-release": b"2026.10.04-001\n",
             "source-revision.txt": (sha + "\n").encode(), "install/setup.bash": b"# fixture\n"}
    files["SHA256SUMS"] = "".join(hashlib.sha256(v).hexdigest() + "  " + k + "\n"
                                   for k, v in files.items()).encode()
    if tamper:
        files["install/setup.bash"] = b"changed after checksums\n"
    (tmp_path / "payload").mkdir()
    (tmp_path / "selected-artifact.json").write_text(json.dumps({"release_id": "2026.10.04-001"}))
    with tarfile.open(tmp_path / "payload/2026.10.04-001.unsigned.tar.gz", "w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return _run_step(tmp_path, "Unpack", env={"EXPECTED_SHA": sha})


def test_native_archive_root_is_install_not_release_id_directory(tmp_path):
    result = _payload_fixture(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "release/install/setup.bash").is_file()


def test_manifest_source_release_runtime_and_checksum_must_match(tmp_path):
    for index, change in enumerate(({"git_revision": "b" * 40}, {"release_id": "2026.10.04-002"},
                                   {"runtime": {"model": "other"}}, {"target": {"architecture": "amd64"}})):
        case = tmp_path / str(index)
        case.mkdir()
        result = _payload_fixture(case, change=change)
        assert result.returncode != 0
    case = tmp_path / "tamper"
    case.mkdir()
    assert _payload_fixture(case, tamper=True).returncode != 0


def _probe_fixture(tmp_path, *, csp):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(("GET", self.path))
            self.send_response(200)
            if csp:
                self.send_header("Content-Security-Policy", "default-src 'self'")
            self.end_headers()
            self.wfile.write(b"fixture")
        def do_HEAD(self):
            calls.append(("HEAD", self.path))
            self.send_error(405)
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _run_step(tmp_path, "Probe", replace=("127.0.0.1:8080", f"127.0.0.1:{server.server_port}"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    return result, calls


def test_get_csp_succeeds_when_head_is_unsupported(tmp_path):
    result, calls = _probe_fixture(tmp_path, csp=True)
    assert result.returncode == 0, result.stderr
    assert calls == [("GET", "/dashboard"), ("GET", "/pilot"), ("GET", "/console")]
    assert (tmp_path / "probe/console.headers").is_file()
    assert (tmp_path / "probe/console.body").read_bytes() == b"fixture"


def test_get_without_csp_fails_with_readable_reason_and_saved_response(tmp_path):
    result, calls = _probe_fixture(tmp_path, csp=False)
    assert result.returncode != 0
    assert "FAIL /dashboard missing GET CSP" in result.stdout
    assert calls == [("GET", "/dashboard")]
    assert (tmp_path / "probe/dashboard.headers").is_file()
