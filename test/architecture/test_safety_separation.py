"""D-430 safety as a separate concern: §1 tagging and §3 separation invariants.

Safety-tagged files are the Python files under a ``concern: safety`` root plus the
``safety_modules`` list in ``tools/harness/platform_parts.yaml``. Each test says
whether it is structural (static AST over tracked files) or behavioural. The
behavioural invariants 3b and 4 need ``core_features`` on ``sys.path`` and live in
``src/runtime/services/test/test_safety_behaviour.py``.

KNOWN_SAFETY_VIOLATIONS is checked by set equality like ``KNOWN_VIOLATIONS`` in
``test_platform_parts.py``: a new edge fails, a listed edge that no longer occurs
fails, so the list only shrinks. The Fleet stop-path carve (D-430 Validation wave 0
item 2) removes the mixed-file entries.

Honest holes, not oversights:
- Only static ``import`` / ``from`` statements are seen, as in test_platform_parts.
- A module counts only when it lies under a root's ``import_prefix``; script
  folders without one are invisible to the import rules.
- Invariant 3a sees ``create_publisher`` topic literals, module constants named
  in that argument, and ``declare_parameter`` defaults. A topic built at run time
  or remapped in launch is review-only (D-430 §3 invariant 3).
"""

import ast
import functools
from pathlib import PurePosixPath

from test_platform_parts import ROOT, _is_test_file, _owner, _package_of, _tracked
from test_platform_parts import _manifest as _read_manifest

SAFETY = "safety"

#: One parse per session; the tests below only read it.
_manifest = functools.lru_cache(maxsize=1)(_read_manifest)


@functools.lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    """Dotted module name -> tracked path, for production files under an import_prefix."""
    roots = _manifest()["roots"]
    modules: dict[str, str] = {}
    for path in _tracked():
        if not path.endswith(".py") or _is_test_file(path):
            continue
        root = _owner(path, roots)
        if root is None or not root.get("import_prefix"):
            continue
        package = _package_of(path, root)
        stem = PurePosixPath(path).stem
        module = package if stem == "__init__" else ".".join(p for p in (package, stem) if p)
        if any(module == prefix or module.startswith(prefix + ".") for prefix in root["import_prefix"]):
            modules[module] = path
    return modules


def _module_of(name: str) -> str | None:
    """Longest indexed module that ``name`` starts with."""
    index = _index()
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in index:
            return candidate
    return None


@functools.lru_cache(maxsize=None)
def _concern_of(path: str) -> str | None:
    manifest = _manifest()
    if path in manifest["safety_modules"]:
        return SAFETY
    root = _owner(path, manifest["roots"])
    return None if root is None else root["concern"]


@functools.lru_cache(maxsize=None)
def _tree(path: str) -> ast.Module:
    return ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))


def _find(node: ast.AST, name: str) -> ast.AST | None:
    """First definition or assignment of ``name`` under ``node``, nested ones included."""
    for child in ast.walk(node):
        if child is node:
            continue
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child.name == name:
            return child
        targets = (child.targets if isinstance(child, ast.Assign)
                   else [child.target] if isinstance(child, ast.AnnAssign) else [])
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return child
    return None


def _resolve_symbol(symbol: str) -> tuple[str | None, ast.AST | None]:
    """(defining path, node) of a dotted ``module.Symbol[.nested]`` anchor."""
    module = _module_of(symbol)
    if module is None or module == symbol:
        return None, None
    path = _index()[module]
    node: ast.AST | None = _tree(path)
    for name in symbol[len(module) + 1:].split("."):
        node = _find(node, name) if node is not None else None
    return path, node


@functools.lru_cache(maxsize=1)
def _safety_files() -> list[str]:
    return sorted(path for path in _tracked()
                  if path.endswith(".py") and not _is_test_file(path) and _concern_of(path) == SAFETY)


