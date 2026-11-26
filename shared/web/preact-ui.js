/**
 * Preact + htm bridge for ROSY <ui-button> custom elements.
 * Syncs disabled, reason and aria-describedby after render via cause-line.js setOff()
 * so Preact never collides with UiButton._syncReason()'s light-DOM <small data-reason>.
 */
import { html, useLayoutEffect, useRef } from "/common/vendor/htm-preact.esm.min.js";
import { setOff } from "/common/cause-line.js";

/** Wrap <ui-button> so Preact props do not overwrite imperative reason/aria-describedby DOM state. */
export function UiButton({
  kind = "quiet",
  type = "button",
  class: className = "",
  disabled = false,
  reason = "",
  describedBy = "",
  onClick,
  children,
  ...rest
}) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    if (ref.current) {
      setOff(ref.current, Boolean(disabled || reason), reason || "", describedBy || "");
    }
  }, [disabled, reason, describedBy]);
  return html`<ui-button
    ref=${ref}
    kind=${kind}
    type=${type}
    class=${className || undefined}
    onClick=${onClick}
    ...${rest}
  ><span>${children}</span></ui-button>`;
}
