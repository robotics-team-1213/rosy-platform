/**
 * Framework-free access to server-judged evidence states (D-999, D-157).
 *
 * The server owns freshness thresholds. This adapter deliberately contains no
 * clock math; every surface consumes the same per-channel evidence enum while
 * retaining its own visual grammar.
 */

const EVIDENCE_STATES = new Set(["fresh", "delayed", "disconnected", "unavailable"]);

export class HeadlessState {
  constructor(statePayload) {
    this.state = statePayload || {};
  }

  evidenceOf(channel) {
    const judged = this.state.evidence?.[channel]?.evidence;
    return EVIDENCE_STATES.has(judged) ? judged : "disconnected";
  }

  isFresh(channel) {
    return this.evidenceOf(channel) === "fresh";
  }

  isDelayed(channel) {
    return this.evidenceOf(channel) === "delayed";
  }

  isDisconnected(channel) {
    return this.evidenceOf(channel) === "disconnected";
  }

  getValue(fieldPath, evidenceField, fallback = "?") {
    if (!this.isFresh(evidenceField)) return fallback;

    let value = this.state;
    for (const key of fieldPath.split(".")) {
      if (value === undefined || value === null) return fallback;
      value = value[key];
    }
    return value !== undefined && value !== null ? value : fallback;
  }
}