def test_safety_anchors_live_in_safety_tagged_files():
    """Structural. D-430 §1 drift guard: every symbol anchor (module-qualified, nested
    definitions included) and string anchor resolves inside a safety-tagged file, and
    every safety module and Python safety root holds at least one anchor."""
    manifest = _manifest()
    tracked = set(_tracked())
    problems = [f"safety_modules entry is not a tracked .py file: {path}"
                for path in manifest["safety_modules"] if path not in tracked or not path.endswith(".py")]
    anchored = set()
    for anchor in manifest["safety_anchors"]:
        if "string" in anchor:
            path, node = _resolve_symbol(anchor["in"])
            found = node is not None and any(
                isinstance(child, ast.Constant) and child.value == anchor["string"] for child in ast.walk(node))
            label = f"string {anchor['string']!r} in {anchor['in']}"
        else:
            path, node = _resolve_symbol(anchor["symbol"])
            found = node is not None
            label = anchor["symbol"]
        if not found:
            problems.append(f"anchor does not resolve: {label}")
        elif _concern_of(path) != SAFETY:
            problems.append(f"anchor {label} lives in {path}, which is not safety-tagged")
        else:
            anchored.add(path)
    problems += [f"safety module has no anchor: {path}"
                 for path in manifest["safety_modules"] if path not in anchored]
    for root in manifest["roots"]:
        if root["concern"] != SAFETY:
            continue
        files = [path for path in _safety_files() if _owner(path, manifest["roots"]) is root]
        if files and not anchored & set(files):
            problems.append(f"safety root has Python files but no anchor: {root['path']}")
    assert problems == [], problems
    assert len(anchored) >= len(manifest["safety_modules"]) + 1


# --- D-430 §3 invariants 1 and 2 ---------------------------------------------

#: Model SDKs and the training stack safety code may not import (invariant 1).
MODEL_SDKS = ("google.genai", "google.generativeai", "anthropic", "openai", "lerobot", "torch", "onnxruntime")
GUARDED = ("decision", "learning")


