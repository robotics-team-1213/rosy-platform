// Articulated 6-DOF OMX-AI arm assembly matching shared/web/meshes/omx-f.urdf.

const meshCache = new Map();

function parseBinaryStl(buffer, three) {
  const view = new DataView(buffer);
  const count = view.getUint32(80, true);
  const expected = 84 + count * 50;
  if (buffer.byteLength < expected) throw new Error("Invalid OMX link STL");
  const pos = new Float32Array(count * 9);
  for (let i = 0; i < count; i += 1) {
    const off = 84 + i * 50;
    const dst = i * 9;
    for (let v = 0; v < 3; v += 1) {
      const src = off + 12 + v * 12;
      pos[dst + v * 3] = view.getFloat32(src, true);
      pos[dst + v * 3 + 1] = view.getFloat32(src + 4, true);
      pos[dst + v * 3 + 2] = view.getFloat32(src + 8, true);
    }
  }
  const geo = new three.BufferGeometry();
  geo.setAttribute("position", new three.BufferAttribute(pos, 3));
  geo.computeVertexNormals();
  return geo;
}

export function loadBinaryStl(three, url) {
  if (!meshCache.has(url)) {
    const p = fetch(url, { redirect: "error" }).then((r) => {
      if (!r.ok) throw new Error(`Cannot load ${url}`);
      return r.arrayBuffer();
    }).then((buf) => parseBinaryStl(buf, three));
    meshCache.set(url, p);
  }
  return meshCache.get(url);
}

export async function loadOmxArmMeshes(three, baseUrl = "./common/meshes") {
  const keys = [0, 1, 2, 3, 4, 5, 6, 7];
  const entries = await Promise.all(keys.map(async (idx) => (
    [idx, await loadBinaryStl(three, `${baseUrl}/omx-link${idx}.stl`)]
  )));
  return Object.fromEntries(entries);
}

export function createArticulatedOmxArm(three, geometries, {
  name, baseSite, baseYaw, accentHex = 0x58a6ff, addLabel,
}) {
  const darkMat = new three.MeshStandardMaterial({
    color: 0x2a313d, metalness: 0.58, roughness: 0.34, envMapIntensity: 1.1,
  });
  const jawMat = new three.MeshStandardMaterial({
    color: 0xdce2ea, metalness: 0.32, roughness: 0.38, envMapIntensity: 1.0,
  });
  const accentMat = new three.MeshStandardMaterial({
    color: accentHex, emissive: accentHex, emissiveIntensity: 0.35, metalness: 0.4, roughness: 0.3,
  });

  const makeLink = (idx, mat = darkMat) => {
    const mesh = new three.Mesh(geometries[idx], mat);
    mesh.castShadow = mesh.receiveShadow = true;
    return mesh;
  };

  const root = new three.Group();
  root.position.set(baseSite[0], baseSite[1], baseSite[2]);
  root.rotation.z = baseYaw;
  root.add(makeLink(0));

  const j1 = new three.Group();
  j1.position.set(-0.01125, 0, 0.034);
  j1.add(makeLink(1));
  root.add(j1);

  const j2 = new three.Group();
  j2.position.set(0, 0, 0.0635);
  j2.add(makeLink(2));
  j1.add(j2);

  const j3 = new three.Group();
  j3.position.set(0.0415, 0, 0.11315);
  j3.add(makeLink(3));
  const collar = new three.Mesh(new three.BoxGeometry(0.022, 0.034, 0.018), accentMat);
  collar.position.set(0.08, 0, 0.008);
  j3.add(collar);
  j2.add(j3);

  const j4 = new three.Group();
  j4.position.set(0.162, 0, 0);
  j4.add(makeLink(4));
  j3.add(j4);

  const j5 = new three.Group();
  j5.position.set(0.0287, 0, 0);
  j5.add(makeLink(5));
  j4.add(j5);

  const g1 = new three.Group();
  g1.position.set(0.0295, 0.0075, 0);
  g1.add(makeLink(6, jawMat));
  const g2 = new three.Group();
  g2.position.set(0.0295, -0.0108, 0);
  g2.add(makeLink(7, jawMat));
  j5.add(g1, g2);

  const label = addLabel?.(root, name, new three.Vector3(0, 0, 0.27));

  function setJoints(q) {
    if (!Array.isArray(q) || q.length < 5) return;
    j1.rotation.z = q[0];
    j2.rotation.y = q[1];
    j3.rotation.y = q[2];
    j4.rotation.y = q[3];
    j5.rotation.x = q[4];
    const grip = Number.isFinite(q[5]) ? q[5] : 0.7;
    g1.rotation.z = grip;
    g2.rotation.z = -grip;
  }

  return { root, label, setJoints };
}
