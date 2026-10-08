// Node cannot resolve the browser's absolute "/common/..." imports; map them to shared/web.
import { fileURLToPath, pathToFileURL } from "node:url";
import { resolve as resolvePath } from "node:path";

const SHARED = fileURLToPath(new URL("../../../../shared/web", import.meta.url));

export async function resolve(specifier, context, next) {
  // ui.js registers custom elements at import; the queue logic only needs a name from it.
  if (specifier === "/common/ui.js") {
    return { url: "data:text/javascript,export const actionIcon = () => null;", shortCircuit: true };
  }
  if (specifier.startsWith("/common/")) {
    return next(pathToFileURL(resolvePath(SHARED, specifier.slice(8))).href, context);
  }
  return next(specifier, context);
}