def _import_refs(path: str) -> list[tuple[str, str | None]]:
    """(module, imported name or None) per static import, relative ones resolved."""
    root = _owner(path, _manifest()["roots"])
    package = _package_of(path, root).split(".") if root is not None else []
    refs = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            refs += [(alias.name, None) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = package[:max(0, len(package) - node.level + 1)] if node.level else []
            module = ".".join([*base, *(node.module.split(".") if node.module else [])])
            for alias in node.names:
                qualified = f"{module}.{alias.name}" if module else alias.name
                if qualified in _index():
                    refs.append((qualified, None))  # `from pkg import submodule`
                elif alias.name != "*":
                    refs.append((module, alias.name))
    return refs


def _public() -> tuple[set[str], set[str]]:
    """(public names, owners of public names): a class or function holding a public
    method or nested handler is importable so the caller can reach it."""
    names = {anchor.get("symbol") or f"{anchor['in']}.{anchor['string']}"
             for anchor in _manifest()["safety_anchors"] if anchor.get("public")}
    owners = {".".join(name.split(".")[:end]) for name in names for end in range(1, name.count(".") + 1)}
    return names, owners


@functools.lru_cache(maxsize=1)
def _separation_edges() -> tuple[dict[tuple[str, str, str], str], dict[str, int]]:
    """Violations keyed (rule, importer path, imported module or symbol), and how many
    importers / resolved import edges each rule checked."""
    manifest = _manifest()
    roots = manifest["roots"]
    public, owners = _public()
    violations: dict[tuple[str, str, str], str] = {}
    checked = {"rule1_files": 0, "rule1_edges": 0, "rule2_files": 0, "rule2_edges": 0,
               "rule2_robot_files": 0}
    for path in _tracked():
        if not path.endswith(".py") or _is_test_file(path):
            continue
        concern = _concern_of(path)
        if concern not in (SAFETY, *GUARDED):
            continue
        checked["rule1_files" if concern == SAFETY else "rule2_files"] += 1
        if concern != SAFETY and _owner(path, roots)["part"] == "middleware":
            checked["rule2_robot_files"] += 1
        for module, name in _import_refs(path):
            full = f"{module}.{name}" if name else module
            if concern == SAFETY and any(full == sdk or full.startswith(sdk + ".") for sdk in MODEL_SDKS):
                violations[("1", path, full)] = "model SDK"
                continue
            target = _module_of(full)
            if target is None:
                continue
            target_path = _index()[target]
            target_concern = _concern_of(target_path)
            target_root = _owner(target_path, roots)
            if concern == SAFETY:
                checked["rule1_edges"] += 1
                models = target_root["part"] == "integrations" and _under_kind(target_root, "models")
                if target_concern in GUARDED or models:
                    violations[("1", path, target)] = f"safety -> {target_concern}"
            elif target_concern == SAFETY:
                checked["rule2_edges"] += 1
                if name is None:
                    violations[("2", path, target)] = "whole safety module"
                elif full not in public and full not in owners:
                    violations[("2", path, full)] = "safety internal"
    return violations, checked


def _under_kind(root: dict, kind: str) -> bool:
    integration = root.get("integration", "")
    return integration == kind or integration.startswith(kind + "/")


#: Frozen D-430 §3 edges as (rule, importer, imported module or symbol) -> reason.
#: Rule "1": safety imports decision/learning. Rule "2": decision/learning imports a
#: safety internal. Shrink-only; the Fleet stop-path carve removes the mixed files.
KNOWN_SAFETY_VIOLATIONS = {
    # safety -> decision, cancel_all.py
    ("1", "src/site/fleet/fleet/server/cancel_all.py", "fleet.server.console_view"): "error text helper",
    ("1", "src/site/fleet/fleet/server/cancel_all.py", "fleet.swarm.transport"): "RobotApiError",
    # mixed file console.py (estop_all) -> decision
    ("1", "src/site/fleet/fleet/server/console.py", "fleet.formation.geometry"): "mixed file",
    ("1", "src/site/fleet/fleet/server/console.py", "fleet.hub.hub"): "mixed file",
    ("1", "src/site/fleet/fleet/server/console.py", "fleet.localization.trust"): "mixed file",
    ("1", "src/site/fleet/fleet/server/console.py", "fleet.server.bays"): "mixed file",
    ("1", "src/site/fleet/fleet/server/console.py", "fleet.server.console_view"): "mixed file",
    ("1", "src/site/fleet/fleet/server/console.py", "fleet.server.traffic"): "mixed file",
    ("1", "src/site/fleet/fleet/server/console.py", "fleet.swarm.robots"): "mixed file",
    ("1", "src/site/fleet/fleet/server/console.py", "fleet.swarm.session"): "mixed file",
    ("1", "src/site/fleet/fleet/server/console.py", "fleet.swarm.transport"): "mixed file",
    # mixed file task_dispatch_routes.py (rearm handler) -> decision
    ("1", "src/site/fleet/fleet/server/task_dispatch_routes.py", "fleet.hub.hub"): "mixed file",
    ("1", "src/site/fleet/fleet/server/task_dispatch_routes.py", "fleet.server.http_errors"): "mixed file",
    ("1", "src/site/fleet/fleet/server/task_dispatch_routes.py", "fleet.server.site_auth"): "mixed file",
    ("1", "src/site/fleet/fleet/server/task_dispatch_routes.py", "fleet.server.task_store"): "mixed file",
    ("1", "src/site/fleet/fleet/server/task_dispatch_routes.py", "fleet.swarm.transport"): "mixed file",
    # decision -> safety internals
    ("2", "src/site/fleet/fleet/server/task_store.py", "fleet.server.cancel_all_store.ensure_schema"): (
        "schema setup behind the store"),
    ("2", "src/site/fleet/fleet/server/cell_job_store.py", "fleet.server.dispatch_admission.normalize_resources"): (
        "resource normalisation before reserve"),
    # app assembly imports non-anchor names of the mixed task_dispatch_routes.py
    # (missing from the D-430 §3 grep)
    ("2", "src/site/fleet/fleet/server/app.py", "fleet.server.task_dispatch_routes.GoalRequest"): (
        "request model re-export"),
    ("2", "src/site/fleet/fleet/server/app.py", "fleet.server.task_dispatch_routes.cancel_pending_task_queue"): (
        "queue cancel helper"),
    ("2", "src/site/fleet/fleet/server/app.py", "fleet.server.task_dispatch_routes.fanout_local_omx_stops"): (
        "OMX local stop fan-out; a public entry point once the stop path is carved"),
}


def _frozen(rule: str) -> tuple[list, list]:
    violations, _ = _separation_edges()
    actual = {key for key in violations if key[0] == rule}
    known = {key for key in KNOWN_SAFETY_VIOLATIONS if key[0] == rule}
    return sorted(actual - known), sorted(known - actual)


def test_safety_does_not_import_decision_learning_or_model_sdks():
    """Structural. D-430 §3 invariant 1, against the frozen list: (new, stale)."""
    assert _frozen("1") == ([], [])


def test_decision_and_learning_use_only_safety_public_api():
    """Structural. D-430 §3 invariant 2: decision/learning code imports from safety
    files only ``public: true`` anchors (or the class/function that owns one),
    never a whole safety module; against the frozen list: (new, stale)."""
    assert _frozen("2") == ([], [])


# --- D-430 §3 invariant 3a ---------------------------------------------------

#: Paths outside the production scope, by reason. Listed, not pattern-matched, so a
#: new exception cannot appear silently. ``test``/``tests`` folders are out as well:
#: they build fake graphs (e.g. gateway test_absorption_output_graph.py).
CMD_VEL_SCOPE_EXCLUDED = {
    "src/runtime/sensing/tools/gz/": "Gazebo bench driver; drives the sim robot, never a device run path",
}
CMD_VEL_TOPICS = {"cmd_vel", "/cmd_vel"}
#: The single writer (D-2, D-38).
CMD_VEL_PUBLISHER = "src/runtime/gateway/core/bridge/ros_bridge.py"
#: ``declare_parameter`` defaults of "cmd_vel": the legacy D-208 standalone safety node only.
CMD_VEL_PARAMETER_ALLOWLIST = {"src/runtime/sensing/control/safety/node.py"}
OMX_SCOPE = ("src/products/omx/", "integrations/robots/omx/", "apps/agent/")


def _is_cmd_vel(node: ast.AST | None, constants: dict) -> bool:
    if isinstance(node, ast.Constant):
        return node.value in CMD_VEL_TOPICS
    return isinstance(node, ast.Name) and constants.get(node.id) in CMD_VEL_TOPICS


def _argument(call: ast.Call, position: int, keyword: str) -> ast.AST | None:
    if len(call.args) > position:
        return call.args[position]
    return next((kw.value for kw in call.keywords if kw.arg == keyword), None)


@functools.lru_cache(maxsize=1)
def _cmd_vel_findings() -> dict[str, set]:
    found = {"publishers": set(), "parameters": set(), "pub_users": set(), "send_goal": set(), "scanned": set()}
    for path in _tracked():
        if not path.endswith(".py") or _is_test_file(path) or path.startswith(tuple(CMD_VEL_SCOPE_EXCLUDED)):
            continue
        found["scanned"].add(path)
        text = (ROOT / path).read_text(encoding="utf-8-sig")
        if "cmd_vel" not in text and "send_goal" not in text:
            continue
        tree = _tree(path)
        constants = {target.id: node.value.value for node in tree.body
                     if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                     for target in node.targets if isinstance(target, ast.Name)}
        for function in ast.walk(tree):
            if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if any(isinstance(node, ast.Attribute) and node.attr == "cmd_vel_pub" for node in ast.walk(function)):
                    found["pub_users"].add((path, function.name))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "create_publisher" and _is_cmd_vel(_argument(node, 1, "topic"), constants):
                found["publishers"].add(path)
            elif node.func.attr == "declare_parameter" and _is_cmd_vel(_argument(node, 1, "value"), constants):
                found["parameters"].add(path)
        if path.startswith(OMX_SCOPE):
            for owner in [tree, *(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef))]:
                if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and node.func.attr == "send_goal" for node in ast.walk(owner)):
                    found["send_goal"].add((path, getattr(owner, "name", "<module>")))
    return found


