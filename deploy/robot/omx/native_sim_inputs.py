"""File bindings shared by the unprivileged native simulation deployment and job."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re

RUN_ID = re.compile(r"([0-9a-f]{40})-([0-9a-f]{12})")
CAPS = {"ai": (4, 4), "model": (8, 6)}
MUTABLE = {"manifest.json", "start-intent.json", "run-intent.json", "exit.json",
           "budget.resv", "budget.lock", "home", "tmp", "logs", "cache", "g2", "pick-place"}


def run_identity(value):
    match = RUN_ID.fullmatch(value)
    if match is None:
        raise ValueError("run_id must bind SHA40 and nonce12")
    return match.group(1)


def write_json(path, value):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    result = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def inventory(root, *, absolute=False, exclude=()):
    """Hash the exact visible inventory, including SDK symlink targets and new files."""
    root = Path(root).absolute()
    if not root.exists():
        raise ValueError("input drift: missing root " + str(root))
    if root.is_file():
        return {str(root) if absolute else root.name: digest(root)}
    result, ancestors = {}, set()
    def visit(directory):
        resolved = directory.resolve()
        if resolved in ancestors:
            raise ValueError("input drift: dependency symlink cycle")
        ancestors.add(resolved)
        try:
            for path in sorted(directory.iterdir()):
                relative = path.relative_to(root)
                if (relative.parts[0] in exclude or path.name in {"__pycache__", ".git"}
                        or path.suffix in {".pyc", ".pyo"}):
                    continue
                if path.is_dir():
                    visit(path)
                elif path.is_file():
                    result[str(path) if absolute else relative.as_posix()] = digest(path)
                else:
                    raise ValueError("input drift: unsupported or dangling input " + str(path))
        finally:
            ancestors.remove(resolved)
    visit(root)
    return result


def verify_inventory(root, expected, *, absolute=False, exclude=()):
    if inventory(root, absolute=absolute, exclude=exclude) != expected:
        raise ValueError("input drift: " + str(root))


def dependency_inventory(roots):
    result = {}
    for root in roots:
        result.update(inventory(root, absolute=True))
    return result


def load_config(path):
    config = read_json(path)
    if config.get("schema") != "rosy.omx-native-sim-host/1":
        raise ValueError("unsupported native simulation host schema")
    if config.get("role") not in CAPS:
        raise ValueError("native simulation role must be ai or model")
    required = {"schema", "role", "ros_setup", "overlay", "python_site"}
    if not required <= config.keys() or config.keys() - required - {
            "dependency_prefix", "policy_input", "inference_python_sites"}:
        raise ValueError("unexpected native SDK config keys")
    if ('policy_input' in config) != ('inference_python_sites' in config):
        raise ValueError('policy and inference dependencies must be explicit together')
    for key in ("ros_setup", "overlay", "python_site", "dependency_prefix", "policy_input"):
        if key not in config:
            continue
        value = config[key]
        if not isinstance(value, str) or not Path(value).is_absolute() or "\n" in value or "\x00" in value:
            raise ValueError("SDK paths must be absolute: " + key)
        config[key] = str(Path(value).resolve(strict=True))
    if not Path(config["ros_setup"]).is_file() or not (Path(config["overlay"]) / "setup.bash").is_file():
        raise ValueError("ROS and overlay setup files are required")
    if not Path(config["python_site"]).is_dir():
        raise ValueError("python_site must be a directory")
    if 'policy_input' in config:
        sites=config['inference_python_sites']
        if (not isinstance(sites,list) or len(sites)!=2 or len(set(sites))!=2
                or any(not isinstance(p,str) or not Path(p).is_absolute()
                       or any(c in p for c in ('\n','\x00',':')) or not Path(p).is_dir() for p in sites)
                or any(not (Path(config['policy_input'])/name).is_file()
                       for name in ('policy-artifact.json','campaign.json'))):
            raise ValueError('pinned policy/campaign and two explicit inference sites required')
        config['inference_python_sites']=[str(Path(p).resolve(strict=True)) for p in sites]
    return config


def verify_bindings(document, source, state):
    revision = run_identity(document["run_id"])
    if document.get("revision") != revision or document.get("role") not in CAPS:
        raise ValueError("native run identity mismatch")
    if document.get("sdk_status") != "PASS":
        raise ValueError("SDK preflight did not pass")
    verify_inventory(source, document["source_hashes"])
    if dependency_inventory(document["dependency_roots"]) != document["dependency_hashes"]:
        raise ValueError("dependency input drift")
    verify_inventory(state, document["state_hashes"], exclude=MUTABLE)
