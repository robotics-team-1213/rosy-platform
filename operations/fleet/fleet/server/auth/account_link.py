"""D-992: after a hub link, register the robot in Account and give it the receiver settings."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx


def _private_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or (os.name == "posix" and path.stat().st_mode & 0o077):
        raise ValueError("account link token file must be a private regular file")
    return path.read_text(encoding="utf-8").strip()


CONFIG_ENV = "ROSY_ACCOUNT_LINK_CONFIG"


def configured_link():
    """The AccountLink the environment names, or None. A broken file stops startup: it was asked for."""
    filename = os.environ.get(CONFIG_ENV, "").strip()
    if not filename:
        return None
    try:
        return AccountLink.load(Path(filename))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SystemExit(f"{CONFIG_ENV} is not a valid account link file") from None


class AccountLink:
    """Never raises into the hub link: this is people's login, and the robot link already succeeded."""

    def __init__(self, *, issuer: str, registrar_token: str, public_keys: dict[str, str], transport=None):
        parsed = urlsplit(issuer)
        if parsed.scheme != "https" or not parsed.hostname or not registrar_token or not public_keys:
            raise ValueError("invalid account link configuration")
        self.issuer, self._token, self.public_keys = issuer.rstrip("/"), registrar_token, public_keys
        self._transport = transport
        self.states: dict[str, str] = {}

    @classmethod
    def load(cls, filename: Path) -> "AccountLink":
        data = json.loads(Path(filename).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"issuer", "registrar_token_file", "public_key_files"}:
            raise ValueError("invalid account link configuration")
        base = Path(filename).resolve().parent
        return cls(issuer=data["issuer"], registrar_token=_private_text(base / data["registrar_token_file"]),
                   public_keys={kid: (base / name).read_text(encoding="ascii")
                                for kid, name in data["public_key_files"].items()})

    async def _register(self, robot_id: str, base_url: str) -> str:
        """Our client id; the registry row exists when this returns."""
        async with httpx.AsyncClient(transport=self._transport, timeout=5.0, follow_redirects=False) as http:
            response = await http.put(
                f"{self.issuer}/api/fleet/auth/device-clients/{robot_id}",
                headers={"Authorization": "Bearer " + self._token},
                json={"callback": base_url + "/api/account/callback", "home_url": base_url + "/dashboard",
                      "label": robot_id})
        response.raise_for_status()
        return response.json()["client_id"]

    async def provision(self, robot_id: str, client) -> str:
        """`linked`, or the step that stopped it. Repeating a hub link repeats this with the same values."""
        base_url = client._ep.base_url.rstrip("/")
        state = "linked"
        try:
            caps = await client.capabilities()
            if not (isinstance(caps, dict) and caps.get("account_receiver_provisioning") is True):
                state = "robot_unsupported"
            else:
                try:
                    client_id = await self._register(robot_id, base_url)
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    state = "account_unreachable"
                else:
                    state = "robot_refused"
                    await client.account_receiver_put({
                        "issuer": self.issuer, "client_id": client_id,
                        "callback": base_url + "/api/account/callback", "public_keys": self.public_keys})
                    state = "linked"
        except Exception:  # the robot's refusal or a dropped connection: state says which step it reached
            if state == "linked":
                state = "robot_unreachable"
        self.states[robot_id] = state
        return state
