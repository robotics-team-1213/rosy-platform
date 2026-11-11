"""D-998 pre-cutover producer seam; the Fleet outbox/worker remain authoritative."""


class FleetDeliveryProducer:
    def __init__(self, *, enabled=False, legacy_enabled=True):
        if enabled and legacy_enabled:
            raise ValueError('MULTIPLE_NOTIFICATION_SEND_OWNERS')
        if enabled:
            raise ValueError('NOTIFICATION_CUTOVER_NOT_ACCEPTED')
        self.enabled = False

    def submit(self, outbox_row):
        """Future adapter must preserve the original identity and UNKNOWN rows."""
        return None
