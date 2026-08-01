#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const registryPath = path.join(root, "data/object-3d-versions.json");
const runPath = path.join(
  root,
  "data/meshy-casually-tossed-test-v2-20260728.json",
);

const reviews = new Map([
  [
    "black-culottes",
    {
      status: "review",
      note: "Casually tossed pose reconstruction. It forms a convincing low floor pose with distinct leg openings, waistband, broad folded legs, and useful localized wrinkling. Treat as a static pose candidate, not a physical simulation.",
    },
  ],
  [
    "black-deconstructed-coat-dress",
    {
      status: "needs-fix",
      note: "Casually tossed pose comparison only. The layered skirt and red stitch accents survive, but Meshy re-inflates and props up the tailored torso so it still reads partly mannequin-like rather than casually tossed on the floor.",
    },
  ],
  [
    "black-tiered-tulle-skirt",
    {
      status: "review",
      note: "Casually tossed pose reconstruction. The model keeps the open waistband, tied waist detail, layered tiers, and a believable low floor spread. The tulle is reconstructed as mostly opaque fabric, so use it as a static shape candidate rather than a material-faithful simulation.",
    },
  ],
]);

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await fs.rename(temporaryPath, targetPath);
}

const [registry, run] = await Promise.all(
  [registryPath, runPath].map((filePath) =>
    fs.readFile(filePath, "utf8").then(JSON.parse),
  ),
);
if (run.objects.some((item) => item.status !== "succeeded")) {
  throw new Error("Refusing to register an incomplete Meshy comparison");
}
const registryById = new Map(
  registry.objects.map((record) => [record.objectId, record]),
);
for (const item of run.objects) {
  const record = registryById.get(item.objectId);
  const review = reviews.get(item.objectId);
  if (!record || !review) {
    throw new Error(`Missing registry or review record for ${item.objectId}`);
  }
  if (!record.primaryVersionId) {
    record.primaryVersionId =
      record.versions.findLast(
        (candidate) => candidate.id !== "meshy-casually-tossed-v1",
      )?.id || record.versions.at(-1)?.id;
  }
  const version = {
    id: "meshy-casually-tossed-v1",
    label: "Casually tossed v1",
    provider: "Meshy 6 pose reconstruction",
    model: item.model,
    thumbnail: `/archive/objects/3d/reviews/${item.objectId}-casually-tossed-v1/${item.objectId}-casually-tossed-v1-top.png`,
    createdAt: "2026-07-28",
    taskId: item.taskId,
    faces: item.faces,
    vertices: item.vertices,
    status: review.status,
    note: review.note,
  };
  await Promise.all(
    [version.model, version.thumbnail].map((assetPath) =>
      fs.access(path.join(root, "public", assetPath.replace(/^\//, ""))),
    ),
  );
  record.versions = [
    ...record.versions.filter((candidate) => candidate.id !== version.id),
    version,
  ];
}
registry.updatedAt = new Date().toISOString();
await writeJsonAtomically(registryPath, registry);
console.log(
  JSON.stringify({
    registered: run.objects.map((item) => item.objectId),
    primaryVersionsPreserved: run.objects.map((item) => ({
      objectId: item.objectId,
      primaryVersionId:
        registryById.get(item.objectId)?.primaryVersionId || null,
    })),
  }),
);
