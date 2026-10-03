"""Site host automatic updater (D-441) with fake HTTP, Docker and systemd."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy.site import rosy_site_autoupdate as upd

REPO = "example-owner/example-repo"
OLD = "1" * 40
NEW = "2" * 40
NEWER = "3" * 40
UNIT = (
    "[Service]\nEnvironmentFile=-/etc/rosy/site/site.env\n"
    "ExecStartPre=/usr/bin/python3 /opt/rosy/candidate/deploy/site/site-firewall.py check "
    "--compose-file /opt/rosy/candidate/deploy/site/compose.yaml\n"
    "ExecStart=/usr/bin/docker compose --project-name rosy-site --env-file /etc/rosy/site/site.env "
    "-f /opt/rosy/candidate/deploy/site/compose.yaml $ROSY_SITE_PAIRING_COMPOSE up -d --no-build\n"
    "ExecStop=/usr/bin/docker compose --project-name rosy-site --env-file /etc/rosy/site/site.env "
    "-f /opt/rosy/candidate/deploy/site/compose.yaml $ROSY_SITE_PAIRING_COMPOSE down\n"
)


def _symlinks_supported() -> bool:
    with tempfile.TemporaryDirectory() as folder:
        try:
            os.symlink(folder, Path(folder) / "link", target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


def _tag(commit: str) -> str:
    return f"site-{commit[:12]}"


def _image_id(commit: str, service: str) -> str:
    return 'sha256:' + hashlib.sha256(f'{commit}/{service}'.encode()).hexdigest()


def _bundle(commit: str, *, special: tarfile.TarInfo | None = None) -> dict[str, bytes]:
    manifest = json.dumps({"source_commit": commit}).encode() + b"\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name, data in {f"{commit}/release.json": manifest,
                           f"{commit}/images.tar": b"images " * 500,
                           f"{commit}/deploy/site/compose.yaml": b"services: {}\n"}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        if special is not None:
            archive.addfile(special)
    blob = buffer.getvalue()
    half = len(blob) // 2
    assets = {"release.json": manifest,
              f"rosy-site-candidate-{commit}.tar.part00": blob[:half],
              f"rosy-site-candidate-{commit}.tar.part01": blob[half:]}
    assets["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in assets.items()
    ).encode()
    assets["release.json.sig"] = b'{"signature_version":1}\n'
    return assets


def _release(commit: str, created: str, assets: dict[str, bytes], *, signed: bool = True,
             draft: bool = False) -> dict:
    tag = _tag(commit)
    names = [name for name in assets if signed or name != "release.json.sig"]
    return {"tag_name": tag, "created_at": created, "draft": draft, "assets": [
        {"name": name,
         "browser_download_url": f"https://github.com/{REPO}/releases/download/{tag}/{name}"}
        for name in names]}


class FakeHttp:
    def __init__(self, releases: list[dict], blobs: dict[str, dict[str, bytes]]):
        self.releases = releases
        self.blobs = blobs  # tag -> assets
        self.downloads: list[str] = []
        self.health = 200

    def _asset(self, url: str) -> bytes:
        tag, name = url.rsplit("/", 2)[-2:]
        return self.blobs[tag][name]

    def get(self, url: str, limit: int) -> bytes:
        if '/compare/' in url:
            base, head = url.rsplit('/', 1)[-1].split('...')
            commit = next((c for c in (OLD, NEW, NEWER) if head == _tag(c)), head)
            return json.dumps({'status': 'ahead' if commit > base else 'behind',
                               'merge_base_commit': {'sha': base}}).encode()
        if "api.github.com" in url:
            return json.dumps(self.releases if url.endswith("page=1") else []).encode()
        return self._asset(url)

    def download(self, url: str, destination: Path) -> str:
        self.downloads.append(url)
        data = self._asset(url)
        destination.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def status(self, url: str, ca_file) -> int:
        return self.health


class FakeHost:
    """systemctl + docker; the running tag follows site.env at each restart."""

    def __init__(self, paths: upd.Paths, *, unit: str = UNIT, healthy_tags=None,
                 config_image=None):
        self.paths = paths
        self.unit = unit
        self.healthy_tags = healthy_tags  # None: every tag is healthy
        self.config_image = config_image
        self.calls: list[list[str]] = []
        self.running = upd.read_env(paths.site_env)["ROSY_SITE_IMAGE_TAG"]
        self.images = {f"rosy-site-{s}:{OLD}" for s in upd.SERVICES} | {
            f"rosy-site-fleet:{'9' * 40}"}

    def _ok(self, stdout: str = "", code: int = 0) -> SimpleNamespace:
        return SimpleNamespace(returncode=code, stdout=stdout, stderr="")

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        if args[:2] == ["systemctl", "cat"]:
            return self._ok(self.unit)
        if args[:2] == ["systemctl", "restart"]:
            self.running = upd.read_env(self.paths.site_env)["ROSY_SITE_IMAGE_TAG"]
            return self._ok()
        if args[:2] == ["docker", "compose"]:
            if "config" in args:
                tag = kwargs["env"]["ROSY_SITE_IMAGE_TAG"]
                services = {s: {"image": f"rosy-site-{s}:{tag}"} for s in upd.SERVICES}
                if self.config_image:
                    services["fleet"]["image"] = self.config_image
                return self._ok(json.dumps({"services": services}))
            if "ps" in args:
                healthy = self.healthy_tags is None or self.running in self.healthy_tags
                return self._ok("\n".join(json.dumps({
                    "Service": s, "Image": f"rosy-site-{s}:{self.running}", "State": "running",
                    "ID": f'{s}-container',
                    "Health": "healthy" if healthy else "unhealthy"}) for s in upd.SERVICES))
        if args[:3] == ["docker", "image", "load"]:
            commit = Path(args[-1]).parent.name
            self.images |= {f"rosy-site-{s}:{commit}" for s in upd.SERVICES}
            return self._ok()
        if args[:3] == ["docker", "image", "ls"]:
            return self._ok("\n".join(sorted(self.images)))
        if args[:3] == ['docker', 'container', 'inspect']:
            service = args[-1].split('-')[0]
            return self._ok(_image_id(self.running, service))
        if args[:2] == ["docker", "ps"]:
            return self._ok("\n".join(f"rosy-site-{s}:{self.running}" for s in upd.SERVICES))
        if args[:3] == ["docker", "image", "rm"]:
            self.images.discard(args[3])
            return self._ok()
        raise AssertionError(f"unexpected command {args}")


def _verifier(calls):
    def verify(folder, *, trusted_key_id, trusted_public_key, runner, inspect_loaded_images):
        calls.append((Path(folder).name, inspect_loaded_images))
        if not (Path(folder) / "release.json.sig").is_file():
            raise upd.CandidateVerificationError("release signature is missing or unsafe")
        manifest = json.loads((Path(folder) / 'release.json').read_text())
        manifest['accepted_image_ids'] = {s: [_image_id(manifest['source_commit'], s)] for s in upd.SERVICES}
        return manifest
    return verify


@pytest.fixture
def host(tmp_path):
    if not _symlinks_supported():
        pytest.skip("needs symlinks (Linux site host; Windows without developer mode "
                    "cannot create them)")
    paths = upd.Paths(tmp_path)
    paths.site_env.parent.mkdir(parents=True)
    paths.site_env.write_text(f"# site\nROSY_SITE_IMAGE_TAG={OLD}\nROSY_SITE_CONFIG_DIR=/etc/x\n",
                              encoding="utf-8")
    paths.candidates.mkdir(parents=True)
    old = paths.candidates / OLD
    (old / "deploy/site").mkdir(parents=True)
    (old / "release.json").write_text(json.dumps({"source_commit": OLD}), encoding="utf-8")
    (old / 'release.json.sig').write_text('signed', encoding='utf-8')
    os.symlink(old, paths.link, target_is_directory=True)
    public = tmp_path / "site.pub.pem"
    public.write_text("pub", encoding="utf-8")
    config = {"repo": REPO, "key_id": "rosy-site-test-1", "public_key": public, "keep": 2,
              "health_url": "https://site.example.invalid:8443/healthz", "health_ca": None,
              "health_timeout_s": 30}
    return SimpleNamespace(paths=paths, config=config, root=tmp_path)


def _updater(host, http, fake, verify_calls=None, **kwargs):
    clock = iter(range(0, 100000, 10))
    return upd.SiteUpdater(host.config, paths=host.paths, runner=fake, http=http,
                           verifier=_verifier(verify_calls if verify_calls is not None else []),
                           sleep=lambda seconds: None, clock=lambda: next(clock), **kwargs)


def _world(*commits_created, signed=True):
    releases, blobs = [], {}
    for commit, created in commits_created:
        assets = _bundle(commit)
        blobs[_tag(commit)] = assets
        releases.append(_release(commit, created, assets, signed=signed))
    return releases, blobs


# -- selection ------------------------------------------------------------------

def test_selection_picks_the_newest_signed_newer_candidate(tmp_path):
    old_assets, new_assets, newer_assets = _bundle(OLD), _bundle(NEW), _bundle(NEWER)
    releases = [
        _release(OLD, "2026-10-04T01:00:00Z", old_assets),
        _release(NEW, "2026-10-04T02:00:00Z", new_assets),
        _release(NEWER, "2026-10-04T03:00:00Z", newer_assets, signed=False),
        {"tag_name": "payload-031", "created_at": "2026-10-04T04:00:00Z", "assets": []},
        {**_release("4" * 40, "2026-10-04T05:00:00Z", _bundle("4" * 40)), "draft": True},
    ]
    updater = upd.SiteUpdater({"repo": REPO}, paths=upd.Paths(tmp_path), runner=None,
                              http=FakeHttp([], {}))
    state = {"failed": {}}

    assert updater.select(releases, OLD, state)["tag_name"] == _tag(NEW)  # NEWER unsigned
    state["failed"][_tag(NEW)] = {"reason": "x"}
    assert updater.select(releases, OLD, state) is None                   # failed, never retried
    assert updater.select(releases, NEW, {"failed": {}}) is None           # already current
    # Never an older candidate than the one running.
    assert updater.select(releases[:1], NEW, {"failed": {}, "installed": {
        "created_at": "2026-10-04T02:00:00Z"}}) is None


# -- full runs ----------------------------------------------------------------

def test_success_switches_tag_link_and_state_then_prunes(host):
    releases, blobs = _world((OLD, "2026-10-04T01:00:00Z"), (NEW, "2026-10-04T02:00:00Z"))
    http = FakeHttp(releases, blobs)
    fake = FakeHost(host.paths)
    verify_calls = []
    stale = host.paths.candidates / ("8" * 40)
    stale.mkdir()
    os.utime(stale, (1, 1))

    assert _updater(host, http, fake, verify_calls).run() == upd.EXIT_OK

    target = host.paths.candidates / NEW
    assert Path(os.readlink(host.paths.link)) == target
    assert upd.read_env(host.paths.site_env)["ROSY_SITE_IMAGE_TAG"] == NEW
    assert "ROSY_SITE_CONFIG_DIR=/etc/x" in host.paths.site_env.read_text(encoding="utf-8")
    assert f"ROSY_SITE_IMAGE_TAG={OLD}" in host.paths.env_backup.read_text(encoding="utf-8")
    assert (target / "release.json.sig").is_file() and (target / "images.tar").is_file()
    assert verify_calls == [('candidate', True), (NEW, False), (NEW, True)]
    load = next(i for i, c in enumerate(fake.calls) if c[:3] == ["docker", "image", "load"])
    restart = next(i for i, c in enumerate(fake.calls) if c[:2] == ["systemctl", "restart"])
    assert load < restart
    state = json.loads(host.paths.state.read_text(encoding="utf-8"))
    assert state["installed"]["commit"] == NEW and state["last_run"]["result"] == "installed"
    # keep=2: new + previous stay, the stale folder and its unused image go.
    assert not stale.exists() and (host.paths.candidates / OLD).is_dir()
    assert f"rosy-site-fleet:{'9' * 40}" not in fake.images
    assert f"rosy-site-fleet:{OLD}" in fake.images
    assert not any(p.name.startswith(".staging") for p in host.paths.candidates.iterdir())

    # Next run: nothing newer.
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    assert json.loads(host.paths.state.read_text())["last_run"]["result"] == "idle"


def test_health_failure_rolls_back_and_records_the_tag(host):
    releases, blobs = _world((OLD, "2026-10-04T01:00:00Z"), (NEW, "2026-10-04T02:00:00Z"))
    http = FakeHttp(releases, blobs)
    fake = FakeHost(host.paths, healthy_tags={OLD})

    assert _updater(host, http, fake).run() == upd.EXIT_FAILED

    assert Path(os.readlink(host.paths.link)) == host.paths.candidates / OLD
    assert upd.read_env(host.paths.site_env)["ROSY_SITE_IMAGE_TAG"] == OLD
    assert fake.running == OLD
    assert [c[:2] for c in fake.calls].count(["systemctl", "restart"]) == 2
    state = json.loads(host.paths.state.read_text(encoding="utf-8"))
    assert _tag(NEW) in state["failed"] and "rollback healthy" in state["failed"][_tag(NEW)]["reason"]
    assert state["last_run"]["result"] == "rolled-back"
    # Failed tags are never retried automatically.
    downloads = len(http.downloads)
    assert _updater(host, http, fake).run() == upd.EXIT_OK
    assert len(http.downloads) == downloads


def test_relative_active_link_rolls_back_to_its_actual_previous_folder(host):
    host.paths.link.unlink()
    os.symlink(Path('candidates') / OLD, host.paths.link, target_is_directory=True)
    releases, blobs = _world((NEW, '2026-10-04'))
    fake = FakeHost(host.paths, healthy_tags={OLD})
    updater = _updater(host, FakeHttp(releases, blobs), fake)
    assert updater.run() == upd.EXIT_FAILED
    assert host.paths.link.resolve() == host.paths.candidates / OLD
    assert fake.running == OLD
    assert 'switch' not in updater.load_state()


def test_healthz_failure_alone_also_rolls_back(host):
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    http = FakeHttp(releases, blobs)
    http.health = 502
    fake = FakeHost(host.paths)

    assert _updater(host, http, fake).run() == upd.EXIT_FAILED
    assert upd.read_env(host.paths.site_env)["ROSY_SITE_IMAGE_TAG"] == OLD
    state = json.loads(host.paths.state.read_text())
    assert state['switch']['current'] == OLD  # retry recovery until old stack is healthy
    assert state['failed'] == {}


@pytest.mark.parametrize("variant", ["config-image", "unit-file", "pairing", "compose-file"])
def test_image_override_is_refused_without_any_change(host, variant):
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    http = FakeHttp(releases, blobs)
    unit = UNIT
    if variant == "unit-file":
        unit = UNIT.replace("$ROSY_SITE_PAIRING_COMPOSE up",
                            "-f /etc/rosy/site/pin.yaml $ROSY_SITE_PAIRING_COMPOSE up")
    if variant in {"pairing", "compose-file"}:
        line = ("ROSY_SITE_PAIRING_COMPOSE=-f /etc/rosy/site/pin.yaml\n" if variant == "pairing"
                else "COMPOSE_FILE=/etc/rosy/site/pin.yaml\n")
        with host.paths.site_env.open("a", encoding="utf-8") as stream:
            stream.write(line)
    env_before = host.paths.site_env.read_bytes()
    fake = FakeHost(host.paths, unit=unit,
                    config_image="rosy-site-fleet:pinned" if variant == "config-image" else None)

    assert _updater(host, http, fake).run() == upd.EXIT_FAILED

    assert host.paths.site_env.read_bytes() == env_before
    assert Path(os.readlink(host.paths.link)) == host.paths.candidates / OLD
    assert http.downloads == []
    assert not any(c[:2] == ["systemctl", "restart"] for c in fake.calls)
    state = json.loads(host.paths.state.read_text(encoding="utf-8"))
    assert state["last_run"]["result"] == "refused" and state["failed"] == {}


def test_pairing_overlay_from_the_candidate_is_allowed(host):
    with host.paths.site_env.open("a", encoding="utf-8") as stream:
        stream.write("ROSY_SITE_PAIRING_COMPOSE=-f "
                     "/opt/rosy/candidate/deploy/site/compose.pairing.yaml\n")
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    assert _updater(host, FakeHttp(releases, blobs), FakeHost(host.paths)).run() == upd.EXIT_OK


def test_real_candidate_directory_is_migrated_once_to_a_symlink(host):
    host.paths.link.unlink()
    old = host.paths.candidates / OLD
    old.rename(host.paths.link)  # the pre-D-441 layout: a real directory
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    fake = FakeHost(host.paths, healthy_tags={OLD})

    assert _updater(host, FakeHttp(releases, blobs), fake).run() == upd.EXIT_FAILED

    # Migrated, then rolled back onto the migrated folder.
    assert host.paths.link.is_symlink()
    assert Path(os.readlink(host.paths.link)) == host.paths.candidates / OLD
    assert (host.paths.candidates / OLD / "release.json").is_file()


def test_missing_first_install_is_refused(host):
    host.paths.link.unlink()
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    http = FakeHttp(releases, blobs)

    assert _updater(host, http, FakeHost(host.paths)).run() == upd.EXIT_FAILED
    assert http.downloads == []


def test_tampered_part_or_link_member_is_rejected_before_load(host):
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    link = tarfile.TarInfo(f"{NEW}/evil")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    evil = _bundle(NEW, special=link)
    blobs[_tag(NEW)] = evil
    releases = [_release(NEW, "2026-10-04T02:00:00Z", evil)]
    fake = FakeHost(host.paths)

    assert _updater(host, FakeHttp(releases, blobs), fake).run() == upd.EXIT_FAILED
    assert not any(c[:3] == ["docker", "image", "load"] for c in fake.calls)
    reason = json.loads(host.paths.state.read_text())["failed"][_tag(NEW)]["reason"]
    assert "non-regular archive member" in reason

    tampered = _bundle(NEWER)
    tampered[f"rosy-site-candidate-{NEWER}.tar.part01"] += b"x"
    world = FakeHttp([_release(NEWER, "2026-10-04T03:00:00Z", tampered)], {_tag(NEWER): tampered})
    assert _updater(host, world, fake).run() == upd.EXIT_FAILED
    assert "does not match SHA256SUMS" in json.loads(
        host.paths.state.read_text())["failed"][_tag(NEWER)]["reason"]
    assert not (host.paths.candidates / NEWER).exists()


def test_dry_run_changes_nothing(host):
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    http = FakeHttp(releases, blobs)
    fake = FakeHost(host.paths)
    env_before = host.paths.site_env.read_bytes()

    assert _updater(host, http, fake, dry_run=True).run() == upd.EXIT_OK
    assert http.downloads == [] and host.paths.site_env.read_bytes() == env_before
    assert json.loads(host.paths.state.read_text())["last_run"]["result"] == "dry-run"


def test_a_second_run_stops_while_the_lock_is_held(host):
    releases, blobs = _world((NEW, "2026-10-04T02:00:00Z"))
    http = FakeHttp(releases, blobs)
    with upd.run_lock(host.paths.lock):
        assert _updater(host, http, FakeHost(host.paths)).run() == upd.EXIT_LOCKED
    assert http.downloads == []


def test_config_requires_https_health_and_known_keys(tmp_path):
    public = tmp_path / "k.pem"
    public.write_text("pub", encoding="utf-8")
    good = {"repo": REPO, "key_id": "rosy-site-1", "public_key": str(public),
            "health_url": "https://site.example.invalid:8443/healthz"}
    path = tmp_path / "autoupdate.conf"
    path.write_text(json.dumps(good), encoding="utf-8")
    assert upd.load_config(path)["keep"] == 3
    for bad, message in (({"health_url": "http://x/healthz"}, "https"),
                         ({"token": "x"}, "unknown"), ({"keep": 1}, "keep")):
        path.write_text(json.dumps({**good, **bad}), encoding="utf-8")
        with pytest.raises(upd.ConfigError, match=message):
            upd.load_config(path)


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "deploy" / "site"


def test_units_run_the_installed_updater_on_a_persistent_randomized_timer():
    service = (SITE / "rosy-site-autoupdate.service").read_text(encoding="utf-8")
    timer = (SITE / "rosy-site-autoupdate.timer").read_text(encoding="utf-8")

    assert ("ExecStart=/usr/bin/python3 -I /usr/local/lib/rosy-site/rosy_site_autoupdate.py run"
            in service)
    assert "/opt/rosy/candidate/" not in service  # never runs code from the candidate
    assert "Type=oneshot" in service and "NoNewPrivileges=yes" in service
    assert "ProtectSystem=full" in service
    assert "ReadWritePaths=/etc/rosy/site /opt/rosy /var/lib/rosy /run/lock" in service
    assert "OnCalendar=*:0/15" in timer and "RandomizedDelaySec=" in timer
    assert "Persistent=true" in timer and "WantedBy=timers.target" in timer


def test_runbook_explains_install_pause_and_manual_rollback():
    readme = (SITE / "README.md").read_text(encoding="utf-8")
    section = readme[readme.index("### Automatic updates (D-441)"):
                     readme.index("### Backup and restore operations")]

    for needle in ("register_auto_sign_task.ps1", "Disable-ScheduledTask",
                   "systemctl disable --now rosy-site-autoupdate.timer", "forget-failed",
                   "--source-ref refs/heads/main", "/usr/local/lib/rosy-site/",
                   "ln -sfn /opt/rosy/candidates/<previous-commit>", "D-412"):
        assert needle in section, needle


def test_recent_rebuild_of_older_commit_is_not_selected(tmp_path):
    releases, blobs = _world((OLD, '2099-01-01'), (NEWER, '2026-10-04'))
    updater = upd.SiteUpdater({'repo': REPO}, paths=upd.Paths(tmp_path), http=FakeHttp(releases, blobs))
    assert updater.select(releases, NEW, {'failed': {}})['tag_name'] == _tag(NEWER)


def test_restart_timeout_restores_previous_stack(host):
    import subprocess
    releases, blobs = _world((NEW, '2026-10-04'))
    fake = FakeHost(host.paths)

    def runner(args, **kwargs):
        if args[:2] == ['systemctl', 'restart'] and upd.read_env(host.paths.site_env)['ROSY_SITE_IMAGE_TAG'] == NEW:
            raise subprocess.TimeoutExpired(args, 300)
        return fake(args, **kwargs)
    assert _updater(host, FakeHttp(releases, blobs), runner).run() == upd.EXIT_FAILED
    assert upd.read_env(host.paths.site_env)['ROSY_SITE_IMAGE_TAG'] == OLD
    assert host.paths.link.resolve() == host.paths.candidates / OLD
    assert fake.running == OLD


def test_interrupted_switch_is_undone_before_network_access(host):
    import shutil
    updater = _updater(host, FakeHttp([], {}), FakeHost(host.paths))
    shutil.copy2(host.paths.site_env, host.paths.env_backup)
    target = host.paths.candidates / NEW
    target.mkdir()
    upd.write_env_tag(host.paths.site_env, NEW)
    upd.swap_link(host.paths.link, target)
    updater.save_state({'failed': {}, 'switch': {'previous': str(host.paths.candidates / OLD),
                        'current': OLD, 'commit': NEW, 'tag': _tag(NEW)}})
    assert updater.run() == upd.EXIT_FAILED
    assert host.paths.link.resolve() == host.paths.candidates / OLD
    assert upd.read_env(host.paths.site_env)['ROSY_SITE_IMAGE_TAG'] == OLD
    assert 'switch' not in updater.load_state()


def test_verifier_commit_must_match_candidate_directory(host):
    updater = _updater(host, FakeHttp([], {}), FakeHost(host.paths))
    updater.verifier = lambda *args, **kwargs: {'source_commit': NEW}
    with pytest.raises(upd.Rejected, match='commit'):
        updater._verify(host.paths.candidates / OLD, loaded=False)


@pytest.mark.parametrize('mismatch', ['backup', 'candidate'])
def test_recovery_refuses_mismatched_rollback_evidence(host, mismatch):
    updater = _updater(host, FakeHttp([], {}), FakeHost(host.paths))
    shutil.copy2(host.paths.site_env, host.paths.env_backup)
    target = host.paths.candidates / NEW
    target.mkdir()
    upd.write_env_tag(host.paths.site_env, NEW)
    upd.swap_link(host.paths.link, target)
    updater.save_state({'failed': {}, 'switch': {'previous': str(host.paths.candidates / OLD),
                        'current': OLD, 'commit': NEW, 'tag': _tag(NEW)}})
    if mismatch == 'backup':
        upd.write_env_tag(host.paths.env_backup, NEW)
    else:
        updater.verifier = lambda *args, **kwargs: {'source_commit': NEW}
    assert updater.run() == upd.EXIT_FAILED
    assert host.paths.link.resolve() == target
    assert upd.read_env(host.paths.site_env)['ROSY_SITE_IMAGE_TAG'] == NEW
    assert 'switch' in updater.load_state()


def test_prune_does_not_remove_images_when_container_listing_fails(host):
    fake = FakeHost(host.paths)

    def runner(args, **kwargs):
        if args[:2] == ['docker', 'ps']:
            return fake._ok(code=1)
        return fake(args, **kwargs)
    updater = _updater(host, FakeHttp([], {}), runner)
    with pytest.raises(upd.Transient):
        updater.prune({host.paths.candidates / OLD})
    assert not any(c[:3] == ['docker', 'image', 'rm'] for c in fake.calls)


def test_http_body_timeout_is_transient():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, *args):
            raise TimeoutError('body stalled')
    http = upd.Http()
    http._open = lambda url: Response()
    with pytest.raises(upd.Transient):
        http.get('https://example.invalid', 100)


def test_diverged_history_is_not_an_upgrade(tmp_path):
    releases, blobs = _world((NEW, '2026-10-04'))
    http = FakeHttp(releases, blobs)
    http.get = lambda *args: json.dumps({'status': 'ahead', 'merge_base_commit': {'sha': '9' * 40}}).encode()
    updater = upd.SiteUpdater({'repo': REPO}, http=http)
    assert updater.select(releases, OLD, {'failed': {}}) is None


def test_running_env_must_match_signed_manifest(host):
    upd.write_env_tag(host.paths.site_env, NEW)
    updater = _updater(host, FakeHttp([], {}), FakeHost(host.paths))
    assert updater.run() == upd.EXIT_FAILED
    assert updater.load_state()['last_run']['result'] == 'refused'


def test_prune_preserves_images_for_renamed_rollback_folder(host):
    prior_commit = '9' * 40
    prior = host.paths.candidates / 'prev-migrated'
    prior.mkdir()
    (prior / 'release.json').write_text(json.dumps({'source_commit': prior_commit}))
    fake = FakeHost(host.paths)
    _updater(host, FakeHttp([], {}), fake).prune({host.paths.candidates / OLD, prior})
    assert f'rosy-site-fleet:{prior_commit}' in fake.images


def test_failed_rollback_is_retried_before_new_update(host):
    releases, blobs = _world((NEW, '2026-10-04'))
    fake = FakeHost(host.paths)

    def unavailable(args, **kwargs):
        if args[:2] == ['systemctl', 'restart']:
            return fake._ok(code=1)
        return fake(args, **kwargs)
    updater = _updater(host, FakeHttp(releases, blobs), unavailable)
    assert updater.run() == upd.EXIT_FAILED
    assert updater.load_state()['switch']['current'] == OLD
    recovered = _updater(host, FakeHttp([], {}), fake)
    assert recovered.run() == upd.EXIT_FAILED
    assert recovered.load_state()['last_run']['result'] == 'recovered'
    assert 'switch' not in recovered.load_state()
    assert fake.running == OLD


def test_interrupted_directory_migration_is_recoverable(host, monkeypatch):
    host.paths.link.unlink()
    (host.paths.candidates / OLD).rename(host.paths.link)
    releases, blobs = _world((NEW, '2026-10-04'))
    fake = FakeHost(host.paths)
    original = upd.swap_link

    def fail_swap(*args):
        raise OSError('migration interrupted')

    monkeypatch.setattr(upd, 'swap_link', fail_swap)
    updater = _updater(host, FakeHttp(releases, blobs), fake)
    assert updater.run() == upd.EXIT_FAILED
    assert updater.load_state()['switch']['current'] == OLD
    monkeypatch.setattr(upd, 'swap_link', original)
    assert _updater(host, FakeHttp([], {}), fake).run() == upd.EXIT_FAILED
    assert host.paths.link.resolve() == host.paths.candidates / OLD


def test_installed_cli_loads_only_its_reviewed_modules(tmp_path):
    for name in ('rosy_site_autoupdate.py', 'site_update_io.py', 'verify_candidate.py',
                 'candidate_signing.py'):
        shutil.copy2(SITE / name, tmp_path / name)
    command = [sys.executable, '-I', str(tmp_path / 'rosy_site_autoupdate.py'), '--help']
    result = subprocess.run(command, capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    (tmp_path / 'site_update_io.py').unlink()
    # Missing reviewed helper must fail; never fall back to checkout/candidate code.
    assert subprocess.run(command, capture_output=True, cwd=tmp_path).returncode != 0


def test_running_newer_stack_is_not_downgraded_when_env_is_stale(host):
    releases, blobs = _world((NEW, '2026-10-04'))
    fake = FakeHost(host.paths)
    fake.running = NEWER
    http = FakeHttp(releases, blobs)
    assert _updater(host, http, fake).run() == upd.EXIT_FAILED
    assert fake.running == NEWER and http.downloads == []
    assert not any(c[:2] == ['systemctl', 'restart'] for c in fake.calls)


def test_running_container_identity_must_match_signed_candidate(host):
    releases, blobs = _world((NEW, '2026-10-04'))
    fake = FakeHost(host.paths)

    def runner(args, **kwargs):
        if args[:3] == ['docker', 'container', 'inspect']:
            return fake._ok(_image_id(NEWER, 'fleet'))
        return fake(args, **kwargs)

    http = FakeHttp(releases, blobs)
    assert _updater(host, http, runner).run() == upd.EXIT_FAILED
    assert http.downloads == []


@pytest.mark.parametrize('content', ['{', '[]', '{"switch": null}', '{"switch": {}}'])
def test_corrupt_journal_is_preserved_and_blocks_update(tmp_path, content):
    paths = upd.Paths(tmp_path)
    paths.state.parent.mkdir(parents=True)
    paths.state.write_text(content)
    updater = upd.SiteUpdater({}, paths=paths)
    updater._update = lambda state: upd.EXIT_OK
    assert updater.run() == upd.EXIT_FAILED
    assert paths.state.read_text() == content


def test_unreadable_journal_is_not_treated_as_empty(tmp_path, monkeypatch):
    paths = upd.Paths(tmp_path)
    original = Path.read_text

    def denied(path, *args, **kwargs):
        if path == paths.state:
            raise PermissionError('journal unreadable')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', denied)
    with pytest.raises(upd.Refused):
        upd.SiteUpdater({}, paths=paths).load_state()


def test_forget_failed_obeys_update_lock(tmp_path, monkeypatch):
    paths = upd.Paths(tmp_path)
    paths.state.parent.mkdir(parents=True)
    content = json.dumps({'failed': {_tag(NEW): {'reason': 'test'}}})
    paths.state.write_text(content)
    monkeypatch.setattr(upd, 'Paths', lambda: paths)
    monkeypatch.setattr(upd, 'load_config', lambda path: {})
    with upd.run_lock(paths.lock):
        assert upd.main(['forget-failed', _tag(NEW)]) == upd.EXIT_LOCKED
    assert paths.state.read_text() == content


@pytest.mark.parametrize('operation', ['get', 'download'])
def test_truncated_http_body_is_retryable(tmp_path, operation):
    import http.client

    class Socket:
        def makefile(self, *args):
            return io.BytesIO(b'HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nabc')

    response = http.client.HTTPResponse(Socket())
    response.begin()
    client = upd.Http()
    client._open = lambda url: response
    with pytest.raises(upd.Transient):
        if operation == 'get':
            client.get('https://example.invalid', 100)
        else:
            client.download('https://example.invalid', tmp_path / 'download')
