"""HTTP responses shared by the sample and connected development providers."""
from dataclasses import dataclass
import json
from typing import Iterable


@dataclass
class DevResponse:
    status: int
    headers: list[tuple[str, str]]
    body: bytes | Iterable[bytes]


def reply(value=None, status=200, headers=()):
    return DevResponse(status, [('Content-Type', 'application/json'), ('Cache-Control', 'no-store'), *headers],
                       b'' if status == 204 else json.dumps(value, ensure_ascii=False).encode())


def error(status, code, message=''):
    return reply({'detail': {'code': code, 'message': message}}, status)
