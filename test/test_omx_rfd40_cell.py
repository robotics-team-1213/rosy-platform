import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy/robot/omx"))

from rfd40_cell import Reader, choose_epc, main, retry_link  # noqa: E402


HEADER = b"Command:inventory ,Status:OK,EPCId:,Firstseentime:,RSSI:,TagSeenCount:\r\n"
START = b"Notification:StartOperation\r\n"
STOP = b"Notification:StopOperation\r\n"
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
            HEADER + START + report(A, -42, 2) + STOP,
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
        socket.recv.side_effect = [HEADER + START + report(A, -43, 2), STOP,
                                   b"Command:abort,Status:No Radio Operation in Progress\r\n\r\n"]
        reader = Reader(socket)
        self.assertEqual(choose_epc(reader.scan(20)), A)
        self.assertEqual(socket.recv.call_count, 3)

    def test_successive_scans_accept_split_abort_and_record_delimiters(self):
        socket = Mock()
        ack = b"Command:abort,Status:OK"
        socket.recv.side_effect = [
            HEADER + START + report(A, -43, 2) + STOP[:-2],
            b"\r\n",
            ack,
            b"\r\n",
            b"\r\n" + HEADER + START + report(B, -43, 2) + STOP,
            ack + b"\r\n\r\n",
        ]
        reader = Reader(socket)

        self.assertEqual(choose_epc(reader.scan(20)), A)
        self.assertEqual(choose_epc(reader.scan(20)), B)

    def test_incomplete_trigger_and_odd_hex_do_not_emit(self):
        reader = Reader(None)
        reader.exchange = Mock(side_effect=[
            HEADER + START + report(A, -42, 2), b"Command:abort,Status:OK\r\n",
        ])
        self.assertIsNone(choose_epc(reader.scan(20)))
        self.assertIsNone(choose_epc(HEADER + report("432D3", -42, 2)))

    def test_immediate_trigger_configuration_is_rejected(self):
        reader = Reader(None)
        reader.exchange = Mock(side_effect=[
            b"Command:setstarttrigger .ignorehandheldtrigger .triggertype 0 ,Status:OK",
            b"Command:setstoptrigger .stoponhandheldtrigger .triggertype 1 ,Status:OK",
        ])
        with self.assertRaises(ConnectionError):
            reader.verify_trigger()


class ListenerTests(unittest.TestCase):
    def run_listener(self, open_reader, pause):
        output, status = StringIO(), StringIO()
        args = ["rfd40_cell.py", "00:11:22:33:44:55", "--channel", "2", "--listen", "--beep-on-read"]
        with patch.object(sys, "argv", args), patch("rfd40_cell.open_reader", open_reader), \
                patch("rfd40_cell.time.sleep", pause), redirect_stdout(output), redirect_stderr(status):
            exit_code = main()
        self.assertEqual(exit_code, 130, status.getvalue())
        return output.getvalue().splitlines()

    def test_listener_reuses_link_and_reconnects_without_replaying_a_report(self):
        first, second, third = (Mock(spec=Reader) for _ in range(3))
        first.scan.side_effect = [b"", HEADER + report(A, -42, 2), ConnectionError("link lost")]
        second.scan.return_value = HEADER + report(B, -42, 2)
        second.beep.side_effect = BrokenPipeError("beeper link lost")
        third.scan.side_effect = KeyboardInterrupt
        scopes = [Mock(__enter__=Mock(return_value=reader), __exit__=Mock(return_value=False))
                  for reader in (first, second, third)]
        opener, pause = Mock(side_effect=scopes), Mock()

        self.assertEqual(self.run_listener(opener, pause), [A, B])
        self.assertEqual(opener.call_count, 3)
        self.assertEqual(first.scan.call_count, 3)
        first.verify_trigger.assert_called_once()
        second.verify_trigger.assert_called_once()
        first.beep.assert_called_once()
        second.beep.assert_called_once()
        self.assertEqual(pause.call_count, 2)
        for scope in scopes:
            scope.__exit__.assert_called_once()

    def test_listener_bounds_its_retry_delays_and_resets_after_a_working_scan(self):
        reader = Mock(spec=Reader)
        reader.scan.side_effect = [b"", ConnectionError("link lost")]
        scope = Mock(__enter__=Mock(return_value=reader), __exit__=Mock(return_value=False))
        opener = Mock(side_effect=[ConnectionError("offline")] * 9 + [scope, KeyboardInterrupt])
        pause = Mock()

        self.assertEqual(self.run_listener(opener, pause), [])
        delays = [call.args[0] for call in pause.call_args_list]
        self.assertEqual(delays, [1, 2, 4, 8, 16, 30, 30, 30, 30, 1])
