#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import { access, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const registryPath = path.join(root, "data/object-3d-versions.json");
const manifestPath = path.join(
  root,
  "data/houdini-wardrobe-floor-v4-pilots-20260729.json",
);
const reviewPath = path.join(
  root,
  "data/houdini-wardrobe-floor-v4-reviewed-20260729.json",
);

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(temporaryPath, targetPath);
}

async function verifyPublicAsset(publicPath) {
  await access(path.join(root, "public", publicPath.replace(/^\//, "")));
}

const [registry, manifest, review] = await Promise.all(
  [registryPath, manifestPath, reviewPath].map((filePath) =>
    readFile(filePath, "utf8").then(JSON.parse),
  ),
);
if (
  manifest.schemaVersion !== 4 ||
  manifest.total !== 3 ||
  manifest.succeeded !== 3 ||
  manifest.failed !== 0
) {
  throw new Error(
    `Refusing to publish incomplete v4 pilots: ${manifest.succeeded}/${manifest.total} succeeded, ${manifest.failed} failed`,
  );
}

const manifestById = new Map(
  manifest.objects.map((record) => [record.objectId, record]),
);
const registryById = new Map(
  registry.objects.map((record) => [record.objectId, record]),
);
const published = [];
const held = [];

for (const decision of review.records) {
  const manifestRecord = manifestById.get(decision.objectId);
  if (!manifestRecord || manifestRecord.status !== "succeeded") {
    throw new Error(`Missing completed v4 pilot for ${decision.objectId}`);
  }
  const registryRecord = registryById.get(decision.objectId);
  if (!registryRecord) {
    throw new Error(`Missing 3D registry record for ${decision.objectId}`);
  }
  if (!decision.publish) {
    held.push(decision.objectId);
    continue;
  }

  const metadata = JSON.parse(
    await readFile(path.join(root, manifestRecord.assets.metadata), "utf8"),
  );
  const proof = {
    id: "houdini-vellum-floor-v4",
    label: "Houdini Vellum floor v4",
    solver: "Houdini 22 Vellum · garment-derived proxy",
    image: metadata.render.medium,
    closeupImage: metadata.render.closeup,
    scene: metadata.assets.scene,
    model: metadata.assets.model,
    createdAt: "2026-07-29",
    collisionObject: "Actual floor + lateral bunching gates",
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
  published.push(decision.objectId);
}

registry.updatedAt = new Date().toISOString();
review.publishedAt = registry.updatedAt;
review.published = published;
review.held = held;
await writeJsonAtomically(registryPath, registry);
await writeJsonAtomically(reviewPath, review);

console.log(
  JSON.stringify(
    {
      published,
      held,
      registryPath: path.relative(root, registryPath),
      reviewPath: path.relative(root, reviewPath),
    },
    null,
    2,
  ),
);
