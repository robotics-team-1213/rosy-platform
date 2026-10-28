// Canvas capture is local synthetic media, with the same lifecycle callbacks as native WHEP.
export async function openRobotCamera({video, onState, renewGrant, revokeGrant}) {
  const canvas = document.createElement('canvas'); canvas.width = 480; canvas.height = 270;
  const context = canvas.getContext('2d');
  let state = 'live', closed = false, frame = 0;
  function draw() {
    if (closed || state !== 'live') return;
    context.fillStyle = '#173642'; context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = '#e9f3ef'; context.font = '24px sans-serif';
    context.fillText('ROSY SAMPLE · ' + ++frame, 30, 130);
  }
  draw();
  const stream = canvas.captureStream(5);
  video.srcObject = stream;
  const timer = setInterval(draw, 200);
  const emit = value => { state = value; onState({state, fps:5, ageMs:state === 'stale' ? 1500 : 0}); };
  function close(reason = 'closed') {
    if (closed) return;
    closed = true; clearInterval(timer); removeEventListener('rosy-sample-media', event);
    stream.getTracks().forEach(track => track.stop()); video.srcObject = null;
    onState({state:'closed', reason});
    Promise.resolve().then(() => revokeGrant?.()).catch(() => {});
  }
  function event({detail}) {
    if (closed) return;
    if (detail.state === 'renew') {
      Promise.resolve().then(() => renewGrant?.()).catch(() => emit('lost'));
    } else if (['live', 'stale', 'hidden', 'lost'].includes(detail.state)) emit(detail.state);
  }
  addEventListener('rosy-sample-media', event);
  emit('live');
  return {close};
}
