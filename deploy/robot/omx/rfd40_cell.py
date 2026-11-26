"""Field adapter for a Zebra RFD40 RFID Serial Port (Bluetooth Classic SPP)."""

import argparse
import collections
import re
import socket
import statistics
import sys
import time
from contextlib import contextmanager, nullcontext


def choose_epc(data, *, minimum_rssi=-60, margin=6, require_single=False):
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
    if not ranked or (require_single and len(ranked) != 1):
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

    def scan(self, seconds, *, require_coverage=False):
        stop_notice = rb"(?m)^Notification:StopOperation\r?\n"
        try:
            reports = self.exchange(b"inventory .incrssi", seconds, collect=True, until=stop_notice)
        finally:
            stop_ack = rb"(?m)^Command:abort[ \t]*,Status:(?:OK|No Radio Operation in Progress)\r?\n"
            tail = self.exchange(b"abort", 1.8, collect=True, until=stop_ack)
            if not re.search(stop_ack, tail):
                tail += self.exchange(b"abort", 1.2, collect=True, until=stop_ack)
            if not re.search(stop_ack, tail):
                raise ConnectionError("could not confirm the RFID inventory stopped")
        reports = reports.lstrip(b"\r\n")
        if not reports.startswith(b"Command:inventory"):
            raise ConnectionError("RFD40 did not return an inventory header")
        if require_coverage:
            header = {field.strip().rstrip(b":").lower() for field in reports.splitlines()[0].split(b",")}
            if not {b"status:ok", b"epcid", b"rssi", b"tagseencount"} <= header:
                raise ConnectionError("RFD40 inventory was not ready")
            if re.search(rb"(?m)^(?:Notification:(?:Start|Stop)Operation|,,)", tail):
                raise ConnectionError("RFID trigger overlapped the end of inventory")
        stopped = re.search(stop_notice, reports)
        if require_coverage and not stopped and (b"Notification:StartOperation" in reports or b"\n,," in reports):
            raise ConnectionError("RFID trigger cycle did not finish")
        if stopped is None:
            return b""
        first_scan = reports[:stopped.start()]
        if require_coverage and (len(re.findall(rb"(?m)^Notification:StartOperation\r?\n", first_scan)) != 1
                                 or reports.count(b"Notification:StopOperation") != 1
                                 or reports[stopped.end():].strip()):
            raise ConnectionError("RFID operation boundaries are ambiguous")
        return first_scan if re.search(rb"(?m)^Notification:StartOperation\r?\n", first_scan) else b""

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


@contextmanager
def open_reader(address, channel):
    with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM) as link:
        link.settimeout(5)
        link.connect((address, channel))
        reader = Reader(link)
        if b"Connection Successful" not in reader.exchange(b"connect", 4):
            raise ConnectionError("RFD40 did not establish a ZETI session")
        yield reader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="paired RFD40 Bluetooth address")
    parser.add_argument("--channel", type=int, choices=range(1, 31), metavar="1..30", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="verify ZETI without starting inventory")
    mode.add_argument("--listen", action="store_true", help="keep reading trigger cycles and reconnect on link loss")
    parser.add_argument("--beep-on-read", action="store_true", help="field test: beep after emitting an EPC")
    parser.add_argument("--ordered-intake", metavar="ARM", help="persist trigger results and coverage for the authenticated Cell")
    parser.add_argument("--minimum-rssi", type=int, default=-60)
    parser.add_argument("--margin", type=int, default=6)
    parser.add_argument("--wait", type=int, default=20, help="seconds to wait for one trigger pull and release")
    args = parser.parse_args()
    if args.ordered_intake and not args.listen:
        parser.error("--ordered-intake requires --listen")
    if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", args.address):
        parser.error("address must be a Bluetooth MAC")
    if args.margin < 1 or not -120 <= args.minimum_rssi <= 0:
        parser.error("margin must be positive and minimum RSSI must be between -120 and 0")
    if not 2 <= args.wait <= 60:
        parser.error("wait must be between 2 and 60 seconds")

    emitted = False
    delay = 1

    def session():
        nonlocal emitted, delay
        with open_reader(args.address, args.channel) as reader:
            if args.probe:
                if b"Command:getversion" not in reader.exchange(b"getversion", 4):
                    raise ConnectionError("RFD40 did not answer the version request")
                print("RFD40 Bluetooth RFID link OK")
                return 0
            reader.verify_trigger()
            if capture:
                capture.connected()
            print("Ready. Aim at the RFID tag, pull the trigger, then release it.", file=sys.stderr, flush=True)
            while True:
                reports = reader.scan(args.wait, require_coverage=True) if capture else reader.scan(args.wait)
                delay = 1
                epc = choose_epc(reports, minimum_rssi=args.minimum_rssi, margin=args.margin,
                                 require_single=bool(capture))
                if capture:
                    capture.record(epc, triggered=bool(reports), max_interval=args.wait + 10)
                if epc is None:
                    if args.listen:
                        continue
                    print("No EPC selected. Check the trigger cycle and aim at one nearby tag.", file=sys.stderr)
                    return 2
                try:
                    if not capture:
                        print(epc, flush=True)
                except BrokenPipeError:
                    print("RFD40: EPC consumer closed the output", file=sys.stderr)
                    return 1
                emitted = True
                if args.beep_on_read:
                    reader.beep()
                if not args.listen:
                    return 0

    try:
        operation = nullcontext()
        if args.ordered_intake:
            from rfd40_ordered_outbox import ordered_capture
            operation = ordered_capture(args.ordered_intake)
        with operation as capture:
            if not args.listen:
                return retry_link(session, lambda: emitted)
            while True:
                try:
                    return session()
                except OSError as exc:
                    print(f"RFD40: {exc}; reconnecting in {delay}s", file=sys.stderr, flush=True)
                    time.sleep(delay)
                    delay = min(30, delay * 2)
    except KeyboardInterrupt:
        return 130
    except (AttributeError, OSError) as exc:
        print(f"RFD40: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
