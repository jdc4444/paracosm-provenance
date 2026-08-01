#!/usr/bin/env node

import { access, readFile, rename, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const registryPath = path.join(root, "data", "object-3d-versions.json");
const metadataPath = path.join(
  root,
  "public/archive/objects/3d/simulations/navy-bubble-skirt/houdini-vellum-v1/navy-bubble-skirt-houdini-vellum-v1-metadata.json",
);
const auditPath = path.join(
  root,
  "data",
  "houdini-navy-bubble-vellum-pilot-20260728.json",
);

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(temporaryPath, targetPath);
}

async function verifyPublicAsset(assetPath) {
  await access(path.join(root, "public", assetPath.replace(/^\//, "")));
}

const [registry, metadata] = await Promise.all([
  readFile(registryPath, "utf8").then(JSON.parse),
  readFile(metadataPath, "utf8").then(JSON.parse),
]);
const record = registry.objects.find(
  (candidate) => candidate.objectId === "navy-bubble-skirt",
);
if (!record) throw new Error("Missing Navy Bubble Skirt registry record");

const proof = {
  id: "houdini-vellum-pilot-v1",
  label: "Houdini Vellum bubble-volume pilot",
  solver: "Houdini 22 Vellum · Apprentice proof",
  image: metadata.render.medium,
  closeupImage: metadata.render.closeup,
  scene: metadata.assets.scene,
  model: metadata.assets.model,
  createdAt: "2026-07-28",
  collisionObject: "Invisible sphere",
  proofFrame: metadata.frame,
  resolution: "1280 × 1280",
  status: "promising",
  license: "Apprentice · non-commercial",
  note:
    "A clean continuous quad proxy, satin cloth constraints, and volume struts preserve the waistband, gathered channels, and bubble hem under deformation. This materially improves on the torn Blender proxy while remaining an explicitly non-commercial Houdini Apprentice pilot.",
};

await Promise.all(
  [proof.image, proof.closeupImage, proof.scene, proof.model].map(
    verifyPublicAsset,
  ),
);

record.clothProofs = [
  ...(record.clothProofs || []).filter(
    (candidate) => candidate.id !== proof.id,
  ),
  proof,
];
registry.updatedAt = new Date().toISOString();

const audit = {
  schemaVersion: 1,
  createdAt: registry.updatedAt,
  objectId: record.objectId,
  decision: "promising",
  comparison:
    "The Houdini Vellum proof retains a continuous waistband and bubble volume without the large shell tears visible in construction-static-proof-v1.",
  generatedVideoCount: 0,
  proof,
  metadata: metadata.assets,
};

await writeJsonAtomically(registryPath, registry);
await writeJsonAtomically(auditPath, audit);

console.log(
  JSON.stringify(
    {
      objectId: record.objectId,
      clothProofCount: record.clothProofs.length,
      proofId: proof.id,
      status: proof.status,
      auditPath: path.relative(root, auditPath),
    },
    null,
    2,
  ),
);
