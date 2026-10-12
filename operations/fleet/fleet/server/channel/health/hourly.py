"""Fixed KST channel health slot over cached Fleet and owner facts."""
import asyncio, hashlib, logging, math, sqlite3, time
from contextlib import closing
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

_LOG, _KST = logging.getLogger(__name__), ZoneInfo("Asia/Seoul")
_START_WINDOW_S, _RETRY_WINDOW_S, _RETRY_DELAY_S, _MAX_ATTEMPTS, _CLAIM_RECOVERY_S = 15, 120, 15, 3, 30
class HourlyHealth:
    def __init__(self, journal, sender, gather, console, ai_facts, *, clock=time.time):
        self.journal, self.sender, self.gather = journal, sender, gather
        self.console, self.ai, self.clock = console, ai_facts, clock
        self.started_at = clock()
        self._reported_slot = None
        with closing(self.journal._connect()) as conn, conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS fleet_channel_hourly_health (
                slot TEXT PRIMARY KEY, guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
                bot_id TEXT NOT NULL, nonce TEXT NOT NULL UNIQUE, state TEXT NOT NULL,
                attempts INTEGER NOT NULL, claim_id TEXT, claimed_at REAL, retry_until REAL NOT NULL,
                next_attempt_at REAL, provider_id TEXT, payload TEXT)''')
            if "payload" not in {row[1] for row in conn.execute("PRAGMA table_info(fleet_channel_hourly_health)")}:
                conn.execute("ALTER TABLE fleet_channel_hourly_health ADD COLUMN payload TEXT")

    def _scope(self): return (self.journal.config.guild_id, self.journal.config.channel_id, self.journal.config.bot_id) if self.journal.config.hourly_health_enabled is True else None
    @staticmethod
    def _slot(now):
        start = datetime.fromtimestamp(now, _KST).replace(minute=0, second=0, microsecond=0)
        return start.isoformat(timespec="minutes"), start.timestamp()

    def task_counts(self):
        with closing(self.journal._connect()) as conn:
            return dict(conn.execute("SELECT status, COUNT(*) FROM fleet_tasks GROUP BY status"))

    def slot_exists(self, slot):
        with closing(self.journal._connect()) as conn:
            return conn.execute("SELECT 1 FROM fleet_channel_hourly_health WHERE slot=?", (slot,)).fetchone() is not None

    def report(self, now, counts):
        now = self.clock() if now is None else now
        captured = self.gather.gathered_at
        collection_age = now - captured if type(captured) in (int, float) and math.isfinite(captured) else None
        collection = "recent" if collection_age is not None and 0 <= collection_age <= 5 else "\ubbf8\ud655\uc778"
        stamp = (datetime.fromtimestamp(captured, _KST).strftime("%m-%d %H:%M")
                 if collection_age is not None and 0 <= collection_age <= 5 else "\ubbf8\ud655\uc778")
        rows = {row.get("robot_id"): row for row in (self.gather._snapshot or {}).get("robots", [])
                if isinstance(row, dict) and isinstance(row.get("robot_id"), str)}
        mono, robots = self.console._clock(), sorted(self.console.clients())
        lines = [f"ROSY Fleet \uac74\uac15 | KST {datetime.fromtimestamp(now, _KST):%H:%M}",
                 f"\uc218\uc9d1 {collection} | \uad00\uce21 {stamp}"]
        details = []
        for robot in robots:
            row = rows.get(robot, {})
            observed = row.get("_state_mono")
            age = mono - observed if type(observed) in (int, float) and math.isfinite(observed) else None
            fresh = row.get("online") is True and age is not None and 0 <= age <= 3
            state = row.get("state") if fresh and isinstance(row.get("state"), dict) else {}
            evidence = state.get("evidence", {}) if isinstance(state.get("evidence", {}), dict) else {}
            safety = state.get("safety", {}) if isinstance(state.get("safety", {}), dict) else {}
            battery = state.get("battery", {}) if isinstance(state.get("battery", {}), dict) else {}
            safety_fresh = isinstance(evidence.get("safety"), dict) and evidence["safety"].get("evidence") == "fresh"
            estop = safety.get("estop") if safety_fresh else None
            safe = "E-stop \ub3d9\uc791" if estop is True else "E-stop \ud574\uc81c" if estop is False else "\uc548\uc804 \ubbf8\ud655\uc778"
            battery_fresh = isinstance(evidence.get("battery"), dict) and evidence["battery"].get("evidence") == "fresh"
            percent = battery.get("percent") if battery_fresh else None
            battery_text = (f" | \ubc30\ud130\ub9ac {percent:g}%" if type(percent) in (int, float)
                            and math.isfinite(percent) and 0 <= percent <= 100 else " | \ubc30\ud130\ub9ac \ubbf8\ud655\uc778")
            label = robot if len(robot) <= 72 else robot[:71] + "\u2026"
            link = "\uc5f0\uacb0" if fresh else "\ubbf8\ud655\uc778"
            details.append(f"{label}: {link} | {safe}{battery_text}")
        active = sum(counts.get(state, 0) for state in ("REQUESTED", "QUEUED", "ACCEPTED", "RUNNING"))
        work = f"\uc791\uc5c5 \uc9c4\ud589 {active} | HOLD {counts.get('HOLD', 0)} | UNKNOWN {counts.get('UNKNOWN', 0)}"
        try:
            ai = self.ai.status()
            ai_state = ai.get("state") if ai.get("state") in {"present", "absent"} else "\ubbf8\ud655\uc778"
            mode = (ai.get("owner_mode") if ai_state == "present"
                    and ai.get("owner_mode") in {"available", "shared", "owner_busy"} else "\ubbf8\ud655\uc778")
            age = ai.get("age_s")
            age_text = f" | {age:g}s" if type(age) in (int, float) and math.isfinite(age) and age >= 0 else ""
        except Exception:
            ai_state, mode, age_text = "\ubbf8\ud655\uc778", "\ubbf8\ud655\uc778", ""
        observer = f"AI \uad00\uce21\uae30 {ai_state} | {mode}{age_text}; \ubaa8\ub378 admission: \ubbf8\ud655\uc778"
        fixed = lines + [work, observer]
        budget = 1900 - sum(len(line) + 1 for line in fixed) - 52
        shown = []
        for detail in details:
            if len(detail) > budget:
                break
            shown.append(detail)
            budget -= len(detail) + 1
        omitted = len(details) - len(shown)
        roster = f"\ub85c\ubd07 {len(robots)}\ub300 | \ud45c\uc2dc {len(shown)} | \uc0dd\ub7b5 {omitted}"
        result = "\n".join(lines + [roster] + shown + [work, observer])
        return result if len(result) <= 2000 else result[:1990] + "\u2026"

    def claim(self, now, payload=""):
        scope = self._scope()
        if scope is None: return None
        slot, due = self._slot(now)
        nonce = hashlib.sha256(f"rosy-hourly-health:{slot}".encode()).hexdigest()[:24]
        with closing(self.journal._connect()) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE fleet_channel_hourly_health SET state='FAILED' WHERE state='RETRY' AND retry_until<=?", (now,))
            row = conn.execute("SELECT * FROM fleet_channel_hourly_health WHERE slot=?", (slot,)).fetchone()
            if row is None and (due < self.started_at or now > due + _START_WINDOW_S):
                conn.execute("INSERT INTO fleet_channel_hourly_health VALUES (?,?,?,?,?,'SKIPPED',0,NULL,NULL,?,NULL,NULL,NULL)",
                             (slot, *scope, nonce, due + _RETRY_WINDOW_S))
                return None
            if row is None:
                claim_id = uuid4().hex
                conn.execute("INSERT INTO fleet_channel_hourly_health VALUES (?,?,?,?,?,'CLAIMED',1,?,?,?,NULL,NULL,?)",
                             (slot, *scope, nonce, claim_id, now, due + _RETRY_WINDOW_S, payload))
                return {"slot": slot, "nonce": nonce, "claim_id": claim_id, "attempts": 1,
                        "retry_until": due + _RETRY_WINDOW_S, "scope": scope, "payload": payload}
            if row["state"] == "CLAIMED" and now - (row["claimed_at"] or now) >= _CLAIM_RECOVERY_S:
                conn.execute("UPDATE fleet_channel_hourly_health SET state='UNKNOWN' WHERE slot=? AND state='CLAIMED'",
                             (slot,))
                return None
            if ((row["guild_id"], row["channel_id"], row["bot_id"]) != scope or row["state"] != "RETRY"
                    or row["attempts"] >= _MAX_ATTEMPTS or now < (row["next_attempt_at"] or 0)
                    or now >= row["retry_until"]):
                return None
            claim_id = uuid4().hex
            attempts = row["attempts"] + 1
            conn.execute("UPDATE fleet_channel_hourly_health SET state='CLAIMED', attempts=?, claim_id=?, "
                         "claimed_at=? WHERE slot=? AND state='RETRY'", (attempts, claim_id, now, slot))
            return {"slot": slot, "nonce": row["nonce"], "claim_id": claim_id, "attempts": attempts,
                    "retry_until": row["retry_until"], "scope": scope, "payload": row["payload"] or payload}

    def finish(self, claim, result, now):
        state = result.get("state")
        if state not in {"SENT", "RETRY", "FAILED", "UNKNOWN"}: state = "UNKNOWN"
        # A slow live publisher may outlast the conservative recovery lease.
        # Keep UNKNOWN terminal unless this exact claimant later proves delivery.
        if state == "SENT":
            with closing(self.journal._connect()) as conn, conn:
                conn.execute("UPDATE fleet_channel_hourly_health SET state='SENT', next_attempt_at=NULL, "
                             "provider_id=? WHERE slot=? AND state='UNKNOWN' AND claim_id=?",
                             (result.get("provider_id"), claim["slot"], claim["claim_id"]))
        next_at = None
        if state == "RETRY":
            if claim["attempts"] >= _MAX_ATTEMPTS or now >= claim["retry_until"]:
                state = "FAILED"
            else:
                next_at = now + _RETRY_DELAY_S
        with closing(self.journal._connect()) as conn, conn:
            conn.execute("UPDATE fleet_channel_hourly_health SET state=?, next_attempt_at=?, provider_id=? "
                         "WHERE slot=? AND state='CLAIMED' AND claim_id=?",
                         (state, next_at, result.get("provider_id"), claim["slot"], claim["claim_id"]))

    def recover(self, now=None):
        now = self.clock() if now is None else now
        with closing(self.journal._connect()) as conn, conn:
            conn.execute("UPDATE fleet_channel_hourly_health SET state='UNKNOWN' "
                         "WHERE state='CLAIMED' AND claimed_at<=?", (now - _CLAIM_RECOVERY_S,))

    async def run_once(self):
        now = self.clock()
        if self._scope() is None: return
        slot, due = self._slot(now)
        payload = None
        scanned_slot = False
        if (due >= self.started_at and due <= now <= due + _START_WINDOW_S and self._reported_slot != slot
                and not await asyncio.to_thread(self.slot_exists, slot)):
            counts = await asyncio.to_thread(self.task_counts)
            payload = self.report(now, counts)
            scanned_slot = True
        elif due >= self.started_at and due <= now <= due + _START_WINDOW_S:
            scanned_slot = True
        claim = await asyncio.to_thread(self.claim, now, payload)
        if scanned_slot:
            self._reported_slot = slot
        if claim is None: return
        result = {"state": "UNKNOWN", "provider_id": None}
        try:
            if self._scope() != claim["scope"] or getattr(self.sender, "scope", None) != claim["scope"]:
                result = {"state": "FAILED", "provider_id": None}
            else:
                result = await self.sender.publish(nonce=claim["nonce"], content=claim["payload"])
                if self._scope() != claim["scope"] or getattr(self.sender, "scope", None) != claim["scope"]:
                    result = {"state": "UNKNOWN", "provider_id": result.get("provider_id")}
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(self.finish, claim, result, self.clock()))
            raise
        except Exception:
            pass
        await asyncio.to_thread(self.finish, claim, result, self.clock())

    async def run(self):
        await asyncio.to_thread(self.recover, self.clock())
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError: raise
            except Exception as error:
                _LOG.warning("Hourly health scan held (%s)", type(error).__name__)
            await asyncio.sleep(1)
