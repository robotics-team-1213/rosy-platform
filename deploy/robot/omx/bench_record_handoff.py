#!/usr/bin/env python3
"""Stdlib-only collection verification, single-hop SCP push, Canonical intake notify, and team HF policy checks."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HF_TEAM_ORG = "robotteam"
DEFAULT_HF_DATASET_REPO = "robotteam/rosy-omx-data"
CONFIG_FILE = ".bench-handoff-config.json"
QUEUE_FILE = ".bench-handoff-queue.json"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_SAFE_TARGET = re.compile(r"^(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_REMOTE_DIR = re.compile(r"^(?:~/|/)[A-Za-z0-9_./-]{1,254}$")
_SSH_OPTS = (
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3",
)
_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")


def atomic_write_json(path: Path, data: object) -> None:
    """Atomically write bounded JSON without leaving half-written state across crashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    raw = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    try:
        tmp.write_text(raw, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def load_json_value(path: Path, default):
    """Best-effort JSON load that falls back to `default` when absent or corrupt."""
    try:
        if path.is_file() and not path.is_symlink():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return default


def collections_root(home: Path | None = None) -> Path:
    return (home or Path.home()) / "rosy-test" / "omx-collections"


def default_handoff_config() -> dict:
    return {
        "auto_loop": True,
        "auto_hf_upload": False,
        "model_target": "",
        "remote_collections_dir": "~/rosy-test/omx-collections",
        "intake_url": "",
        "peer_token_file": "",
        "hf_repo_id": DEFAULT_HF_DATASET_REPO,
    }


def _host_allows_plain_http(host: str | None) -> bool:
    if not host:
        return False
    h = host.strip("[]").lower()
    if h == "localhost" or h.endswith((".local", ".ts.net")):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return (not ip.is_unspecified) and (ip.is_loopback or ip.is_private or (ip.version == 4 and ip in _CGNAT_NET))
    except ValueError:
        return "." not in h


def _validate_url(url: str) -> str:
    clean = str(url or "").strip()
    if not clean:
        return ""
    if len(clean) > 256 or any(ord(c) < 32 or c.isspace() for c in clean):
        raise ValueError("intake_url 형식이 올바르지 않습니다")
    parsed = urllib.parse.urlsplit(clean)
    if parsed.username or parsed.password or parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("intake_url은 인증 정보 없는 http(사설/Tailscale)/https URL이어야 합니다")
    if parsed.scheme == "http" and not _host_allows_plain_http(parsed.hostname):
        raise ValueError("외부 호스트 intake_url은 https://만 허용됩니다")
    return clean.rstrip("/")


def _validate_remote_dir(raw: str) -> str:
    clean = str(raw or "~/rosy-test/omx-collections").strip().rstrip("/")
    if not _SAFE_REMOTE_DIR.fullmatch(clean) or "//" in clean or "~" in clean[1:] or ".." in clean.split("/"):
        raise ValueError("remote_collections_dir은 '~/' 또는 '/'로 시작하는 안전 경로여야 합니다")
    return clean


def load_handoff_config(prep: Path) -> dict:
    cfg = default_handoff_config()
    saved = load_json_value(prep / CONFIG_FILE, {})
    if isinstance(saved, dict):
        for k in cfg:
            if k in saved:
                cfg[k] = saved[k]
    cfg["hf_repo_id"] = DEFAULT_HF_DATASET_REPO
    return cfg


def save_handoff_config(prep: Path, patch: dict) -> dict:
    cfg = load_handoff_config(prep)
    if "auto_loop" in patch:
        cfg["auto_loop"] = bool(patch["auto_loop"])
    if "auto_hf_upload" in patch:
        cfg["auto_hf_upload"] = bool(patch["auto_hf_upload"])
    if "model_target" in patch:
        tgt = str(patch["model_target"] or "").strip()
        if tgt and not _SAFE_TARGET.fullmatch(tgt):
            raise ValueError("model_target은 user@host 또는 hostname 형식이어야 합니다")
        cfg["model_target"] = tgt
    if "remote_collections_dir" in patch:
        cfg["remote_collections_dir"] = _validate_remote_dir(patch["remote_collections_dir"])
    if "intake_url" in patch:
        cfg["intake_url"] = _validate_url(patch["intake_url"])
    if "peer_token_file" in patch:
        tok = str(patch["peer_token_file"] or "").strip()
        if tok and (len(tok) > 256 or any(ord(c) < 32 for c in tok)):
            raise ValueError("peer_token_file 경로 형식이 올바르지 않습니다")
        cfg["peer_token_file"] = tok
    if "hf_repo_id" in patch and str(patch["hf_repo_id"] or "").strip() not in ("", DEFAULT_HF_DATASET_REPO):
        raise ValueError(f"HF 저장소는 '{DEFAULT_HF_DATASET_REPO}'로 고정됩니다")
    cfg["hf_repo_id"] = DEFAULT_HF_DATASET_REPO
    atomic_write_json(prep / CONFIG_FILE, cfg)
    return cfg


def load_handoff_queue(prep: Path) -> list[dict]:
    rows = load_json_value(prep / QUEUE_FILE, [])
    return [r for r in rows if isinstance(r, dict) and r.get("collection")][-50:] if isinstance(rows, list) else []


def record_queue_status(prep: Path, collection: str, **updates) -> list[dict]:
    prev = load_handoff_queue(prep)
    entry = next((r for r in prev if r.get("collection") == collection), {"collection": collection})
    rows = [r for r in prev if r.get("collection") != collection]
    rows.append({**entry, **updates, "collection": collection, "updated_at": int(time.time())})
    rows = rows[-50:]
    atomic_write_json(prep / QUEUE_FILE, rows)
    return rows


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sealed_collection(collection_dir: Path) -> dict:
    """Verify closed hardware manifest, digests, episode count, and DO_NOT_TRAIN gate before transfer."""
    if not collection_dir.is_dir() or collection_dir.is_symlink():
        raise ValueError(f"봉인된 컬렉션을 찾을 수 없습니다: {collection_dir.name}")
    if (collection_dir / "DO_NOT_TRAIN.txt").exists() or (collection_dir / "dataset" / "DO_NOT_TRAIN.txt").exists():
        raise ValueError(f"정지회차(DO_NOT_TRAIN) 컬렉션입니다: {collection_dir.name}")
    mf_path = collection_dir / "manifest.json"
    if not mf_path.is_file() or mf_path.is_symlink():
        raise ValueError(f"manifest.json이 없습니다: {collection_dir.name}")
    manifest = json.loads(mf_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "rosy.omx-collection-session.v1" or manifest.get("state") != "CLOSED" or manifest.get("mode") != "hardware":
        raise ValueError(f"닫힌 실물 하드웨어 봉인(CLOSED)이 아닙니다: {collection_dir.name}")
    if manifest.get("source_mode") not in ("leader_native", "scripted_teacher"):
        raise ValueError(f"허용되지 않은 source_mode입니다: {manifest.get('source_mode')}")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("manifest.json files 목록이 비어 있습니다")
    seen = set()
    for p in sorted(collection_dir.rglob("*")):
        if p.is_symlink() or not p.resolve().is_relative_to(collection_dir.resolve()):
            raise ValueError(f"컬렉션 내 링크/경로 이탈은 허용되지 않습니다: {p.name}")
        if p.is_file() and p != mf_path:
            seen.add(p.relative_to(collection_dir).as_posix())
    if seen != set(files):
        raise ValueError("manifest.json 파일 목록과 실제 파일이 일치하지 않습니다")
    for rel, expected in files.items():
        if "\n" in rel or "\r" in rel or rel.startswith(("/", "-")) or ".." in Path(rel).parts:
            raise ValueError(f"잘못된 manifest 경로입니다: {rel!r}")
        if _sha256_file(collection_dir / rel) != expected:
            raise ValueError(f"파일 SHA-256 불일치: {rel}")
    info_path = collection_dir / "dataset" / "meta" / "info.json"
    info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.is_file() else {}
    parquets = list((collection_dir / "dataset").glob("data/**/*.parquet"))
    ep_m, ep_i = manifest.get("total_episodes"), info.get("total_episodes")
    if type(ep_m) is not int or type(ep_i) is not int or ep_m < 1 or ep_i < 1 or not parquets:
        raise ValueError(f"에피소드(parquet >= 1)가 없는 빈 컬렉션은 전송할 수 없습니다: {collection_dir.name}")
    return {
        "collection": collection_dir.name,
        "manifest": manifest,
        "manifest_sha256": _sha256_file(mf_path),
        "file_count": len(files),
        "total_episodes": int(manifest["total_episodes"]),
        "arm_id": str(manifest.get("arm_id") or ""),
    }


def _remote_shell_expr(remote_dir: str) -> str:
    return f'"$HOME/{remote_dir[2:]}"' if remote_dir.startswith("~/") else shlex.quote(remote_dir)


def _scp_dest(remote_dir: str) -> str:
    return remote_dir[2:] if remote_dir.startswith("~/") else remote_dir


def push_collection_to_model(collection_dir: Path, config: dict, *, run=subprocess.run, verified: dict | None = None) -> dict:
    """Push a verified collection to Model PC via staging directory, full SHA-256 check, and atomic rename."""
    info = verified or verify_sealed_collection(collection_dir)
    target = str(config.get("model_target") or "").strip()
    if not target:
        return {"status": "unconfigured", "ok": False, "error": "모델 PC 전송 대상(model_target)이 설정되지 않았습니다", "verification": info}
    if not _SAFE_TARGET.fullmatch(target):
        raise ValueError("올바른 model_target(user@host) 형식이 필요합니다")
    remote_dir = _validate_remote_dir(config.get("remote_collections_dir") or "~/rosy-test/omx-collections")
    name = collection_dir.name
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError("잘못된 컬렉션 이름입니다")

    base_expr = _remote_shell_expr(remote_dir)
    staging_expr = _remote_shell_expr(f"{remote_dir}/.staging-{name}")
    final_expr = _remote_shell_expr(f"{remote_dir}/{name}")
    scp_staging = f"{_scp_dest(remote_dir)}/.staging-{name}"
    sha_manifest_lines = "".join(
        f"{digest}  {rel}\n" for rel, digest in sorted(info["manifest"]["files"].items())
    ) + f"{info['manifest_sha256']}  manifest.json\n"

    prep_cmd = (
        f"if test -f {final_expr}/manifest.json; then "
        f"if (cd {final_expr} && sha256sum -c - >/dev/null 2>&1); then echo ALREADY_MATCHED; exit 0; "
        f"else echo 'remote collection exists with different or corrupt files' >&2; exit 2; fi; "
        f"elif test -e {final_expr}; then echo 'remote path exists without manifest.json' >&2; exit 2; fi; "
        f"mkdir -p {base_expr} && rm -rf {staging_expr}"
    )
    res0 = run(["ssh", *_SSH_OPTS, "--", target, prep_cmd], input=sha_manifest_lines, capture_output=True, text=True, timeout=60)
    if res0.returncode != 0:
        err = (res0.stderr or res0.stdout or f"ssh exit {res0.returncode}").strip()
        return {"status": "failed", "ok": False, "error": f"모델 PC SSH 준비 실패: {err}", "verification": info}
    if "ALREADY_MATCHED" in (res0.stdout or ""):
        return {"status": "done", "ok": True, "already_present": True, "remote_path": f"{remote_dir}/{name}", "target": target, "verification": info}

    res1 = run(["scp", *_SSH_OPTS, "-r", "--", str(collection_dir), f"{target}:{scp_staging}"], capture_output=True, text=True, timeout=600)
    if res1.returncode != 0:
        err = (res1.stderr or res1.stdout or f"scp exit {res1.returncode}").strip()
        return {"status": "failed", "ok": False, "error": f"모델 PC SCP 전송 실패: {err}", "verification": info}

    promote_cmd = (
        f"(test ! -e {final_expr} && cd {staging_expr} && sha256sum -c - >/dev/null 2>&1 && "
        f"mv -- {staging_expr} {final_expr}) || {{ rm -rf {staging_expr}; exit 1; }}"
    )
    res2 = run(["ssh", *_SSH_OPTS, "--", target, promote_cmd], input=sha_manifest_lines, capture_output=True, text=True, timeout=60)
    if res2.returncode != 0:
        err = (res2.stderr or res2.stdout or f"ssh promote exit {res2.returncode}").strip()
        return {"status": "failed", "ok": False, "error": f"모델 PC 수신 해시 검증 실패: {err}", "verification": info}

    return {"status": "done", "ok": True, "remote_path": f"{remote_dir}/{name}", "target": target, "verification": info}


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"redirect blocked ({code})", headers, fp)


def _read_bearer_token(token_file: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(token_file, flags)
    except OSError as exc:
        raise ValueError(f"피어 토큰 파일을 열 수 없습니다: {exc}") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError("피어 토큰 파일이 일반 파일이 아닙니다")
        if os.name == "posix":
            if st.st_uid != os.getuid():
                raise ValueError("피어 토큰 파일 소유자가 일치하지 않습니다")
            if stat.S_IMODE(st.st_mode) & 0o077:
                raise ValueError("피어 토큰 파일 권한은 0600 이하여야 합니다")
        if st.st_size > 4096:
            raise ValueError("피어 토큰 크기 제한(4096B)을 초과했습니다")
        raw = os.read(fd, 4097)
    finally:
        os.close(fd)
    if len(raw) > 4096:
        raise ValueError("피어 토큰 크기 제한(4096B)을 초과했습니다")
    token = raw.decode("utf-8").strip()
    if not 16 <= len(token) <= 4096 or any(ord(c) < 32 for c in token):
        raise ValueError("피어 토큰 형식이 유효하지 않습니다")
    return token


def notify_canonical_intake(config: dict, transfer_info: dict, *, urlopen=None) -> dict:
    """Notify Model PC /api/learning/canonical/intake using Bearer authentication (no redirects or proxies)."""
    url = _validate_url(config.get("intake_url") or "")
    if not url:
        return {"status": "unconfigured", "ok": False, "error": "Canonical intake URL이 설정되지 않았습니다"}
    tok_raw = str(config.get("peer_token_file") or "").strip()
    if not tok_raw:
        return {"status": "failed", "ok": False, "error": "peer_token_file이 설정되지 않아 Canonical 인입을 호출할 수 없습니다"}
    try:
        token = _read_bearer_token(Path(tok_raw).expanduser())
    except (OSError, ValueError, UnicodeError) as exc:
        return {"status": "failed", "ok": False, "error": f"피어 토큰 오류: {exc}"}

    ver = transfer_info["verification"]
    payload = {
        "collection": ver["collection"],
        "manifest_sha256": ver["manifest_sha256"],
        "remote_path": transfer_info.get("remote_path", ""),
        "arm_id": ver.get("arm_id", ""),
        "total_episodes": ver["total_episodes"],
        "rig_revision": str(ver["manifest"].get("rig_revision") or ""),
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    open_fn = urlopen or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirectHandler()).open
    try:
        with open_fn(req, timeout=15) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        return {"status": "done", "ok": True, "response": doc}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "failed", "ok": False, "error": f"Canonical intake HTTP {exc.code}: {body[:160]}"}
    except Exception as exc:
        return {"status": "failed", "ok": False, "error": f"Canonical intake 호출 실패: {type(exc).__name__}: {exc}"}


def validate_team_hf_upload(api, ds_folder: Path, config: dict, *, ds_name: str = "") -> tuple[str, str]:
    """Enforce robotteam org membership, non-empty episodes, no symlinks, and fixed robotteam/rosy-omx-data target."""
    if not ds_folder.is_dir() or ds_folder.is_symlink():
        raise RuntimeError("데이터셋 폴더를 찾을 수 없습니다")
    root_res = ds_folder.resolve()
    for p in ds_folder.rglob("*"):
        if p.is_symlink() or not p.resolve().is_relative_to(root_res):
            raise RuntimeError(f"데이터셋 내 링크/경로 이탈 차단: {p.name}")
    info_path = ds_folder / "meta" / "info.json"
    if ((ds_folder / "DO_NOT_TRAIN.txt").exists()
            or (ds_folder.name == "dataset" and (ds_folder.parent / "DO_NOT_TRAIN.txt").exists())
            or not info_path.is_file()):
        raise RuntimeError("DO_NOT_TRAIN이거나 meta/info.json이 없는 데이터셋은 업로드할 수 없습니다")
    info = json.loads(info_path.read_text(encoding="utf-8"))
    ep_i = info.get("total_episodes")
    if type(ep_i) is not int or ep_i < 1 or not list(ds_folder.glob("data/**/*.parquet")):
        raise RuntimeError("에피소드(total_episodes >= 1, parquet)가 없는 데이터셋은 업로드할 수 없습니다")
    who = api.whoami() or {}
    user = str(who.get("name") or "")
    orgs = [str(o.get("name") or "") for o in (who.get("orgs") or []) if isinstance(o, dict)]
    if user != DEFAULT_HF_TEAM_ORG and DEFAULT_HF_TEAM_ORG not in orgs:
        raise RuntimeError(f"개인 HF 계정({user or 'unknown'}) 업로드 차단 — '{DEFAULT_HF_TEAM_ORG}' 팀 소속 계정이 필요합니다")
    repo_id = str(config.get("hf_repo_id") or DEFAULT_HF_DATASET_REPO).strip()
    if repo_id != DEFAULT_HF_DATASET_REPO:
        raise RuntimeError(f"HF 저장소는 '{DEFAULT_HF_DATASET_REPO}'로 고정되어 있습니다: {repo_id}")
    subpath = str(ds_name or ds_folder.name).strip()
    if not subpath or subpath == "dataset" or not _SAFE_NAME.fullmatch(subpath):
        raise RuntimeError(f"올바른 데이터셋 하위 경로가 필요합니다: {subpath!r}")
    return repo_id, subpath
