"""Migration fixture with persistent containers, independent of tags and symlinks."""

import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
from types import SimpleNamespace

from deploy.site import rosy_site_autoupdate as upd
from test_site_autoupdate import FakeHttp, UNIT, OLD, NEW, _image_id, _release, _tag


LEGACY = ("fleet", "vision", "proxy")
CURRENT = (*LEGACY, "postgres")
PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
HASH_LABEL = "com.docker.compose.config-hash"


def manifest_for(commit, services):
    return {"source_commit": commit, "images": {
        s: {"reference": f"rosy-site-{s}:{commit}", "image_id": _image_id(commit, s)}
        for s in services}, "account_https": True, "omx": True, "workcell": True}


def candidate_files(commit, services, compose_services=None, image_override=None):
    model = {"services": {s: {"image": f"rosy-site-{s}:${{ROSY_SITE_IMAGE_TAG}}"}
                          for s in (services if compose_services is None else compose_services)}}
    if image_override:
        model["services"]["fleet"]["image"] = image_override
    files = {"release.json": json.dumps(manifest_for(commit, services)).encode(),
             "release.json.sig": b"fixture-signed", "images.tar": b"fixture images",
             "deploy/site/compose.yaml": json.dumps(model).encode()}
    for overlay in ("pairing", "omx", "workcell", "account"):
        files[f"deploy/site/compose.{overlay}.yaml"] = b'{"services": {}}'
    return files


