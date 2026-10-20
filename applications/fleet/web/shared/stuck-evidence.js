// Network load: the open stuck's live front picture as raw JPEG, not base64 in JSON (+33 %).
// Fleet answers `Accept: image/jpeg` with the bytes and the metadata in X-Stuck-Evidence;
// the picture is shown through a blob URL that PreviewMap releases when its entry goes.

export async function loadEvidence(call, robotId, stuckId) {
  const { blob, headers } = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/line-stuck/evidence`
    + `?stuck_id=${encodeURIComponent(stuckId)}&live=true`, { headers: { Accept: "image/jpeg" }, blob: true });
  return { ...JSON.parse(headers.get("X-Stuck-Evidence") || "{}"), url: URL.createObjectURL(blob) };
}

const release = (entry) => { if (entry?.preview?.url) URL.revokeObjectURL(entry.preview.url); };

// robot_id -> preview entry; replacing or dropping an entry releases its blob URL.
// shortcut: an answer that arrives after its stuck closed is dropped without release (one URL
// per such race until the page closes); release it at the drop site if that ever matters.
export class PreviewMap extends Map {
  set(key, value) { release(this.get(key)); return super.set(key, value); }
  delete(key) { release(this.get(key)); return super.delete(key); }
  clear() { for (const entry of this.values()) release(entry); super.clear(); }
}
