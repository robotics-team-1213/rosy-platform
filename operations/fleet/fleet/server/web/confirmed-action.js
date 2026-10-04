// Fleet shell owns credentials and page lifetime; this owner also spans roster commands.
export function createConfirmedAction({scope, identity, confirm}) {
  let held = null;
  function cancel(kind) {
    if (!held || (kind && held.kind !== kind)) return;
    held.controller.abort(); held = null;
  }
  scope.onDispose(() => cancel());
  async function run({message, opener, eligible, request, onError, kind = ""}) {
    const caller = identity();
    if (held || caller.locked || caller.role !== "operator" || !eligible()) return;
    const life = scope.capture(), controller = new AbortController();
    const owner = {controller, kind, signal: AbortSignal.any([life.signal, controller.signal])};
    owner.current = () => held === owner && !owner.signal.aborted && life.current()
      && caller.token === identity().token && caller.role === identity().role && !identity().locked;
    owner.check = () => { if (!owner.current()) throw new DOMException("Command owner changed", "AbortError"); };
    held = owner;
    try {
      if (!await confirm({message, action: "요청 전송", opener, signal: owner.signal}) || !owner.current() || !eligible()) return;
      await request(owner);
    } catch (error) { if (owner.current()) onError(error); }
    finally { if (held === owner) held = null; }
  }
  return {run, cancel};
}