def write_candidate(folder, commit, services, compose_services=None):
    for name, body in candidate_files(commit, services, compose_services).items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def release_world(commit, services, compose_services=None, image_override=None):
    files = candidate_files(commit, services, compose_services, image_override)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        for name, body in files.items():
            if name == "release.json.sig":
                continue
            info = tarfile.TarInfo(f"{commit}/{name}")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    body = buf.getvalue()
    split = len(body) // 2
    assets = {"release.json": files["release.json"],
              f"rosy-site-candidate-{commit}.tar.part00": body[:split],
              f"rosy-site-candidate-{commit}.tar.part01": body[split:]}
    assets["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in assets.items()).encode()
    assets["release.json.sig"] = files["release.json.sig"]
    return [_release(commit, "2026-10-25T00:00:00Z", assets)], {_tag(commit): assets}


class RecordingHttp(FakeHttp):
    def __init__(self, releases=None, blobs=None):
        super().__init__(releases or [], blobs or {})
        self.gets = []

    def get(self, url, limit):
        self.gets.append(url)
        return super().get(url, limit)


class InventoryHost:
    """Compose up creates expected services but never removes an orphan implicitly."""

    def __init__(self, paths, services=LEGACY, *, unhealthy=()):
        self.paths, self.unhealthy = paths, set(unhealthy)
        self.calls, self.events, self.verifications = [], [], []
        self.containers, self.image_ids = {}, {}
        self.volumes = {"postgres-data": object()}
        self.counter = 0
        self.fault = None
        self.inspect_patch = None
        self.partial_new = None
        self.loaded = []
        self.proof_patch = None
        write_candidate(paths.candidates / OLD, OLD, services)
        self.load_images(paths.candidates / OLD)
        self.restart()
        self.manual = self.add_container("manual-fleet", "fleet", OLD, managed=False)

    def result(self, stdout="", code=0, **kwargs):
        if code and kwargs.get("check"):
            raise subprocess.CalledProcessError(code, "fixture command", stderr="fixture failure")
        return SimpleNamespace(returncode=code, stdout=stdout, stderr="fixture failure" if code else "")

    def model(self, folder):
        return json.loads((folder / "deploy/site/compose.yaml").read_text())["services"]

    def hash_for(self, folder, commit, service, env_file=None):
        values = upd.read_env(env_file or self.paths.site_env)
        values["ROSY_SITE_IMAGE_TAG"] = commit
        body = {"service": self.model(folder)[service], "env": values}
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def load_images(self, folder):
        manifest = json.loads((folder / "release.json").read_text())
        for row in manifest["images"].values():
            self.image_ids[row["reference"]] = row["image_id"]

    def add_container(self, cid, service, commit, *, managed=True, running=True, folder=None):
        folder = folder or self.paths.candidates / commit
        labels = {PROJECT_LABEL: upd.PROJECT, SERVICE_LABEL: service}
        if managed:
            labels[HASH_LABEL] = self.hash_for(folder, commit, service)
        self.containers[cid] = {
            "Id": cid, "Image": _image_id(commit, service),
            "Config": {"Image": f"rosy-site-{service}:{commit}", "Labels": labels},
            "State": {"Running": running, "Health": {
                "Status": "unhealthy" if commit in self.unhealthy else "healthy"}},
            "HostConfig": {"ReadonlyRootfs": True, "Privileged": False}}
        return cid

    def restart(self):
        folder = self.paths.link.resolve()
        commit = upd.read_env(self.paths.site_env)["ROSY_SITE_IMAGE_TAG"]
        model = self.model(folder)
        for service in model:
            for cid, row in list(self.containers.items()):
                labels = row["Config"]["Labels"]
                if (labels.get(PROJECT_LABEL) == upd.PROJECT
                        and labels.get(SERVICE_LABEL) == service and labels.get(HASH_LABEL)):
                    del self.containers[cid]
        for service in (self.partial_new if commit == NEW and self.partial_new is not None else model):
            self.counter += 1
            self.add_container(f"managed-{service}-{self.counter}", service, commit, folder=folder)
        self.events.append(("restart", commit))

    def verify(self, folder, *, trusted_key_id, trusted_public_key, runner, inspect_loaded_images):
        folder = Path(folder)
        self.verifications.append((folder.resolve(), inspect_loaded_images))
        if not (folder / "release.json.sig").is_file() or (
                folder / "release.json.sig").read_bytes() != b"fixture-signed":
            raise upd.CandidateVerificationError("fixture signature mismatch")
        manifest = json.loads((folder / "release.json").read_text())
        services = list(manifest["images"])
        result = {**manifest, "verified_images": services}
        if inspect_loaded_images:
            result["accepted_image_ids"] = {}
            for service, row in manifest["images"].items():
                if self.image_ids.get(row["reference"]) != row["image_id"]:
                    raise upd.CandidateVerificationError("fixture loaded image identity missing/mismatched")
                result["accepted_image_ids"][service] = [row["image_id"]]
        if self.proof_patch:
            self.proof_patch(result)
        return result

    def _listed(self, args):
        rows = list(self.containers.items())
        for i, arg in enumerate(args):
            if arg != "--filter":
                continue
            key, _, value = args[i + 1].partition("=")
            if key == "label":
                label, _, expected = value.partition("=")
                rows = [(cid, row) for cid, row in rows
                        if row["Config"]["Labels"].get(label) == expected]
            elif key == "id":
                rows = [(cid, row) for cid, row in rows if cid == value]
            else:
                raise AssertionError(f"unmodeled filter {key}")
        return rows

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["systemctl", "cat"]:
            return self.result(UNIT, **kwargs)
        if args[:2] == ["systemctl", "restart"]:
            self.restart()
            return self.result(**kwargs)
        if args[:2] == ["docker", "compose"]:
            base = Path(args[args.index("-f") + 1])
            folder = base.resolve().parents[2]
            env_file = Path(args[args.index("--env-file") + 1])
            tag = (kwargs.get("env") or {}).get("ROSY_SITE_IMAGE_TAG") or (
                upd.read_env(env_file)["ROSY_SITE_IMAGE_TAG"])
            model = self.model(folder)
            if "config" in args:
                self.events.append(("config", folder, tag, env_file))
                if "--hash" in args:
                    return self.result("\n".join(
                        f"{s} {self.hash_for(folder, tag, s, env_file)}" for s in model), **kwargs)
                return self.result(json.dumps({"services": {s: {**v, "image": v["image"].replace(
                    "${ROSY_SITE_IMAGE_TAG}", tag)} for s, v in model.items()}}), **kwargs)
            if "ps" in args:
                return self.result("\n".join(json.dumps({
                    "ID": cid, "Service": row["Config"]["Labels"][SERVICE_LABEL],
                    "Image": row["Config"]["Image"],
                    "State": "running" if row["State"]["Running"] else "exited",
                    "Health": row["State"]["Health"]["Status"]})
                    for cid, row in self.containers.items()), **kwargs)
        if args[:3] == ["docker", "image", "load"]:
            folder = Path(args[-1]).parent
            self.load_images(folder)
            self.loaded.append(folder)
            self.events.append(("load", folder))
            return self.result(**kwargs)
        if args[:3] == ["docker", "image", "inspect"]:
            identity = self.image_ids.get(args[-1])
            return self.result(f"{identity}|linux|amd64\n" if identity else "", 0 if identity else 1, **kwargs)
        if args[:3] == ["docker", "image", "ls"]:
            return self.result("\n".join(self.image_ids), **kwargs)
        if args[:3] == ["docker", "image", "rm"]:
            self.image_ids.pop(args[-1], None)
            return self.result(**kwargs)
        if args[:2] == ["docker", "ps"]:
            if self.fault == "enumerate":
                return self.result(code=1, **kwargs)
            rows = self._listed(args)
            if "{{.Image}}" in args:
                return self.result("\n".join(r["Config"]["Image"] for _, r in rows), **kwargs)
            return self.result("\n".join(cid for cid, _ in rows), **kwargs)
        if args[:3] == ["docker", "container", "inspect"]:
            cid = args[-1]
            if self.fault == "inspect" or cid not in self.containers:
                return self.result(code=1, **kwargs)
            row = copy.deepcopy(self.containers[cid])
            if self.inspect_patch:
                self.inspect_patch(row)
            if "--format" in args:
                return self.result(row["Image"], **kwargs)
            return self.result(json.dumps([row]), **kwargs)
        if args[:3] == ["docker", "container", "stop"]:
            cid = args[-1]
            assert args == ["docker", "container", "stop", "--", cid]
            if self.fault == "stop":
                return self.result(code=1, **kwargs)
            self.containers[cid]["State"]["Running"] = False
            self.events.append(("stop", cid, upd.read_env(self.paths.site_env)["ROSY_SITE_IMAGE_TAG"],
                                self.paths.link.resolve()))
            return self.result(**kwargs)
        if args[:3] == ["docker", "container", "rm"]:
            cid = args[-1]
            assert args == ["docker", "container", "rm", "--", cid]
            if self.fault == "remove":
                return self.result(code=1, **kwargs)
            if self.containers[cid]["State"]["Running"]:
                return self.result(code=1, **kwargs)
            if self.fault != "remove-noop":
                del self.containers[cid]
            self.events.append(("remove", cid, upd.read_env(self.paths.site_env)["ROSY_SITE_IMAGE_TAG"],
                                self.paths.link.resolve()))
            return self.result(**kwargs)
        raise AssertionError(f"unmodeled command {args}")


def updater_for(host, machine, http=None, **kwargs):
    clock = iter(range(0, 100000, 10))
    return upd.SiteUpdater(host.config, paths=host.paths, runner=machine,
                           verifier=machine.verify, http=http or RecordingHttp(),
                           sleep=lambda _: None, clock=lambda: next(clock), **kwargs)
