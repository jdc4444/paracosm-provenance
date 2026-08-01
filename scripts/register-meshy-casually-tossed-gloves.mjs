#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const registryPath = path.join(root, "data/object-3d-versions.json");
const runPath = path.join(
  root,
  "data/meshy-casually-tossed-gloves-v2-20260729.json",
);

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
const item = run.object;
if (item.status !== "succeeded") {
  throw new Error("Refusing to register an incomplete Meshy glove run");
}
const record = registry.objects.find(
  (candidate) => candidate.objectId === item.objectId,
);
if (!record) {
  throw new Error(`Missing registry record for ${item.objectId}`);
}
if (!record.primaryVersionId) {
  record.primaryVersionId =
    record.versions.findLast(
      (candidate) => candidate.id !== "meshy-casually-tossed-v1",
    )?.id || record.versions.at(-1)?.id;
}

const reviewDirectory = `/archive/objects/3d/reviews/${item.objectId}-casually-tossed-v2`;
const version = {
  id: "meshy-casually-tossed-v1",
  label: "Casually tossed gloves v1",
  provider: "Meshy 6 pose reconstruction",
  model: item.model,
  thumbnail: `${reviewDirectory}/${item.objectId}-casually-tossed-v2-top.png`,
  createdAt: "2026-07-29",
  taskId: item.taskId,
  faces: item.faces,
  vertices: item.vertices,
  status: "review",
  note: "Meshy reconstruction of the white-background casually tossed reference. Review the two-glove separation, finger anatomy, cuff openings, pale fabric, and red piping before promoting it over the original multiview model.",
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
registry.updatedAt = new Date().toISOString();
await writeJsonAtomically(registryPath, registry);
console.log(
  JSON.stringify({
    registered: item.objectId,
    versionId: version.id,
    primaryVersionId: record.primaryVersionId,
    taskId: item.taskId,
  }),
);
