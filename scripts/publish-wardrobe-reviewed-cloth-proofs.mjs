#!/usr/bin/env node

import { access, readFile, rename, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const registryPath = path.join(root, "data", "object-3d-versions.json");
const planPath = path.join(
  root,
  "data",
  "wardrobe-cloth-simulation-plan-20260728.json",
);
const batchPath = path.join(
  root,
  "data",
  "wardrobe-static-cloth-proof-batch-20260728.json",
);
const auditPath = path.join(
  root,
  "data",
  "wardrobe-reviewed-cloth-proofs-20260728.json",
);
const reviewSheetManifest =
  "/archive/objects/3d/simulations/proof-review/review-sheets.json";
const createdAt = "2026-07-28";

const materialLabels = {
  "crisp-woven": "Crisp woven",
  "felt-structured": "Structured felt",
  "knit-fuzzy": "Knit and fuzzy",
  "rigid-adornment": "Rigid adornment",
  "rigid-corsetry": "Corsetry structure",
  "satin-fluid": "Fluid satin",
  "sheer-lightweight": "Lightweight sheer",
  "stretch-jersey": "Stretch jersey",
  "structured-ruffle": "Structured ruffle",
  "tailored-heavy": "Heavy tailoring",
  "tulle-ruffle": "Tulle and ruffle",
};

const needsPrepReasons = new Map(
  Object.entries({
    "black-culottes":
      "the lower panels open into visible holes and torn edges",
    "black-deconstructed-coat-dress":
      "the skirt and lower construction break into jagged fragments",
    "black-tiered-tulle-skirt":
      "the lower tiers collapse into sharp, spiky fragments",
    "bronze-abstract-gown":
      "the reconstructed shell separates into multiple disconnected fragments",
    "burgundy-button-corset":
      "ties, straps, and trim float away from the corset body",
    "burgundy-cape-keyhole-top":
      "the lower shell melts and collapses beneath the cape",
    "burgundy-orange-circle-dress":
      "the skirt hem tears and loses its continuous circular construction",
    "burgundy-sheer-column-dress":
      "both the upper and lower shells distort instead of hanging as a column",
    "champagne-ruffle-corset-dress":
      "the ruffles and hem fragment instead of retaining layered construction",
    "multicolor-mesh-top":
      "the center panel tears open under the current proxy",
    "multicolor-ribbed-top":
      "the torso develops severe tears and cannot hold a continuous knit surface",
    "navy-bubble-skirt":
      "the bubble shell tears open instead of retaining enclosed volume",
    "navy-corset-vest":
      "the lower edge develops holes and torn panels around the negative space",
    "navy-pinstripe-ruffle-dress":
      "the layered lower shell and texture fragment during the solve",
    "navy-striped-velvet-skirt":
      "the lower skirt shell is destroyed by the current proxy",
    "navy-taffeta-dress":
      "the heavy structured shell suffers broad construction damage",
    "olive-cropped-military-jacket":
      "the jacket panels and hem separate into torn edges",
    "pink-striped-shag-sweater":
      "the lower body bunches into holes instead of preserving the sweater tube",
    "pink-tie-dye-tights":
      "a large side protrusion breaks the leg silhouette",
    "purple-ruffle-skirt":
      "the waist opening and layered panels tear under the current proxy",
    "teal-pleated-skirt":
      "the waistband and pleat direction survive, but the surface opens into large jagged patches",
    "white-lilac-corset-dress":
      "the layered skirt collapses into one damaged shell beneath the readable bodice",
  }),
);

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(temporaryPath, targetPath);
}

function publicAsset(sourcePath) {
  const relativePath = sourcePath.startsWith("public/")
    ? sourcePath.slice("public".length)
    : sourcePath;
  return relativePath.startsWith("/") ? relativePath : `/${relativePath}`;
}