def test_cmd_vel_publisher_is_single_and_only_send_twist_touches_it():
    """Structural. D-430 §3 invariant 3a over production sources: the only "cmd_vel"
    publisher (topic literal or module constant) is ros_bridge.py; only its
    constructor and ``_send_twist`` touch ``cmd_vel_pub``; a "cmd_vel"
    ``declare_parameter`` default exists only in the allowlisted legacy node; OMX
    ``send_goal`` is called from ``ArmCommandOwner`` and no other class."""
    found = _cmd_vel_findings()
    assert found["publishers"] == {CMD_VEL_PUBLISHER}
    assert found["parameters"] == CMD_VEL_PARAMETER_ALLOWLIST
    assert found["pub_users"] == {(CMD_VEL_PUBLISHER, "__init__"), (CMD_VEL_PUBLISHER, "_send_twist")}
    assert {entry for entry in found["send_goal"] if entry[1] != "<module>"} == {
        ("src/products/omx/adapter/omx_adapter/command_owner.py", "ArmCommandOwner")}


def test_each_separation_rule_checks_at_least_one_importer():
    """Structural. No vacuous pass: invariants 1, 2 (Fleet and robot side) and 3a
    each inspected real files and import edges."""
    _, checked = _separation_edges()
    assert checked["rule1_files"] >= 10 and checked["rule1_edges"] >= 10, checked
    assert checked["rule2_files"] >= 10 and checked["rule2_edges"] >= 5, checked
    assert checked["rule2_robot_files"] >= 1, "core_features/decision must be a checked decision importer"
    found = _cmd_vel_findings()
    assert len(found["scanned"]) > 500 and found["publishers"] and found["send_goal"], len(found["scanned"])


