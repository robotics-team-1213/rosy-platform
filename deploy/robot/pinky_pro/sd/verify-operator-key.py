#!/usr/bin/env python3
"""Compare an OpenSSH private file's embedded public key with the card's .pub file.

This reads the public header without decrypting the private payload. It does not
prove the encrypted payload is intact or that the operator can unlock it.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import stat
import sys

from personalization import operator_key_fingerprint, validate_operator_key


def _read(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("operator key must be a regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("operator key file exceeds limit")
    return raw


def _public_header(raw: bytes) -> str:
    # ssh-keygen -l may read the sibling .pub instead of the private file's header.
    # Format: https://github.com/openssh/openssh-portable/blob/master/PROTOCOL.key
    lines = raw.strip().splitlines()
    if (len(lines) < 3 or lines[0] != b"-----BEGIN OPENSSH PRIVATE KEY-----"
            or lines[-1] != b"-----END OPENSSH PRIVATE KEY-----"):
        raise ValueError("operator private key must use OpenSSH format")
    data = base64.b64decode(b"".join(lines[1:-1]), validate=True)
    magic = b"openssh-key-v1\0"
    if not data.startswith(magic):
        raise ValueError("invalid OpenSSH private key header")
    offset = len(magic)

    def string() -> bytes:
        nonlocal offset
        if len(data) - offset < 4:
            raise ValueError("truncated OpenSSH private key header")
        length = int.from_bytes(data[offset:offset + 4], "big")
        offset += 4
        if length > len(data) - offset:
            raise ValueError("truncated OpenSSH private key field")
        value = data[offset:offset + length]
        offset += length
        return value

    cipher = string()
    for _ in range(2):  # KDF and KDF options precede the public key.
        string()
    if data[offset:offset + 4] != b"\0\0\0\1":
        raise ValueError("operator private key must contain exactly one key")
    offset += 4
    public = string()
    # OpenSSH appends AEAD tags after the encrypted payload's length-delimited bytes.
    tag_length = 16 if cipher in {b"aes128-gcm@openssh.com", b"aes256-gcm@openssh.com",
                                  b"chacha20-poly1305@openssh.com"} else 0
    if not string() or len(data) - offset != tag_length:
        raise ValueError("invalid OpenSSH private key payload framing")
    length = int.from_bytes(public[:4], "big")
    key_type = public[4:4 + length].decode("ascii")
    return validate_operator_key(key_type + " " + base64.b64encode(public).decode("ascii"))


def key_pair(private: Path, public: Path) -> str:
    embedded = _public_header(_read(private, 65536))
    supplied = validate_operator_key(_read(public, 4096).decode("ascii"))
    if embedded.split()[:2] != supplied.split()[:2]:
        raise ValueError("operator private and public key files do not match")
    return operator_key_fingerprint(supplied)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps({"fingerprint": key_pair(args.private_key, args.public_key)}))
        return 0
    except (OSError, ValueError):
        print("HOLD: operator key files are unavailable, invalid, or do not match; no card was changed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
