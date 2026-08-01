#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import { access, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const registryPath = path.join(root, "data", "object-3d-versions.json");
const batchPath = path.join(
  root,
  "data",
  "houdini-wardrobe-rescue-batch-20260728.json",
);
const reviewPath = path.join(
  root,
  "data",
  "houdini-wardrobe-rescue-reviewed-20260728.json",
);

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(temporaryPath, targetPath);
}

function toPublicPath(filePath) {
  return `/${path
    .relative(path.join(root, "public"), path.join(root, filePath))
    .split(path.sep)
    .join("/")}`;
}

async function verifyPublicAsset(publicPath) {
  await access(path.join(root, "public", publicPath.replace(/^\//, "")));
}

const [registry, batch, review] = await Promise.all(
  [registryPath, batchPath, reviewPath].map((filePath) =>
    readFile(filePath, "utf8").then(JSON.parse),
  ),
);
if (batch.total !== 22 || batch.succeeded !== 22 || batch.failed !== 0) {
  throw new Error(
    `Refusing to publish incomplete Houdini batch: ${batch.succeeded}/${batch.total} succeeded, ${batch.failed} failed`,
  );
}
if (review.total !== 22 || review.records.length !== 22) {
  throw new Error(`Expected 22 reviewed records, found ${review.records.length}`);
}

const batchById = new Map(
  batch.objects.map((record) => [record.objectId, record]),
);
const registryById = new Map(
  registry.objects.map((record) => [record.objectId, record]),
);

for (const decision of review.records) {
  if (!["promising", "needs-prep"].includes(decision.status)) {
    throw new Error(
      `Invalid Houdini review status for ${decision.objectId}: ${decision.status}`,
    );
  }
  const batchRecord = batchById.get(decision.objectId);
  const registryRecord = registryById.get(decision.objectId);
  if (!batchRecord || batchRecord.status !== "succeeded") {
    throw new Error(`Missing completed batch record for ${decision.objectId}`);
  }
  if (!registryRecord) {
    throw new Error(`Missing registry record for ${decision.objectId}`);
  }
  const metadataPath =
    batchRecord.assets?.metadata ||
    `public/archive/objects/3d/simulations/${decision.objectId}/houdini-vellum-v1/${decision.objectId}-houdini-vellum-v1-metadata.json`;
  const metadata = JSON.parse(
    await readFile(path.join(root, metadataPath), "utf8"),
  );
  const proof = {
    id: "houdini-vellum-pilot-v1",
    label: "Houdini Vellum rescue proof",
    solver: "Houdini 22 Vellum · Apprentice proof",
    image: metadata.render.medium,
    closeupImage: metadata.render.closeup,
    scene: metadata.assets.scene,
    model: metadata.assets.model,
    createdAt: "2026-07-28",
    collisionObject: "Invisible sphere",
    proofFrame: metadata.frame,
    resolution: "1280 × 1280",
    status: decision.status,
    license: "Apprentice · non-commercial",
    note: decision.note,
  };
  await Promise.all(
    [proof.image, proof.closeupImage, proof.scene, proof.model].map(
      verifyPublicAsset,
    ),
  );
  registryRecord.clothProofs = [
    ...(registryRecord.clothProofs || []).filter(
      (candidate) => candidate.id !== proof.id,
    ),
    proof,
  ];
  decision.proof = proof;
  decision.metadata = {
    sourceModel: metadata.sourceModel,
    proxyKind: metadata.proxyKind,
    frame: metadata.frame,
    assets: metadata.assets,
    render: metadata.render,
  };
}

registry.updatedAt = new Date().toISOString();
review.publishedAt = registry.updatedAt;
review.promisingCount = review.records.filter(
  (record) => record.status === "promising",
).length;
review.needsPrepCount = review.records.filter(
  (record) => record.status === "needs-prep",
).length;
review.generatedVideoCount = 0;
review.batchManifest = toPublicPath(
  "public/archive/objects/3d/simulations/houdini-rescue-review/review-sheets.json",
);

await writeJsonAtomically(registryPath, registry);
await writeJsonAtomically(reviewPath, review);

console.log(
  JSON.stringify(
    {
      total: review.total,
      promising: review.promisingCount,
      needsPrep: review.needsPrepCount,
      generatedVideoCount: review.generatedVideoCount,
      registryPath: path.relative(root, registryPath),
      reviewPath: path.relative(root, reviewPath),
    },
    null,
    2,
  ),
);
