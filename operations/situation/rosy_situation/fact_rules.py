"""Command words are forbidden in advisory facts in both producer and consumer."""

COMMAND_WORDS = frozenset({"WAIT", "RESUME", "BACK_AND_RETRY", "YIELD", "ABORT", "MANUAL", "STOP", "GO"})
