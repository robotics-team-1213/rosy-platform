"""A stand-in card whose reads can hang or trickle (D-188 readback watchdog).

A file stand-in always answers at once. A Windows named pipe lets a test decide
how fast the "card" hands out its bytes: the verifier opens ``\\\\.\\pipe\\<name>``
like a device and its read blocks until the test writes. Each client connection
gets the next behaviour in the list (the writer's pre-flight probe connects
first, the readback second); connections past the list get the whole image.

- ``"full"``: write every byte, then close (end of card).
- ``"hang"``: write nothing and keep the pipe open, like a wedged reader.
- ``("slow", seconds)``: write 4 MiB at a time, sleeping ``seconds`` between.
- ``("slow", seconds, piece)``: the same with ``piece`` bytes at a time.
"""

from __future__ import annotations

import ctypes
import threading
import time
import uuid

import _winapi

PIPE_ACCESS_OUTBOUND = 0x00000002
PIPE_TYPE_BYTE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
PIECE = 4 * 1024 * 1024


class PipeCard:
    def __init__(self, data: bytes, behaviours) -> None:
        self.data = data
        self.behaviours = list(behaviours)
        self.path = r"\\.\pipe\rosy-card-" + uuid.uuid4().hex
        self.connections = 0
        self._stop = threading.Event()
        self._next = self._create()
        self._server = threading.Thread(target=self._serve, name="pipe-card", daemon=True)
        self._server.start()

    def _create(self) -> int:
        return _winapi.CreateNamedPipe(
            self.path, PIPE_ACCESS_OUTBOUND, PIPE_TYPE_BYTE_WAIT, PIPE_UNLIMITED_INSTANCES,
            PIECE, 0, 0, _winapi.NULL,
        )

    def _serve(self) -> None:
        while not self._stop.is_set():
            handle = self._next
            try:
                _winapi.ConnectNamedPipe(handle, False)
            except OSError:
                pass  # ERROR_PIPE_CONNECTED: the client beat us to it
            if self._stop.is_set():
                return
            # The next instance exists before this one is served, so a second
            # client never finds the pipe name missing.
            self._next = self._create()
            behaviour = self.behaviours[self.connections] if self.connections < len(self.behaviours) else "full"
            self.connections += 1
            threading.Thread(target=self._feed, args=(handle, behaviour), daemon=True).start()

    def _feed(self, handle: int, behaviour) -> None:
        try:
            if behaviour == "hang":
                self._stop.wait()
                return
            pause = behaviour[1] if isinstance(behaviour, tuple) else 0.0
            piece = behaviour[2] if isinstance(behaviour, tuple) and len(behaviour) > 2 else PIECE
            for start in range(0, len(self.data), piece):
                if self._stop.is_set():
                    return
                _winapi.WriteFile(handle, self.data[start:start + piece])
                if pause:
                    time.sleep(pause)
            ctypes.windll.kernel32.FlushFileBuffers(handle)  # let the reader drain before EOF
        except OSError:
            pass  # the reader was killed or gave up
        finally:
            _winapi.CloseHandle(handle)

    def close(self) -> None:
        self._stop.set()
        try:  # release the server blocked in ConnectNamedPipe
            with open(self.path, "rb", buffering=0):
                pass
        except OSError:
            pass
        self._server.join(5)
