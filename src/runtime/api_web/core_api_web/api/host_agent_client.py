"""CORE's client for the Host Agent (WP-5).

CORE holds no host privilege, so everything on the Network and Release cards
comes from the Host Agent over ``/run/rosy/host-agent.sock``. The contract is
docs/reference/rosy-host-agent-contract.md.

The one rule that shapes this file: **never invent an answer.** A dashboard
that shows a plausible release status when nothing answered is worse than one
that says the agent is unreachable — an operator reads a blank field as
"nothing wrong" and a fabricated field as fact. So an unreachable agent, a
timeout and a refusal are three distinct outcomes and the card says which.

The socket is absent on a development machine and on any host where the agent
has not started. That is expected, not exceptional, and it must not raise into
a request handler.
"""

from __future__ import annotations

import json
import socket
import uuid
from dataclasses import dataclass, field
from typing import Any

DEFAULT_SOCKET_PATH = "/run/rosy/host-agent.sock"

#: A dashboard poll must not hang on an agent that has stopped answering.
#: Short, because every command behind it is either a read or something the
#: agent itself bounds.
DEFAULT_TIMEOUT_S = 5.0

SCHEMA_VERSION = 1

#: Reported when the agent could not be reached at all. Distinct from any code
#: the agent itself returns, so the dashboard can tell "no answer" from "no".
UNAVAILABLE = "HOST_AGENT_UNAVAILABLE"
TIMEOUT = "HOST_AGENT_TIMEOUT"
UNREADABLE = "HOST_AGENT_UNREADABLE_RESPONSE"


@dataclass(frozen=True)
class AgentReply:
    """What the agent said, or why it did not."""

    ok: bool
    code: str
    detail: str = ""
    recovery: str = ""
    data: Any = None

    @property
    def reachable(self) -> bool:
        """Whether an agent answered at all, however it answered."""
        return self.code not in {UNAVAILABLE, TIMEOUT, UNREADABLE}


@dataclass
class HostAgentClient:
    """One request per connection, matching the agent's own loop."""

    socket_path: str = DEFAULT_SOCKET_PATH
    timeout_s: float = DEFAULT_TIMEOUT_S
    #: Injected in tests; the real one is socket.socket.
    connect: Any = None
    _sent: list[dict] = field(default_factory=list, repr=False)

    def request(
        self,
        command: str,
        *,
        role: str,
        user_id: str = "",
        confirmed: bool = False,
        params: dict | None = None,
        idempotency_key: str | None = None,
    ) -> AgentReply:
        """Send one command and return what came back.

        Never raises. A caller rendering a dashboard card has nothing useful
        to do with an exception, and a traceback in a request handler shows
        the operator a 500 where the honest answer is "the agent is not
        running".
        """
        payload = {
            "schema_version": SCHEMA_VERSION,
            "request_id": uuid.uuid4().hex,
            "command": command,
            "actor": {"user_id": user_id, "role": role},
            "confirmed": confirmed,
        }
        if params:
            payload["params"] = params
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key

        self._sent.append(payload)

        try:
            raw = self._round_trip(json.dumps(payload).encode("utf-8") + b"\n")
        except TimeoutError:
            return AgentReply(
                False, TIMEOUT,
                f"the host agent did not answer within {self.timeout_s:g}s",
                "에이전트가 응답하지 않습니다. 서비스 상태를 확인하십시오.",
            )
        except (FileNotFoundError, ConnectionError, PermissionError, OSError) as exc:
            return AgentReply(
                False, UNAVAILABLE,
                f"cannot reach the host agent at {self.socket_path}: {exc}",
                "rosy-host-agent.service 가 실행 중인지 확인하십시오.",
            )

        try:
            response = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return AgentReply(
                False, UNREADABLE, f"the host agent's reply could not be parsed: {exc}",
                "에이전트와 CORE 의 버전이 맞는지 확인하십시오.",
            )

        if not isinstance(response, dict):
            return AgentReply(
                False, UNREADABLE, "the host agent's reply was not an object",
                "에이전트와 CORE 의 버전이 맞는지 확인하십시오.",
            )

        return AgentReply(
            ok=bool(response.get("ok")),
            code=str(response.get("code", UNREADABLE)),
            detail=str(response.get("detail", "")),
            recovery=str(response.get("recovery", "")),
            data=response.get("data"),
        )

    def _round_trip(self, line: bytes) -> bytes:
        opener = self.connect or self._connect_unix
        connection = opener()
        try:
            connection.sendall(line)
            chunks: list[bytes] = []
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            return b"".join(chunks).split(b"\n", 1)[0]
        finally:
            try:
                connection.close()
            except OSError:
                pass

    def _connect_unix(self):
        if not hasattr(socket, "AF_UNIX"):  # pragma: no cover - Windows dev host
            raise OSError("unix sockets are unavailable on this platform")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout_s)
        connection.connect(self.socket_path)
        return connection
