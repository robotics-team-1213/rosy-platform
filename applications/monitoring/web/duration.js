import { valueText } from './common/value-text.js';

// Link response time (C4): a missing or invalid duration is unknown, a measured 0 is a real 0.
export function durationText(ms) {
  const known = typeof ms === 'number' && Number.isFinite(ms) && ms >= 0;
  return '응답 ' + valueText(known ? Math.round(ms) : null, { unit: 'ms' }).text;
}
