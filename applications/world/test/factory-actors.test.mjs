import test from "node:test";
import assert from "node:assert/strict";

import { createFactoryLayer } from "../web/factory-actors.js";

function makeThreeMock() {
  class Vector3 {
    constructor(x = 0, y = 0, z = 0) { this.x = x; this.y = y; this.z = z; }
    set(x, y, z) { this.x = x; this.y = y; this.z = z; }
  }
  class Object3D {
    constructor() {
      this.children = [];
      this.visible = true;
      this.position = new Vector3();
      this.rotation = { x: 0, y: 0, z: 0 };
    }
    add(...items) { this.children.push(...items); }
    traverse(fn) { fn(this); for (const c of this.children) c.traverse?.(fn); }
  }
  class Mesh extends Object3D {
    constructor(geometry, material) {
      super();
      this.isMesh = true;
      this.geometry = geometry;
      this.material = material;
      this.castShadow = false;
      this.receiveShadow = false;
    }
  }
  class Mat {
    constructor(props = {}) { Object.assign(this, props); this.color = { setHex() {} }; }
    clone() { return new Mat(this); }
  }
  class Geom { setFromPoints() { return this; } computeBoundingSphere() {} }
  return {
    DoubleSide: 2,
    RepeatWrapping: 1000,
    RGBAFormat: 1023,
    SRGBColorSpace: "srgb",
    Color: class { constructor() { this.r = 0.5; this.g = 0.5; this.b = 0.5; } },
    DataTexture: class {},
    Vector3,
    Group: Object3D,
    Mesh,
    Line: Object3D,
    BufferGeometry: Geom,
    BoxGeometry: Geom,
    PlaneGeometry: Geom,
    RingGeometry: Geom,
    MeshBasicMaterial: Mat,
    MeshStandardMaterial: Mat,
    LineBasicMaterial: Mat,
    CanvasTexture: class {},
  };
}

test("createFactoryLayer renders dynamic Pinky ids and hides absent roster ids", () => {
  const prevDoc = globalThis.document;
  const prevRaf = globalThis.requestAnimationFrame;
  globalThis.document = {
    createElement() {
      const ctx = {
        fillStyle: "",
        strokeStyle: "",
        lineWidth: 0,
        fillRect() {},
        beginPath() {},
        moveTo() {},
        lineTo() {},
        stroke() {},
      };
      return { width: 0, height: 0, getContext: () => ctx };
    },
  };
  globalThis.requestAnimationFrame = () => 0;
  try {
    const three = makeThreeMock();
    const scene = new three.Group();
    const labels = [];
    const layer = createFactoryLayer({
      three,
      scene,
      redraw: () => {},
      addLabel: (_group, id) => {
        const lbl = { visible: true, id };
        labels.push(lbl);
        return lbl;
      },
    });
    layer.apply({
      pinkys: [
        { id: "rosy_42", pose_m: [0.1, 0.2, 0.0], yaw_rad: 0.5, observed: true },
        { id: "rosy_99", pose_m: [0.5, -0.1, 0.0], yaw_rad: 1.5, observed: true },
      ],
      arms: {},
    }, 0, true);

    assert.ok(labels.some((l) => l.id === "rosy_99"), "dynamic Pinky rosy_99 actor created");
    const root = scene.children[0];
    assert.equal(root.visible, true);
    const taggedGroups = root.children.filter((c) => c.children.some((g) => g.isMesh));
    // Default 3 Pinkys (42, 45, 46) + dynamic rosy_99: 45 and 46 are hidden when omitted from state.pinkys.
    assert.equal(labels.filter((l) => l.id === "rosy_45" || l.id === "rosy_46").length, 2);
    const visiblePinkyGroups = root.children.filter(
      (c) => c.visible === true && c.children.length > 0 && c.position && (c.position.x === 0.1 || c.position.x === 0.5),
    );
    assert.equal(visiblePinkyGroups.length, 2);
    assert.ok(taggedGroups.length >= 4);
  } finally {
    globalThis.document = prevDoc;
    globalThis.requestAnimationFrame = prevRaf;
  }
});
