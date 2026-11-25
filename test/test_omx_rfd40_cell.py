import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))

from rfd40_cell import Reader, choose_epc, retry_link  # noqa: E402


HEADER = b"Command:inventory ,Status:OK,EPCId:,Firstseentime:,RSSI:,TagSeenCount:\r\n"
A = "E200001234567890"
B = "E200009876543210"


def report(epc, rssi, count):
    return f",,{epc},123,{rssi},{count}\r\n".encode()


class SelectionTests(unittest.TestCase):
    def test_strong_repeated_candidate_wins(self):
        self.assertEqual(choose_epc(HEADER + report(A, -42, 2) + report(B, -55, 1)), A)

    def test_tie_or_weak_candidate_stays_empty(self):
        self.assertIsNone(choose_epc(HEADER + report(A, -42, 2) + report(B, -45, 1)))
        self.assertIsNone(choose_epc(HEADER + report(A, -75, 8)))

    def test_single_sighting_and_empty_inventory_stay_empty(self):
        self.assertIsNone(choose_epc(HEADER + report(A, -42, 1)))
        self.assertIsNone(choose_epc(HEADER))

    def test_median_resists_one_strong_spike(self):
        data = HEADER + report(A, -30, 1) + report(A, -58, 2) + report(A, -58, 3)
        self.assertEqual(choose_epc(data + report(B, -47, 4)), B)

    def test_failed_inventory_does_not_choose_a_tag(self):
        self.assertIsNone(choose_epc(HEADER.replace(b"Status:OK", b"Status:Error") + report(A, -42, 5)))

    def test_delayed_abort_acknowledgement_confirms_stop(self):
        reader = Reader(None)
        reader.exchange = Mock(side_effect=[
            HEADER + report(A, -42, 2),
            b"",
            b"\r\nNotification:StopOperation\r\nCommand:abort,Status:OK\r\n\r\n",
        ])
        self.assertEqual(choose_epc(reader.scan(1.25)), A)

    def test_epc_encoded_as_ascii_still_preserves_full_epc(self):
        epc = "432D313200000000"
        self.assertEqual(choose_epc(HEADER + report(epc, -41, 2)), epc)

    def test_link_error_retries_but_committed_result_does_not(self):
        operation = Mock(side_effect=[TimeoutError(), 0])
        self.assertEqual(retry_link(operation, lambda: False, pause=lambda _: None), 0)
        self.assertEqual(operation.call_count, 2)
        operation = Mock(side_effect=ConnectionError())
        with self.assertRaises(ConnectionError):
            retry_link(operation, lambda: True, pause=lambda _: None)
        self.assertEqual(operation.call_count, 1)

    def test_armed_inventory_finishes_on_release_notification(self):
        socket = Mock()
        report_bytes = HEADER + report(A, -43, 2)
        socket.recv.side_effect = [report_bytes, b"Notification:StopOperation\r\n",
                                   b"Command:abort,Status:No Radio Operation in Progress\r\n\r\n"]
        reader = Reader(socket)
        self.assertEqual(choose_epc(reader.scan(20)), A)
        self.assertEqual(socket.recv.call_count, 3)