# --- D-430 §4 Fleet-loss exceptions ------------------------------------------

#: STOP is the default and HOLD is physically the same stop (D-430 §4); anything
#: else is a recorded exception that needs a per-robot approval record.
FLEET_LOSS_FAIL_CLOSED = {"STOP", "HOLD"}
APPROVAL_FIELDS = ("robot", "approver", "evidence")
DEFAULT_CONFIG = "src/contracts/foundation/config/rosy_default.yaml"


def _fleet_loss_problems(safety: dict) -> list[str]:
    policy = str(safety.get("fleet_loss_policy", "STOP")).strip().upper()
    if policy in FLEET_LOSS_FAIL_CLOSED:
        return []
    approval = safety.get("fleet_loss_policy_approval")
    missing = [field for field in APPROVAL_FIELDS
               if not isinstance(approval, dict) or not str(approval.get(field) or "").strip()]
    return [f"fleet_loss_policy {policy} needs fleet_loss_policy_approval {missing}"] if missing else []


def _fleet_loss_blocks(node) -> list[dict]:
    if isinstance(node, dict):
        found = [node] if "fleet_loss_policy" in node else []
        return found + [block for value in node.values() for block in _fleet_loss_blocks(value)]
    if isinstance(node, list):
        return [block for value in node for block in _fleet_loss_blocks(value)]
    return []


def test_non_stop_fleet_loss_policy_requires_approval_record():
    """Structural (profile validation). D-430 §4 / user decision U2: a
    ``safety.fleet_loss_policy`` other than STOP/HOLD needs a per-robot
    ``fleet_loss_policy_approval`` with robot, approver and G-dev evidence. Checked on
    fixtures and on every tracked YAML outside tests that sets the policy; the shared
    default stays STOP. Unparseable YAML is skipped (honest hole)."""
    import yaml

    approved = {"robot": "pinky-9dfk", "approver": "operator-lead", "evidence": "docs/validation/x.md"}
    assert _fleet_loss_problems({"fleet_loss_policy": "STOP"}) == []
    assert _fleet_loss_problems({"fleet_loss_policy": "HOLD"}) == []
    assert _fleet_loss_problems({}) == []
    assert _fleet_loss_problems({"fleet_loss_policy": "RETURN_HOME"})
    assert _fleet_loss_problems({"fleet_loss_policy": "continue"})
    assert _fleet_loss_problems({"fleet_loss_policy": "CONTINUE",
                                 "fleet_loss_policy_approval": {**approved, "evidence": ""}})
    assert _fleet_loss_problems({"fleet_loss_policy": "CONTINUE", "fleet_loss_policy_approval": "yes"})
    assert _fleet_loss_problems({"fleet_loss_policy": "RETURN_HOME", "fleet_loss_policy_approval": approved}) == []

    problems, seen = [], {}
    for path in _tracked():
        if not path.endswith((".yaml", ".yml")) or _is_test_file(path) or "/test/" in f"/{path}":
            continue
        text = (ROOT / path).read_text(encoding="utf-8-sig", errors="replace")
        if "fleet_loss_policy" not in text:
            continue
        try:
            documents = list(yaml.safe_load_all(text))
        except yaml.YAMLError:
            continue
        for block in _fleet_loss_blocks(documents):
            seen[path] = block["fleet_loss_policy"]
            problems += [f"{path}: {problem}" for problem in _fleet_loss_problems(block)]
    assert problems == []
    assert len(seen) >= 2, seen
    assert seen.get(DEFAULT_CONFIG) == "STOP", "the shared default is STOP for every robot"


def test_safety_review_trailer_check_sees_the_same_safety_paths():
    """Structural. D-430 §5: the CI trailer check (tools/harness/safety_review.py)
    classifies every tracked file exactly as these tests do."""
    import safety_review

    manifest = _manifest()
    modules = set(manifest["safety_modules"])
    mismatched = [path for path in _tracked()
                  if safety_review.is_safety(path, manifest["roots"], modules) != (_concern_of(path) == SAFETY)]
    assert mismatched == []
    assert sum(safety_review.is_safety(path, manifest["roots"], modules) for path in _tracked()) >= 20
