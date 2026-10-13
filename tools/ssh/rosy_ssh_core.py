"""CORE client for the D-418 SSH tools: JSON over HTTPS to one robot's CORE with a pinned certificate.

Loaded by file path from rosy_ssh_enroll.py (the tools are run as standalone scripts); not a command itself.
"""

from __future__ import annotations

import argparse
import json
import ssl
import urllib.error
import urllib.request

#: CORE waits up to 10 s for the root helper; this leaves room for that and a slow LAN.

DEFAULT_TIMEOUT_S = 25


class SshAccessError(RuntimeError):
    pass


# --- CORE HTTP -----------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is answered as an error: the token must never be sent anywhere but the robot asked."""

    def redirect_request(self, *args, **kwargs):
        return None


def tls_context(ca_file: str | None = None, ca_pem: str | None = None, insecure: bool = False) -> ssl.SSLContext:
    """Trust only the given PEM (the robot's served certificate or its CA). PARTIAL_CHAIN lets the served
    leaf itself be the anchor. The name is not checked: tools reach the robot by address and the anchor
    is per robot. insecure only from an explicit --insecure (as tools/capture/edge_drive.py)."""
    if insecure:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    if not ca_file and not ca_pem:
        raise SshAccessError("CORE serves HTTPS: pass --ca-file <robot certificate or CA PEM>, "
                             "or --insecure on a trusted LAN")
    try:
        context = ssl.create_default_context(cafile=ca_file, cadata=ca_pem)
    except (OSError, ValueError) as error:
        raise SshAccessError(f"cannot load the TLS anchor {ca_file or '(served certificate)'}: {error}") from None
    context.check_hostname = False
    context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
    return context


class CoreClient:
    """JSON over HTTPS to one robot's CORE. Proxies from the environment are ignored (LAN only);
    redirects are not followed."""

    def __init__(self, base_url: str, timeout: float = DEFAULT_TIMEOUT_S, context: ssl.SSLContext | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                   urllib.request.HTTPSHandler(context=context), _NoRedirect())

    def call(self, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if token is not None:
            request.add_header("Authorization", "Bearer " + token)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except (urllib.error.URLError, OSError) as error:
            reason = getattr(error, "reason", error)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise SshAccessError(f"{self.base_url} presented a certificate that does not match the pinned one "
                                     f"({reason.verify_message}): the wrong file, a re-provisioned robot, or "
                                     "someone in between. Nothing was sent") from None
            # urllib wraps connect/send failures in URLError; a bare timeout came while waiting for the answer.
            if isinstance(error, TimeoutError) and not isinstance(error, urllib.error.URLError):
                raise SshAccessError(f"{self.base_url} did not answer {method} {path} within {self.timeout:g} s; "
                                     "the change may have been applied on the robot anyway, check with "
                                     "rosy_ssh_share.py list before retrying") from None
            raise SshAccessError(f"{self.base_url} is not reachable ({reason})") from None
        try:
            return status, (json.loads(raw) if raw else None)
        except ValueError:
            return status, None


def add_tls_arguments(parser: argparse.ArgumentParser) -> None:
    tls = parser.add_mutually_exclusive_group()
    tls.add_argument("--ca-file", help="PEM the robot's HTTPS certificate must chain to: its served certificate or "
                                       "its CA (on the robot: echo | openssl s_client -connect 127.0.0.1:8080 "
                                       "| openssl x509)")
    tls.add_argument("--insecure", action="store_true",
                     help="do not verify the robot's HTTPS certificate (trusted bench LAN only)")
