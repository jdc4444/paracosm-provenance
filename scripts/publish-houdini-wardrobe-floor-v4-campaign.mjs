#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import { access, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const registryPath = path.join(root, "data/object-3d-versions.json");
const campaignPath = path.join(
  root,
  "data/houdini-wardrobe-floor-v4-campaign-reviewed-20260729.json",
);
const gatedManifestPath = path.join(
  root,
  "data/houdini-wardrobe-floor-v4-pilots-20260729.json",
);
const dropManifestPath = path.join(
  root,
  "data/houdini-wardrobe-floor-v4-drop-pilots-20260729.json",
);

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(temporaryPath, targetPath);
}

async function verifyPublicAsset(publicPath) {
  await access(path.join(root, "public", publicPath.replace(/^\//, "")));
}

const [registry, campaign, gatedManifest, dropManifest] = await Promise.all(
  [
    registryPath,
    campaignPath,
    gatedManifestPath,
    dropManifestPath,
  ].map((filePath) => readFile(filePath, "utf8").then(JSON.parse)),
);

const accepted = campaign.records.filter((record) => record.accepted);
if (
  campaign.targetAccepted !== 20 ||
  campaign.acceptedCount !== 20 ||
  accepted.length !== 20 ||
  new Set(accepted.map((record) => record.objectId)).size !== 20
) {
  throw new Error(
    `Refusing to publish campaign with ${accepted.length}/${campaign.targetAccepted} accepted proofs`,
  );
}

const registryById = new Map(
  registry.objects.map((record) => [record.objectId, record]),
);
const manifestsByVariant = new Map([
  [
    "houdini-floor-v4",
    new Map(
      gatedManifest.objects.map((record) => [record.objectId, record]),
    ),
  ],
  [
    "houdini-floor-v4-drop",
    new Map(
      dropManifest.objects.map((record) => [record.objectId, record]),
    ),
  ],
]);
const reviewedById = new Map(
  campaign.records.map((record) => [record.objectId, record]),
);

const proofIds = new Set([
  "houdini-vellum-floor-v4",
  "houdini-vellum-floor-v4-drop",
]);
for (const registryRecord of registry.objects) {
  const decision = reviewedById.get(registryRecord.objectId);
  if (decision?.accepted) {
    continue;
  }
  registryRecord.clothProofs = (registryRecord.clothProofs || []).filter(
    (proof) => !proofIds.has(proof.id),
  );
}

const published = [];
for (const decision of accepted) {
  const variant = decision.proofVariant || "houdini-floor-v4";
  const manifestRecord = manifestsByVariant
    .get(variant)
    ?.get(decision.objectId);
  if (!manifestRecord || manifestRecord.status !== "succeeded") {
    throw new Error(
      `Missing completed ${variant} proof for ${decision.objectId}`,
    );
  }
  const registryRecord = registryById.get(decision.objectId);
  if (!registryRecord) {
    throw new Error(`Missing 3D registry record for ${decision.objectId}`);
  }

  const dropOnly = variant === "houdini-floor-v4-drop";
  const metadata = JSON.parse(
    await readFile(path.join(root, manifestRecord.assets.metadata), "utf8"),
  );
  const recordedSurfaceMode = metadata.surfaceMode || "source-deform";
  const recordedCompressionMode = metadata.compressionMode || "gates";
  if (
    recordedSurfaceMode !== "source-deform" ||
    recordedCompressionMode !== (dropOnly ? "drop-only" : "gates") ||
    metadata.frame !== 72 ||
    !metadata.render?.texturePreserved ||
    !metadata.render?.uvPreserved
  ) {
    throw new Error(`Incomplete source-faithful metadata for ${decision.objectId}`);
  }

  const proof = {
    id: dropOnly
      ? "houdini-vellum-floor-v4-drop"
      : "houdini-vellum-floor-v4",
    label: dropOnly
      ? "Houdini Vellum floor drop v4"
      : "Houdini Vellum floor v4",
    solver: "Houdini 22 Vellum · garment-derived proxy",
    image: metadata.render.medium,
    closeupImage: metadata.render.closeup,
    scene: metadata.assets.scene,
    model: metadata.assets.model,
    createdAt: "2026-07-29",
    collisionObject: dropOnly
      ? "Actual floor · gravity + self collision"
      : "Actual floor + lateral bunching gates",
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
campaign.publishedAt = registry.updatedAt;
campaign.published = published;
campaign.held = campaign.records
  .filter((record) => !record.accepted)
  .map((record) => record.objectId);
await writeJsonAtomically(registryPath, registry);
await writeJsonAtomically(campaignPath, campaign);

console.log(
  JSON.stringify(
    {
      publishedCount: published.length,
      published,
      heldCount: campaign.held.length,
      registryPath: path.relative(root, registryPath),
      campaignPath: path.relative(root, campaignPath),
    },
    null,
    2,
  ),
);
