// Draft snapshots only; no persistence or robot requests.
const MAX_SNAPSHOTS = 50, MAX_BYTES = 8 * 1024 * 1024;

export function createEditHistory(initialMap) {
  let snapshots = [], index = 0;
  const encode = map => {
    const text = JSON.stringify(map), bytes = new TextEncoder().encode(text).byteLength;
    if (bytes > MAX_BYTES) throw new Error('편집 이력 한도를 넘었습니다. 지도를 나누어 저장하세요');
    return {text, bytes};
  };
  const current = () => JSON.parse(snapshots[index].text);
  const reset = map => { snapshots = [encode(map)]; index = 0; return current(); };
  reset(initialMap);
  return {
    current, reset,
    apply(map) {
      const next = encode(map);
      if (next.text === snapshots[index].text) return current();
      snapshots = [...snapshots.slice(0, index + 1), next];
      let bytes = snapshots.reduce((sum, entry) => sum + entry.bytes, 0);
      while (snapshots.length > MAX_SNAPSHOTS || bytes > MAX_BYTES) bytes -= snapshots.shift().bytes;
      index = snapshots.length - 1;
      return current();
    },
    undo() { if (index > 0) index--; return current(); },
    redo() { if (index + 1 < snapshots.length) index++; return current(); },
    canUndo: () => index > 0,
    canRedo: () => index + 1 < snapshots.length,
  };
}
