/**
 * Shared lazy loader and in-memory cache for Three.js and parsed robot URDF/STL assets.
 * Three.js is fetched via dynamic import only when loadThree() is first called.
 */
import { parseUrdf, parseStl } from "./robot-3d-model.js";

const MODELS = Object.freeze({ arm: "omx-f.urdf", mobile: "pinky-pro.urdf" });

const THREE_URL = new URL("/common/vendor/three.module.min.js", import.meta.url).href;
let threeLoad = null;
const modelLoads = new Map();

export function loadThree() {
  return (threeLoad ??= import(THREE_URL).catch((error) => {
    threeLoad = null;
    throw error;
  }));
}

async function fetchAsset(url, kind) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return kind === "text" ? response.text() : response.arrayBuffer();
}

export function loadRobotModel(kind) {
  if (!Object.hasOwn(MODELS, kind)) {
    return Promise.reject(new RangeError(`unknown robot model kind: ${kind}`));
  }
  if (!modelLoads.has(kind)) {
    const base = new URL(`/common/meshes/${MODELS[kind]}`, import.meta.url);
    modelLoads.set(kind, (async () => {
      const model = parseUrdf(await fetchAsset(base.href, "text"));
      const meshes = {};
      const names = [...new Set(Object.values(model.links).map((link) => link.mesh).filter(Boolean))];
      await Promise.all(names.map(async (name) => {
        meshes[name] = parseStl(await fetchAsset(new URL(name, base).href, "buffer"));
      }));
      return { model, meshes };
    })().catch((error) => {
      modelLoads.delete(kind);
      throw error;
    }));
  }
  return modelLoads.get(kind);
}
