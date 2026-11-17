// Node cannot resolve the browser's absolute "/common/..." imports; map them to shared/web.
import { fileURLToPath, pathToFileURL } from "node:url";
import { resolve as resolvePath } from "node:path";

const SHARED = fileURLToPath(new URL("../../../../shared/web", import.meta.url));

export async function resolve(specifier, context, next) {
  if (specifier === "/console/assets/authorization.js") {
    return next(new URL("../../../../applications/fleet/web/shared/authorization.js", import.meta.url).href, context);
  }
  if (specifier === "/console/assets/unit-scope.js") {
    return next(new URL("../../../../applications/fleet/web/shared/unit-scope.js", import.meta.url).href, context);
  }
  if (specifier === "/console/assets/poll-gate.js") {
    return next(new URL("../../../../applications/fleet/web/shared/poll-gate.js", import.meta.url).href, context);
  }
  // ui.js registers custom elements at import; the queue logic only needs a name from it.
  if (specifier === "/common/ui.js") {
    return { url: "data:text/javascript,export const actionIcon = () => null; export const canvasFont = () => ''; export const toggletip = () => null; export const readColour = () => '';", shortCircuit: true };
  }
  // shared/web/*.js import ./ui.js and ./ui-wiring.js (custom elements + document listeners); node tests need only helper exports.
  if (specifier === "./ui.js" && context.parentURL?.includes("/shared/web/")) {
    return { url: "data:text/javascript,export const actionIcon = () => null; export const canvasFont = () => ''; export const toggletip = () => null; export const readColour = () => '';", shortCircuit: true };
  }
  if (specifier === "./ui-wiring.js" && context.parentURL?.includes("/shared/web/")) {
    return { url: "data:text/javascript,export const wireUi = () => {}; export const closeMenus = () => {};", shortCircuit: true };
  }
  if (specifier.startsWith("/common/")) {
    return next(pathToFileURL(resolvePath(SHARED, specifier.slice(8))).href, context);
  }
  return next(specifier, context);
}
