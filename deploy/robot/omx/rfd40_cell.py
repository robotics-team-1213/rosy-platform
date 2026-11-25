"""Field adapter for a Zebra RFD40 RFID Serial Port (Bluetooth Classic SPP)."""

import argparse
import collections
import re
import socket
import statistics
import sys
import time


def choose_epc(data, *, minimum_rssi=-60, margin=6):
    """Choose one repeatedly observed EPC only if its signal is clearly ahead."""
    lines = data.decode("ascii", errors="replace").splitlines()
    if not lines or not lines[0].startswith("Command:inventory"):
        return None
    fields = [field.strip().rstrip(":").lower() for field in lines[0].split(",")]
    if "status:ok" not in fields or not {"epcid", "rssi", "tagseencount"} <= set(fields):
        return None
    epc_col, rssi_col, count_col = (fields.index(name) for name in ("epcid", "rssi", "tagseencount"))
    readings = collections.defaultdict(list)
    counts = {}
    for line in lines[1:]:
        if not line.startswith(",,"):
            continue
        columns = line.split(",")
        try:
            epc = columns[epc_col].strip().upper()
            rssi, seen = int(columns[rssi_col]), int(columns[count_col])
        except (ValueError, IndexError):
            return None
        if not re.fullmatch(r"(?:[0-9A-F]{2}){2,64}", epc) or not -120 <= rssi <= 0 or seen < 1:
            return None
        readings[epc].append(rssi)
        counts[epc] = max(counts.get(epc, 0), seen)
    ranked = sorted(((statistics.median(samples), epc) for epc, samples in readings.items()), reverse=True)
    if not ranked:
        return None
    score, epc = ranked[0]
    if score < minimum_rssi or max(counts[epc], len(readings[epc])) < 2:
        return None
    if len(ranked) > 1 and score - ranked[1][0] < margin:
        return None
    return epc


def retry_link(operation, emitted, *, pause=time.sleep):
    for attempt in range(3):
        try:
            return operation()
        except OSError:
            if emitted() or attempt == 2:
                raise
            pause(0.7 * (attempt + 1))


class Reader:
    def __init__(self, link):
        self.link = link

    def exchange(self, command, seconds=1, *, collect=False, until=None):
        self.link.settimeout(2)
        self.link.sendall(command + b"\r\n")
        deadline = time.monotonic() + seconds
        data = bytearray()
        while time.monotonic() < deadline:
            self.link.settimeout(min(0.12, max(0.001, deadline - time.monotonic())))
            try:
                chunk = self.link.recv(4096)
            except TimeoutError:
                continue
            if not chunk:
                raise ConnectionError("RFD40 closed the connection")
            data.extend(chunk)
            if len(data) > 256 * 1024:
                raise ConnectionError("RFD40 reply exceeded 256 KiB")
            if until is not None and re.search(until, data):
                break
            if not collect and b"\r\n\r\n" in data:
                break
        return bytes(data)

    def scan(self, seconds):
        try:
            reports = self.exchange(b"inventory .incrssi", seconds, collect=True,
                                    until=rb"(?m)^Notification:StopOperation\r?$")
        finally:
            stop_ack = rb"(?m)^Command:abort\s*,Status:(?:OK|No Radio Operation in Progress)\r?$"
            tail = self.exchange(b"abort", 1.8, collect=True, until=stop_ack)
            if not re.search(stop_ack, tail):
                tail += self.exchange(b"abort", 1.2, collect=True, until=stop_ack)
            if not re.search(stop_ack, tail):
                raise ConnectionError("could not confirm the RFID inventory stopped")
        if not reports.startswith(b"Command:inventory"):
            raise ConnectionError("RFD40 did not return an inventory header")
        first_scan, stopped, _ = reports.partition(b"Notification:StopOperation")
        return first_scan if stopped and b"Notification:StartOperation" in first_scan else b""

    def verify_trigger(self):
        start = self.exchange(b"st .n", 4)
        stop = self.exchange(b"ot .n", 4)
        if not (b"Status:OK" in start and b".startonhandheldtrigger .triggertype 0 " in start
                and b"Status:OK" in stop and b".stoponhandheldtrigger .triggertype 1 " in stop):
            raise ConnectionError("RFD40 must be configured to start on trigger press and stop on release")

    def beep(self):
        try:
            on = self.exchange(b"ld .en", 0.4, collect=True)
        finally:
            off = self.exchange(b"ld .ds")
        if b"Status:OK" not in on or b"Status:OK" not in off:
            raise ConnectionError("RFD40 did not acknowledge the beeper commands")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="paired RFD40 Bluetooth address")
    parser.add_argument("--channel", type=int, choices=range(1, 31), metavar="1..30", required=True)
    parser.add_argument("--probe", action="store_true", help="verify ZETI without starting inventory")
    parser.add_argument("--beep-on-read", action="store_true", help="field test: beep after emitting an EPC")
    parser.add_argument("--minimum-rssi", type=int, default=-60)
    parser.add_argument("--margin", type=int, default=6)
    parser.add_argument("--wait", type=int, default=20, help="seconds to wait for one trigger pull and release")
    args = parser.parse_args()
    if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", args.address):
        parser.error("address must be a Bluetooth MAC")
    if args.margin < 1 or not -120 <= args.minimum_rssi <= 0:
        parser.error("margin must be positive and minimum RSSI must be between -120 and 0")
    if not 2 <= args.wait <= 60:
        parser.error("wait must be between 2 and 60 seconds")

    emitted = False

    def session():
        nonlocal emitted
        with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM) as link:
            link.settimeout(5)
            link.connect((args.address, args.channel))
            reader = Reader(link)
            if b"Connection Successful" not in reader.exchange(b"connect", 4):
                raise ConnectionError("RFD40 did not establish a ZETI session")
            if args.probe:
                if b"Command:getversion" not in reader.exchange(b"getversion", 4):
                    raise ConnectionError("RFD40 did not answer the version request")
                print("RFD40 Bluetooth RFID link OK")
                return 0
            reader.verify_trigger()
            print("Ready. Aim at the RFID tag, pull the trigger, then release it.", file=sys.stderr, flush=True)
            epc = choose_epc(reader.scan(args.wait), minimum_rssi=args.minimum_rssi, margin=args.margin)
            if epc is None:
                print("No EPC selected. Check the trigger cycle and aim at one nearby tag.", file=sys.stderr)
                return 2
            emitted = True
            print(epc, flush=True)
            if args.beep_on_read:
                reader.beep()
            return 0

    try:
        return retry_link(session, lambda: emitted)
    except (AttributeError, OSError) as exc:
        print(f"RFD40: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
