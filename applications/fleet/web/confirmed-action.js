// Fleet shell owns credentials and page lifetime; this owner also spans roster commands.
export function createConfirmedAction({scope, identity, confirm}) {
  let held = null;
  function cancel(kind) {
    if (!held || (kind && held.kind !== kind)) return;
    held.controller.abort(); held = null;
  }
  scope.onDispose(() => cancel());
  // With `note`, the confirmation also asks for it and request(owner, text) receives the trimmed text.
  async function run({message, opener, eligible, request, onError, kind = "", note = null, action = "요청 전송"}) {
    const caller = identity();
    if (held || caller.locked || caller.role !== "operator" || !eligible()) return;
    const life = scope.capture(), controller = new AbortController();
    const owner = {controller, kind, signal: AbortSignal.any([life.signal, controller.signal])};
    owner.current = () => held === owner && !owner.signal.aborted && life.current()
      && caller.token === identity().token && caller.role === identity().role && caller.principal === identity().principal && !identity().locked;
    owner.check = () => { if (!owner.current()) throw new DOMException("Command owner changed", "AbortError"); };
    held = owner;
    try {
      const answer = await confirm({message, action, opener, signal: owner.signal, ...(note ? {note} : {})});
      if (!answer || !owner.current() || !eligible()) return;
      await request(owner, answer);
    } catch (error) { if (owner.current()) onError(error); }
    finally { if (held === owner) held = null; }
  }
  return {run, cancel};
}
