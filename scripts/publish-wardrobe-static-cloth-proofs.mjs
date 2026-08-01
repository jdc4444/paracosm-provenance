import { access, readFile, rename, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const registryPath = path.join(root, "data", "object-3d-versions.json");
const auditPath = path.join(
  root,
  "data",
  "wardrobe-static-cloth-proofs-20260728.json",
);
const createdAt = "2026-07-28";

const proofSpecs = [
  {
    objectId: "red-corset-top",
    proof: {
      id: "construction-static-proof-v1",
      label: "Corsetry structure proof",
      solver: "Blender cloth cage · high-res static",
      image:
        "/archive/objects/3d/simulations/red-corset-top/red-corset-top-cloth-static-proof-v1-final.png",
      scene:
        "/archive/objects/3d/tests/red-corset-3d-sphere-sim/red-corset-3d-sphere-sim-frame80.blend",
      createdAt,
      collisionObject: "Invisible sphere",
      proofFrame: 16,
      resolution: "1280 × 1280",
      status: "promising",
      note:
        "Early-contact frame keeps the corset body, puff sleeves, and trim readable while proving the garment can begin to conform over a curved prop.",
    },
  },
  {
    objectId: "teal-pleated-skirt",
    proof: {
      id: "construction-static-proof-v1",
      label: "Pleated panel proof",
      solver: "Blender cloth cage · high-res static",
      image:
        "/archive/objects/3d/simulations/teal-pleated-skirt/teal-pleated-skirt-cloth-static-proof-v1-final.png",
      scene:
        "/archive/objects/3d/simulations/teal-pleated-skirt/teal-pleated-skirt-cloth-static-proof-v1.blend",
      createdAt,
      collisionObject: "Invisible sphere",
      proofFrame: 28,
      resolution: "1280 × 1280",
      status: "needs-prep",
      note:
        "The waistband and pleat direction survive, but the current reconstructed surface opens into jagged patches. Rebuild it as a continuous panel before any motion render.",
    },
  },
  {
    objectId: "white-lilac-corset-dress",
    proof: {
      id: "construction-static-proof-v1",
      label: "Layered dress proof",
      solver: "Blender cloth cage · high-res static",
      image:
        "/archive/objects/3d/simulations/white-lilac-corset-dress/white-lilac-corset-dress-cloth-static-proof-v1-final.png",
      scene:
        "/archive/objects/3d/simulations/white-lilac-corset-dress/white-lilac-corset-dress-cloth-static-proof-v1.blend",
      createdAt,
      collisionObject: "Invisible sphere",
      proofFrame: 30,
      resolution: "1280 × 1280",
      status: "needs-prep",
      note:
        "The bodice stays legible, but the layered skirt collapses into one damaged shell. It needs separate structural and soft-layer proxies before simulation.",
    },
  },
  {
    objectId: "gray-opera-gloves",
    proof: {
      id: "construction-static-proof-v1",
      label: "Paired stretch proof",
      solver: "Blender cloth cage · high-res static",
      image:
        "/archive/objects/3d/simulations/gray-opera-gloves/gray-opera-gloves-cloth-static-proof-v1-final.png",
      scene:
        "/archive/objects/3d/simulations/gray-opera-gloves/gray-opera-gloves-cloth-static-proof-v1.blend",
      createdAt,
      collisionObject: "Invisible sphere",
      proofFrame: 36,
      resolution: "1280 × 1280",
      status: "promising",
      note:
        "Both gloves hold their paired identity and read as thin stretch fabric while bending independently across the curved collision surface.",
    },
  },
  {
    objectId: "olive-crochet-bag",
    proof: {
      id: "construction-static-proof-v1",
      label: "Crochet structure proof",
      solver: "Blender cloth cage · high-res static",
      image:
        "/archive/objects/3d/simulations/olive-crochet-bag/olive-crochet-bag-cloth-static-proof-v1-final.png",
      scene:
        "/archive/objects/3d/simulations/olive-crochet-bag/olive-crochet-bag-cloth-static-proof-v1.blend",
      createdAt,
      collisionObject: "Invisible sphere",
      proofFrame: 24,
      resolution: "1280 × 1280",
      status: "promising",
      note:
        "The dense crochet body keeps its volume while the long strap relaxes naturally, making this a useful soft-structured material direction.",
    },
  },
];

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(temporaryPath, targetPath);
}

const registry = JSON.parse(await readFile(registryPath, "utf8"));
const records = registry.objects;
let removedSimulationCount = 0;

for (const record of records) {
  if (!record.simulations) continue;
  const retained = record.simulations.filter((simulation) => {
    const remove = simulation.id === "material-aware-sphere-v1";
    if (remove) removedSimulationCount += 1;
    return !remove;
  });
  if (retained.length > 0) {
    record.simulations = retained;
  } else {
    delete record.simulations;
  }
}

for (const { objectId, proof } of proofSpecs) {
  const record = records.find((candidate) => candidate.objectId === objectId);
  if (!record) throw new Error(`Missing registry record: ${objectId}`);

  for (const assetPath of [proof.image, proof.scene]) {
    await access(path.join(root, "public", assetPath.replace(/^\//, "")));
  }

  record.clothProofs = [
    ...(record.clothProofs || []).filter(
      (candidate) => candidate.id !== proof.id,
    ),
    proof,
  ];
}

registry.updatedAt = new Date().toISOString();
const audit = {
  schemaVersion: 1,
  createdAt: registry.updatedAt,
  mode: "high-resolution-static-proofs",
  proofCount: proofSpecs.length,
  removedSimulationCount,
  resolution: "1280 × 1280",
  generatedVideoCount: 0,
  proofs: proofSpecs.map(({ objectId, proof }) => ({
    objectId,
    ...proof,
  })),
};

await writeJsonAtomically(registryPath, registry);
await writeJsonAtomically(auditPath, audit);

console.log(
  JSON.stringify(
    {
      proofCount: proofSpecs.length,
      removedSimulationCount,
      auditPath: path.relative(root, auditPath),
    },
    null,
    2,
  ),
);
