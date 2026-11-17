"""D-998 pre-cutover producer seam; the Fleet outbox/worker remain authoritative."""

from __future__ import annotations

from fleet.incidents.notification_client import build_delivery_request, delivery_notification_id


class FleetDeliveryProducer:
    def __init__(self, *, enabled=False, legacy_enabled=True, sink=None, cutover_accepted=False):
        if enabled and legacy_enabled:
            raise ValueError('MULTIPLE_NOTIFICATION_SEND_OWNERS')
        if enabled and not cutover_accepted:
            raise ValueError('NOTIFICATION_CUTOVER_NOT_ACCEPTED')
        if enabled and sink is None:
            raise ValueError('NOTIFICATION_SINK_REQUIRED')
        self.enabled = bool(enabled)
        self.sink = sink

    def submit(self, outbox_row, facts=None):
        """Future adapter must preserve the original identity and UNKNOWN rows."""
        if not self.enabled:
            return None
        if outbox_row.get('state') == 'UNKNOWN':
            return {
                'notification_id': delivery_notification_id(outbox_row),
                'state': 'UNKNOWN',
            }
        payload = build_delivery_request(outbox_row, facts)
        return self.sink.submit_delivery(payload)

