#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const registryPath = path.join(root, "data/object-3d-versions.json");
const reviewPath = path.join(
  root,
  "data/houdini-wardrobe-rescue-reviewed-20260728.json",
);
const heldNote =
  "Held after textured and neutral review: the v1 generic garment-family proxy and Cloth Capture transfer stretch or distort source geometry. Texture can expose the deformation but does not cause it. Keep this only as a solver diagnostic; rebuild from clean sewn panels or simulation-ready retopology before approval.";

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await fs.rename(temporaryPath, targetPath);
}

const [registry, review] = await Promise.all(
  [registryPath, reviewPath].map((filePath) =>
    fs.readFile(filePath, "utf8").then(JSON.parse),
  ),
);

let registryCount = 0;
for (const record of registry.objects) {
  for (const proof of record.clothProofs || []) {
    if (proof.id !== "houdini-vellum-pilot-v1") continue;
    proof.label = "Houdini Vellum diagnostic v1";
    proof.status = "needs-prep";
    proof.note = heldNote;
    registryCount += 1;
  }
}
for (const record of review.records) {
  record.status = "needs-prep";
  record.note = heldNote;
  if (record.proof?.id === "houdini-vellum-pilot-v1") {
    record.proof.label = "Houdini Vellum diagnostic v1";
    record.proof.status = "needs-prep";
    record.proof.note = heldNote;
  }
}
review.promisingCount = 0;
review.needsPrepCount = review.records.length;
review.reReviewedAt = new Date().toISOString();
review.reReviewReason =
  "Systemic geometry-transfer distortion confirmed by textured and neutral floor tests.";
registry.updatedAt = review.reReviewedAt;

if (registryCount !== review.records.length) {
  throw new Error(
    `Registry/review mismatch: ${registryCount} proofs vs ${review.records.length} decisions`,
  );
}
await Promise.all([
  writeJsonAtomically(registryPath, registry),
  writeJsonAtomically(reviewPath, review),
]);
console.log(
  JSON.stringify({
    held: registryCount,
    promising: review.promisingCount,
    needsPrep: review.needsPrepCount,
  }),
);
