"""The updater's records, config, hold and eligibility (D-412; moved out of rosy_auto_update.py, D-798)."""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import math
import os
from pathlib import Path
import re

import rosy_claim
from os_state_layout import StateError, policy_file
from auto_update_host import (ANGULAR_EPS, API_BASE_URL, APPROVALS, BATTERY_MIN, CLAIM_HOLDER, DEFAULT_REPO,
    DOCKING_IDLE, FACE_UNIT, _finite, HISTORY_MAX_BYTES, LINE_FOLLOW_IDLE, LINEAR_EPS, MAX_HOLD_HOURS,
    MAX_STATUS_INPUTS_BYTES, NAV_IDLE, NOT_NULL_INPUTS, _number, parse_z, PHASES, _read_json, _reason_class, _fsync_parent,
    RELEASE_ID, REPO, REQUIRED_INPUTS, RETIRED_DISPLAY_UNIT, SAMPLE_GAP_S, STATUS_INPUTS,
    STATUS_INPUTS_FRESH_S, _tail, UPDATE_DISPLAY, UpdateError, _write_json, _z)


class UpdaterRecords:
    """Updater mixin: state/status/history files, config, holds, approvals and the idle check."""

    # records --------------------------------------------------------------------

    def _maintenance_problem(self) -> str | None:
        try:
            from os_payload_compatibility import require_native_maintenance
            require_native_maintenance(self.root)
        except (ImportError, OSError, ValueError) as exc:
            return f"OS_STATE_HOLD: {exc}"
        return None

    def _policy_path(self, name: str) -> Path:
        try:
            return policy_file(self.root, name)
        except StateError as exc:
            raise UpdateError(str(exc)) from exc

    def _load_state(self) -> dict:
        try:
            data = _read_json(self.updates / "state.json")
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self, state: dict) -> None:
        _write_json(self.updates / "state.json", state)

    def _update_marker(self, applying) -> None:
        """D-433 row 3: the screen's "Updating" card, only while THIS run works on an apply.

        Written by ``_journal`` (each step this run takes) and by the "applying"
        finish at activation; every other finish removes it. A journal left
        waiting (held, ineligible, stuck) therefore never keeps the card up and
        hides a stop, a dead CORE or a login code behind it. Best effort.
        """
        marker = self.root / UPDATE_DISPLAY
        with contextlib.suppress(OSError):
            if isinstance(applying, dict) and RELEASE_ID.fullmatch(str(applying.get("release_id") or "")):
                step = re.sub(r"[^a-z-]", "-", str(applying.get("step") or "applying").lower())[:32] or "applying"
                marker.parent.mkdir(parents=True, exist_ok=True)
                temporary = marker.with_name(f".{marker.name}.tmp")
                temporary.write_text(f"{step}\n{applying['release_id']}\n", encoding="utf-8")
                os.chmod(temporary, 0o644)
                os.replace(temporary, marker)
            else:
                marker.unlink(missing_ok=True)

    def _face_swap(self) -> None:
        """D-433: hand the LCD, buzzer and lamp from rosy-boot-display to rosy-face, live.

        The image-layer sync only installs and enables rosy-face; it never swaps,
        because on a robot updating from 026 the sync runs under 026's updater,
        whose rollback cannot restart the retired unit. This updater can (see
        ``_restore_display``), so the swap waits for it: the first timer run after
        the payload landed, or the next boot, where rosy-face starts and the
        retired unit's condition keeps it off. Best effort; a failed step is
        tried again on the next run only while the retired unit still runs.
        """
        units = self.root / "etc/systemd/system"
        if not (units / FACE_UNIT).is_file():
            return
        if self._systemctl("is-enabled", "--quiet", FACE_UNIT).returncode != 0:
            return
        if self._systemctl("is-active", "--quiet", FACE_UNIT).returncode == 0:
            return
        if self._systemctl("is-active", "--quiet", RETIRED_DISPLAY_UNIT).returncode != 0:
            return
        if self._systemctl("stop", RETIRED_DISPLAY_UNIT).returncode == 0:
            self._systemctl("start", FACE_UNIT)

    def _restore_display(self) -> None:
        """D-433 Q5: after a rollback the screen must not stay dark until the next boot.

        Only when the rolled-back release has no rosy-face (its unit file is gone)
        and the retired unit is enabled but not running; starting it beside
        rosy-face would put two owners on the same lines.
        """
        if (self.root / "etc/systemd/system" / FACE_UNIT).exists():
            return
        if not (self.root / "etc/systemd/system" / RETIRED_DISPLAY_UNIT).is_file():
            return
        if self._systemctl("is-enabled", "--quiet", RETIRED_DISPLAY_UNIT).returncode != 0:
            return
        if self._systemctl("is-active", "--quiet", RETIRED_DISPLAY_UNIT).returncode == 0:
            return
        started = self._systemctl("start", RETIRED_DISPLAY_UNIT)
        if started.returncode != 0:
            raise UpdateError(f"DISPLAY_RESTORE_FAILED: {_tail(started.stderr)}")

    def _history(self, event: str, release_id: str | None, detail: str) -> None:
        self.updates.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"at": _z(self.host.now()), "event": event, "release_id": release_id,
                           "detail": detail, "boot_id": self.host.boot_id()}, sort_keys=True)
        path = self.updates / "history.jsonl"
        # Review L4: one generation of history is kept beside the live file.
        with contextlib.suppress(OSError):
            if path.stat().st_size >= HISTORY_MAX_BYTES:
                os.replace(path, path.with_name("history.jsonl.1"))
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(path, 0o644)

    def _finish(self, state: dict, phase: str, reason: str, candidate: str | None = None) -> dict:
        """Write status.json; add a history line when the phase or its reason changed."""
        assert phase in PHASES, phase
        current = self.host.current_release()
        status = {
            "schema": 1, "updated_at": _z(self.host.now()), "hostname": self.host.hostname(),
            "current_release": current, "candidate": candidate, "phase": phase, "reason": reason,
            "last_result": state.get("last_result"),
        }
        # D-433: only an apply in progress in this run shows "Updating"; a wait clears it.
        self._update_marker(state.get("applying") if phase == "applying" else None)
        signature = [phase, candidate, _reason_class(reason)]
        if state.get("last_status") != signature:
            self._history(phase, candidate, reason)
            state["last_status"] = signature
        self._save_state(state)
        _write_json(self.updates / "status.json", status)
        return status

    def _result(self, state: dict, release_id: str, outcome: str, detail: str) -> None:
        state["last_result"] = {"release_id": release_id, "outcome": outcome,
                                "at": _z(self.host.now()), "detail": detail}

    def _mark_failed(self, state: dict, release_id: str, detail: str) -> None:
        state.setdefault("failed", {})[release_id] = {"at": _z(self.host.now()), "detail": detail}
        if state.get("staged") == release_id:
            state["staged"] = None
        (state.get("stage_errors") or {}).pop(release_id, None)

    # config and hold ---------------------------------------------------------------

    def _config(self) -> dict:
        path = self._policy_path("config.json")
        if not path.exists() and not path.is_symlink():
            # On by default since the first real canary commit (D-412, 2026-10-02);
            # config.json {"enabled": false} turns a robot off.
            return {"enabled": True, "repo": DEFAULT_REPO, "api_base": None}
        try:
            data = _read_json(path, 64 * 1024)
        except (OSError, ValueError) as exc:
            raise UpdateError(f"CONFIG_INVALID: {exc}") from exc
        if not isinstance(data, dict):
            raise UpdateError("CONFIG_INVALID: not an object")
        enabled = data.get("enabled", True)
        repo = data.get("repo", DEFAULT_REPO)
        if not isinstance(enabled, bool) or not isinstance(repo, str) or not REPO.fullmatch(repo):
            raise UpdateError("CONFIG_INVALID: enabled must be a bool and repo owner/name")
        api_base = data.get("api_base")
        if api_base is not None and not (isinstance(api_base, str) and API_BASE_URL.fullmatch(api_base)):
            raise UpdateError("CONFIG_INVALID: api_base must be an http(s)://host[:port][/path] URL")
        return {"enabled": enabled, "repo": repo, "api_base": api_base}

    def _hold(self) -> tuple[str, str]:
        """("none" | "active" | "expired" | "invalid", detail). Read-only."""
        path = self._policy_path("hold.json")
        if not path.exists() and not path.is_symlink():
            return "none", ""
        try:
            data = _read_json(path, 64 * 1024)
        except (OSError, ValueError) as exc:
            return "invalid", f"hold.json unreadable ({exc}); release it with release-hold"
        created = parse_z(data.get("created_at")) if isinstance(data, dict) else None
        expires = parse_z(data.get("expires_at")) if isinstance(data, dict) else None
        if (created is None or expires is None or not expires > created
                or (expires - created) > _dt.timedelta(hours=MAX_HOLD_HOURS)):
            return "invalid", "hold.json has no valid expires_at within 7 days; release it with release-hold"
        detail = f"hold by {data.get('holder')}: {data.get('reason')} (until {_z(expires)})"
        if self.host.now() >= expires:
            return "expired", detail
        return "active", detail

    def hold(self, holder: str, reason: str, hours: float) -> dict:
        if not _number(hours) or not 0 < hours <= MAX_HOLD_HOURS:
            raise UpdateError(f"HOLD_HOURS_INVALID: hours must be in (0, {MAX_HOLD_HOURS:g}]")
        for name, value in (("holder", holder), ("reason", reason)):
            if not isinstance(value, str) or not value.strip() or len(value) > 200 \
                    or re.search(r"[\x00-\x1f\x7f]", value):
                raise UpdateError(f"HOLD_{name.upper()}_INVALID: 1-200 printable characters")
        now = self.host.now()
        payload = {"holder": holder, "reason": reason, "created_at": _z(now),
                   "expires_at": _z(now + _dt.timedelta(hours=hours))}
        _write_json(self._policy_path("hold.json"), payload)
        self._history("hold_set", None, f"{holder}: {reason} until {payload['expires_at']}")
        return payload

    def release_hold(self) -> dict:
        """Remove the hold; also the operator's acknowledgement of a rollback failure and of
        repeated apply failures. Takes the run lock (RunBusy while a run is active)."""
        with self._run_lock():
            path = self._policy_path("hold.json")
            existed = path.exists() or path.is_symlink()
            path.unlink(missing_ok=True)
            _fsync_parent(path)
            state = self._load_state()
            cleared = sorted(state.get("apply_errors") or {})
            acknowledged = None
            if (state.get("last_result") or {}).get("outcome") == "rollback_failed":
                acknowledged = state["last_result"].get("release_id")
                self._history("rollback_failure_acknowledged", acknowledged, "cleared by release-hold")
                state["last_result"] = None
            if cleared or acknowledged:
                state["apply_errors"] = {}
                self._save_state(state)
            self._history("hold_released", None, "hold removed" if existed else "no hold was set")
            return {"released": existed, "acknowledged_rollback_failure": acknowledged,
                    "cleared_apply_errors": cleared}

    def _expire_hold(self) -> None:
        kind, detail = self._hold()
        if kind == "expired":
            path = self._policy_path("hold.json")
            path.unlink(missing_ok=True)
            _fsync_parent(path)
            self._history("hold_expired", None, detail)

    # eligibility ---------------------------------------------------------------------

    def _sealed(self, current: str | None) -> list[str]:
        # Review M6: a marker that exists but cannot be read as {"release_id": str}
        # might be a seal; it holds like one.
        reasons = []
        for marker in APPROVALS:
            path = self.root / marker
            name = Path(marker).name
            if path.is_symlink():
                reasons.append(f"approval marker {name} is a symlink")
                continue
            if not path.exists():
                continue
            try:
                data = _read_json(path, 64 * 1024)
            except (OSError, ValueError):
                reasons.append(f"approval marker {name} is unreadable or oversize")
                continue
            if not isinstance(data, dict) or not isinstance(data.get("release_id"), str):
                reasons.append(f"approval marker {name} is corrupt")
            elif current is not None and data["release_id"] == current:
                reasons.append(f"sealed approval {name} names the current release {current}")
        return reasons

    def _inputs_problems(self) -> list[str]:
        return self._sample()[0] + self._network_problems()

    def _network_problems(self) -> list[str]:
        reasons = []
        for relative in ("var/lib/rosy/network/transaction.json", "run/rosy-network/recovery.json"):
            path = self.root / relative
            if not path.exists() and not path.is_symlink():
                continue  # A legacy image has no network transaction/recovery producer.
            try:
                data = _read_json(path, 64 * 1024)
                if not isinstance(data, dict):
                    raise ValueError("invalid state")
                if path.name == "transaction.json":
                    state = data.get("state")
                    if (state not in {"committed", "rolled_back", "rejected"}
                            or ("phase" in data and data["phase"] != state)):
                        reasons.append("network transaction is active or held")
                elif data.get("active") is not False or data.get("boot_id") != self.host.boot_id():
                    reasons.append("network recovery is active or unknown")
            except (OSError, ValueError):
                reasons.append("network state is unreadable or invalid")
        return reasons

    def _sample(self) -> tuple[list[str], _dt.datetime | None]:
        """(problems, written_at) for one read of status-inputs.json."""
        try:
            data = _read_json(self.root / STATUS_INPUTS, MAX_STATUS_INPUTS_BYTES)
        except (OSError, ValueError, UnicodeDecodeError):
            return ["status-inputs.json missing, unreadable or over 16 KiB"], None
        problems = self._judge_inputs(data)
        return problems, (parse_z(data["written_at"]) if not problems else None)

    def _judge_inputs(self, data: object) -> list[str]:
        if not isinstance(data, dict):
            return ["status-inputs.json is not an object"]
        schema = data.get("schema")
        if not isinstance(schema, int) or isinstance(schema, bool) or schema < 2:
            return [f"status-inputs schema {schema!r} is not >= 2"]
        missing = [key for key in REQUIRED_INPUTS if key not in data]
        if missing:
            return [f"status-inputs lacks {', '.join(missing)}"]
        written = parse_z(data["written_at"])
        if written is None:
            return ["status-inputs written_at is invalid"]
        age = (self.host.now() - written).total_seconds()
        if not -5.0 <= age <= STATUS_INPUTS_FRESH_S:
            return [f"status-inputs is stale ({age:.0f} s old)"]
        # Contract amendment (b63cb7f2): an added key may be null, null is unknown and
        # unknown is ineligible, decided before any value is interpreted. A null
        # battery_percent blocks even while charging. docking_state and activity_kind
        # are typed "null or string": there null means none, as before.
        unknown = [key for key in NOT_NULL_INPUTS
                   if data[key] is None or (isinstance(data[key], float) and not math.isfinite(data[key]))]
        if unknown:
            return [f"status-inputs does not know {', '.join(unknown)}"]
        problems = []
        if data["swarm_role"] not in (None, "none"):
            problems.append(f"swarm role is {data['swarm_role']}")
        if data["robot_mode"] != "IDLE":
            problems.append(f"robot mode is {data['robot_mode']}")
        if data["nav_state"] not in NAV_IDLE:
            problems.append(f"navigation is {data['nav_state']}")
        if data["line_follow_mode"] != "OFF":
            problems.append(f"line follow is {data['line_follow_mode']}")
        if data["line_follow_state"] not in LINE_FOLLOW_IDLE:
            problems.append(f"line follow state is {data['line_follow_state']}")
        if data["docking_state"] not in DOCKING_IDLE:
            problems.append(f"docking is {data['docking_state']}")
        if data["swarm_active"] is not False:
            problems.append("swarm is active")
        if data["estop"] is not False:
            problems.append("E-stop is engaged")
        if data["activity_kind"] is not None:
            problems.append(f"activity {data['activity_kind']} is running")
        linear, angular = data["velocity_linear"], data["velocity_angular"]
        # Finite numbers inside the band, written so a NaN can never pass.
        if not (_finite(linear) and _finite(angular) and abs(linear) < LINEAR_EPS and abs(angular) < ANGULAR_EPS):
            problems.append(f"robot is moving or its velocity is invalid (v={linear!r}, w={angular!r})")
        percent, charging = data["battery_percent"], data["battery_charging"]
        if not _finite(percent):
            problems.append(f"battery percent {percent!r} is invalid")
        elif charging is not True and not percent >= BATTERY_MIN:
            problems.append(f"battery {percent!r}% is below {BATTERY_MIN:g}% and not charging")
        return problems

    def precheck(self) -> list[str]:
        """What native_release runs right before it stops the runtime: hold, seal, one fresh sample."""
        if problem := self._maintenance_problem():
            return [problem]
        reasons = []
        kind, detail = self._hold()
        if kind in {"active", "invalid"}:
            reasons.append(detail)
        reasons += self._sealed(self.host.current_release())
        claim = rosy_claim.check(self.root, now=self.host.now())
        if claim is not None and claim.get("holder") != CLAIM_HOLDER:
            reasons.append(f"claim held by {claim.get('holder')}")
        return reasons + self._inputs_problems()

    def eligibility(self, *, own_claim_ok: bool = False, waive_inputs: bool = False) -> dict:
        """Read-only: may this robot apply now? Two status samples, two different writes."""
        current = self.host.current_release()
        reasons: list[str] = []
        if problem := self._maintenance_problem():
            reasons.append(problem)
        kind, detail = self._hold()
        if kind in {"active", "invalid"}:
            reasons.append(detail)
        reasons += self._sealed(current)
        reasons += self._network_problems()
        held = bool(reasons)
        claim = rosy_claim.check(self.root, now=self.host.now())
        if claim is not None and not (own_claim_ok and claim.get("holder") == CLAIM_HOLDER):
            reasons.append(f"claim held by {claim.get('holder')} ({claim.get('purpose')})")
        if not held and not waive_inputs:
            problems, first = self._sample()
            if not problems:
                self.host.sleep(SAMPLE_GAP_S)
                problems, second = self._sample()
                problems = [f"second sample: {item}" for item in problems]
                if not problems and not (second is not None and first is not None and second > first):
                    problems = ["second sample: status-inputs was not rewritten (CORE is not updating it)"]
            reasons += problems
        return {"eligible": not reasons, "held": held, "reasons": reasons,
                "current_release": current, "checked_at": _z(self.host.now())}