async function verifyPublicAsset(assetPath) {
  await access(path.join(root, "public", assetPath.replace(/^\//, "")));
}

const [registry, plan, batch] = await Promise.all([
  readFile(registryPath, "utf8").then(JSON.parse),
  readFile(planPath, "utf8").then(JSON.parse),
  readFile(batchPath, "utf8").then(JSON.parse),
]);
const records = registry.objects;
const batchByObjectId = new Map(
  batch.objects.map((entry) => [entry.objectId, entry]),
);
let removedSimulationCount = 0;

for (const record of records) {
  if (!record.simulations) continue;
  const retained = record.simulations.filter((simulation) => {
    const shouldRemove = simulation.id === "material-aware-sphere-v1";
    if (shouldRemove) removedSimulationCount += 1;
    return !shouldRemove;
  });
  if (retained.length > 0) {
    record.simulations = retained;
  } else {
    delete record.simulations;
  }
}

const proofs = [];

for (const item of plan.objects) {
  const record = records.find((candidate) => candidate.objectId === item.objectId);
  if (!record) throw new Error(`Missing registry record: ${item.objectId}`);

  let image;
  let closeupImage;
  let scene;
  let proofFrame;

  if (item.objectId === "red-corset-top") {
    image =
      "/archive/objects/3d/simulations/red-corset-top/red-corset-top-cloth-static-proof-v1-final.png";
    closeupImage =
      "/archive/objects/3d/simulations/red-corset-top/red-corset-top-cloth-static-proof-v1-closeup.png";
    scene =
      "/archive/objects/3d/tests/red-corset-3d-sphere-sim/red-corset-3d-sphere-sim-frame80.blend";
    proofFrame = 16;
  } else {
    const batchEntry = batchByObjectId.get(item.objectId);
    if (!batchEntry || batchEntry.status !== "succeeded") {
      throw new Error(`Missing successful proof batch entry: ${item.objectId}`);
    }
    const metadata = JSON.parse(
      await readFile(path.join(root, batchEntry.assets.metadata), "utf8"),
    );
    image = publicAsset(batchEntry.assets.medium);
    closeupImage = publicAsset(batchEntry.assets.closeup);
    scene = publicAsset(batchEntry.assets.scene);
    proofFrame = metadata.settledFrame;
  }

  await Promise.all(
    [image, closeupImage, scene].map((assetPath) =>
      verifyPublicAsset(assetPath),
    ),
  );

  const prepReason = needsPrepReasons.get(item.objectId);
  const proof = {
    id: "construction-static-proof-v1",
    label: `${materialLabels[item.materialClass] || "Garment"} proof`,
    solver: "Blender cloth cage · high-res static",
    image,
    closeupImage,
    scene,
    createdAt,
    collisionObject: "Invisible sphere",
    proofFrame,
    resolution: "1280 × 1280",
    status: prepReason ? "needs-prep" : "promising",
    note: prepReason
      ? `Medium and closeup review found that ${prepReason}. Repair or rebuild the simulation proxy before rendering motion.`
      : "Medium and closeup review preserve the garment silhouette and construction at the proof frame. Approved for a focused cloth-motion pilot.",
  };

  record.clothProofs = [
    ...(record.clothProofs || []).filter(
      (candidate) => candidate.id !== proof.id,
    ),
    proof,
  ];
  proofs.push({
    objectId: item.objectId,
    name: item.name,
    materialClass: item.materialClass,
    structureMode: item.structureMode,
    ...proof,
  });
}

const promisingCount = proofs.filter(
  (proof) => proof.status === "promising",
).length;
const needsPrepCount = proofs.filter(
  (proof) => proof.status === "needs-prep",
).length;

if (proofs.length !== 66 || promisingCount !== 44 || needsPrepCount !== 22) {
  throw new Error(
    `Unexpected review totals: ${proofs.length} total, ${promisingCount} promising, ${needsPrepCount} needs prep`,
  );
}

registry.updatedAt = new Date().toISOString();
const audit = {
  schemaVersion: 1,
  createdAt: registry.updatedAt,
  mode: "visually-reviewed-high-resolution-static-proofs",
  total: proofs.length,
  promisingCount,
  needsPrepCount,
  removedSimulationCount,
  mediumResolution: "1280 × 1280",
  closeupResolution: "1280 × 1280",
  generatedVideoCount: 0,
  sourceReviewSheets: reviewSheetManifest,
  reviewMethod:
    "Manual visual review of labeled medium and closeup contact sheets, grouped by material family.",
  proofs,
};

await writeJsonAtomically(registryPath, registry);
await writeJsonAtomically(auditPath, audit);

console.log(
  JSON.stringify(
    {
      total: proofs.length,
      promisingCount,
      needsPrepCount,
      removedSimulationCount,
      auditPath: path.relative(root, auditPath),
    },
    null,
    2,
  ),
);
