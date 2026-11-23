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
  // ui.js registers custom elements at import; the queue logic only needs a name from it.
  if (specifier === "/common/ui.js") {
    return { url: "data:text/javascript,export const actionIcon = () => null; export const iconSvg = () => null; export const readColour = () => ''; export const cssColor = () => ''; export const toggletip = () => null;", shortCircuit: true };
  }
  if (specifier.startsWith("/common/")) {
    return next(pathToFileURL(resolvePath(SHARED, specifier.slice(8))).href, context);
  }
  return next(specifier, context);
}
