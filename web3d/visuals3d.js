// Rendering-only geometry helpers for app3d.html.
// Physics coordinates, voxel masks, collision geometry, and server data never
// pass through this file.

export function roundedBoxGeometry(THREE, xDepth, yHeight, zWidth, radius, bevel) {
  const minDim = Math.min(xDepth, yHeight, zWidth);
  const b = Math.max(0, Math.min(bevel || 0, minDim * 0.18));
  const innerDepth = xDepth - 2 * b;
  const innerHeight = yHeight - 2 * b;
  const innerWidth = zWidth - 2 * b;
  if (innerDepth <= 0.02 || innerHeight <= 0.02 || innerWidth <= 0.02)
    return new THREE.BoxGeometry(xDepth, yHeight, zWidth);

  const r = Math.max(0, Math.min(radius || 0, innerHeight * 0.48, innerWidth * 0.48));
  if (r < 0.02 && b < 0.01)
    return new THREE.BoxGeometry(xDepth, yHeight, zWidth);

  const x0 = -innerWidth / 2, x1 = innerWidth / 2;
  const y0 = -innerHeight / 2, y1 = innerHeight / 2;
  const shape = new THREE.Shape();
  shape.moveTo(x0 + r, y0);
  shape.lineTo(x1 - r, y0);
  shape.quadraticCurveTo(x1, y0, x1, y0 + r);
  shape.lineTo(x1, y1 - r);
  shape.quadraticCurveTo(x1, y1, x1 - r, y1);
  shape.lineTo(x0 + r, y1);
  shape.quadraticCurveTo(x0, y1, x0, y1 - r);
  shape.lineTo(x0, y0 + r);
  shape.quadraticCurveTo(x0, y0, x0 + r, y0);

  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: innerDepth,
    steps: 1,
    curveSegments: 4,
    bevelEnabled: b > 0,
    bevelSegments: b > 0 ? 2 : 0,
    bevelSize: b,
    bevelThickness: b,
  });
  // ExtrudeGeometry is XY with depth along +Z. Centre it, then map local Z to
  // scene X so app3d's through-plane convention remains untouched.
  geometry.translate(0, 0, -innerDepth / 2);
  geometry.rotateY(Math.PI / 2);
  geometry.computeVertexNormals();
  return geometry;
}

export function disposeObjectGeometry(root, sharedMaterials = null) {
  if (!root) return;
  root.traverse(object => {
    if (object.geometry && typeof object.geometry.dispose === "function")
      object.geometry.dispose();
    if (!object.material || !sharedMaterials) return;
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      if (material && !sharedMaterials.has(material) && typeof material.dispose === "function")
        material.dispose();
    }
  });
}
