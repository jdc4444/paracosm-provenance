#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import {
  access,
  mkdir,
  readFile,
  rename,
  writeFile,
} from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const reviewPath = path.join(
  root,
  "data/wardrobe-reviewed-cloth-proofs-20260728.json",
);
const manifestPath = path.join(
  root,
  "data/houdini-wardrobe-rescue-batch-20260728.json",
);
const logDirectory = path.join(
  root,
  "data/houdini-wardrobe-rescue-logs-20260728",
);
const houdini = path.join(
  "/Applications/Houdini/Houdini22.0.368/Frameworks",
  "Houdini.framework/Versions/Current/Resources/bin/hython",
);
const blender = "/Applications/Blender.app/Contents/MacOS/Blender";
const houdiniScript = path.join(
  root,
  "scripts/build_houdini_wardrobe_vellum_pilot.py",
);
const blenderScript = path.join(
  root,
  "scripts/render_houdini_wardrobe_vellum_proof.py",
);
const force = process.argv.includes("--force");
const idArgumentIndex = process.argv.indexOf("--ids");
const selectedIds =
  idArgumentIndex >= 0
    ? new Set(process.argv[idArgumentIndex + 1].split(","))
    : null;

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(temporaryPath, targetPath);
}

function assetPaths(objectId) {
  const directory = path.join(
    root,
    `public/archive/objects/3d/simulations/${objectId}/houdini-vellum-v1`,
  );
  const stem = `${objectId}-houdini-vellum-v1`;
  return {
    directory,
    metadata: path.join(directory, `${stem}-metadata.json`),
    medium: path.join(directory, `${stem}-medium.png`),
    closeup: path.join(directory, `${stem}-closeup.png`),
    scene: path.join(directory, `${stem}.hipnc`),
    model: path.join(directory, `${stem}-frame28.obj`),
    renderScene: path.join(directory, `${stem}-render.blend`),
  };
}

async function assetsComplete(paths) {
  try {
    await Promise.all(
      [
        paths.metadata,
        paths.medium,
        paths.closeup,
        paths.scene,
        paths.model,
        paths.renderScene,
      ].map((assetPath) => access(assetPath)),
    );
    const metadata = JSON.parse(await readFile(paths.metadata, "utf8"));
    return Boolean(
      metadata.render?.medium &&
        metadata.render?.closeup &&
        metadata.frame === 28,
    );
  } catch {
    return false;
  }
}

function run(command, args) {
  return spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    maxBuffer: 50 * 1024 * 1024,
  });
}

await mkdir(logDirectory, { recursive: true });
const review = JSON.parse(await readFile(reviewPath, "utf8"));
const rescueItems = review.proofs
  .filter((item) => item.status === "needs-prep")
  .filter((item) => !selectedIds || selectedIds.has(item.objectId));

let existingManifest = null;
try {
  existingManifest = JSON.parse(await readFile(manifestPath, "utf8"));
} catch {
  // First run.
}
const previousById = new Map(
  (existingManifest?.objects || []).map((item) => [item.objectId, item]),
);
const manifest = {
  schemaVersion: 1,
  startedAt: existingManifest?.startedAt || new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  mode: "non-commercial-apprentice-static-rescue-proofs",
  concurrency: 1,
  force,
  total: rescueItems.length,
  succeeded: 0,
  failed: 0,
  running: 0,
  pending: rescueItems.length,
  objects: rescueItems.map((item) => ({
    objectId: item.objectId,
    name: item.name,
    materialClass: item.materialClass,
    structureMode: item.structureMode,
    status: previousById.get(item.objectId)?.status || "pending",
  })),
};

async function persist() {
  manifest.updatedAt = new Date().toISOString();
  manifest.succeeded = manifest.objects.filter(
    (item) => item.status === "succeeded",
  ).length;
  manifest.failed = manifest.objects.filter(
    (item) => item.status === "failed",
  ).length;
  manifest.running = manifest.objects.filter(
    (item) => item.status === "running",
  ).length;
  manifest.pending = manifest.objects.filter(
    (item) => item.status === "pending",
  ).length;
  await writeJsonAtomically(manifestPath, manifest);
}

await persist();

for (const entry of manifest.objects) {
  const paths = assetPaths(entry.objectId);
  if (!force && (await assetsComplete(paths))) {
    entry.status = "succeeded";
    entry.resumed = true;
    entry.finishedAt =
      previousById.get(entry.objectId)?.finishedAt || new Date().toISOString();
    await persist();
    console.log(
      `[${manifest.succeeded}/${manifest.total}] reused ${entry.objectId}`,
    );
    continue;
  }

  entry.status = "running";
  entry.startedAt = new Date().toISOString();
  entry.resumed = false;
  await persist();
  console.log(`starting ${entry.objectId}`);

  const startedAtMs = Date.now();
  const houdiniResult = run(houdini, [
    houdiniScript,
    "--object-id",
    entry.objectId,
  ]);
  let blenderResult = null;
  if (houdiniResult.status === 0) {
    blenderResult = run(blender, [
      "--background",
      "--python",
      blenderScript,
      "--",
      "--object-id",
      entry.objectId,
    ]);
  }

  const log = [
    "HOUDINI STDOUT",
    houdiniResult.stdout || "",
    "HOUDINI STDERR",
    houdiniResult.stderr || "",
    "BLENDER STDOUT",
    blenderResult?.stdout || "",
    "BLENDER STDERR",
    blenderResult?.stderr || "",
  ].join("\n");
  await writeFile(path.join(logDirectory, `${entry.objectId}.log`), log);

  const complete = await assetsComplete(paths);
  if (
    houdiniResult.status !== 0 ||
    blenderResult?.status !== 0 ||
    !complete
  ) {
    entry.status = "failed";
    entry.error = {
      houdiniExitCode: houdiniResult.status,
      blenderExitCode: blenderResult?.status ?? null,
      assetsComplete: complete,
    };
  } else {
    entry.status = "succeeded";
    entry.assets = Object.fromEntries(
      Object.entries(paths)
        .filter(([key]) => key !== "directory")
        .map(([key, value]) => [key, path.relative(root, value)]),
    );
    entry.durationSeconds = Math.round((Date.now() - startedAtMs) / 1000);
  }
  entry.finishedAt = new Date().toISOString();
  await persist();
  console.log(
    `[${manifest.succeeded}/${manifest.total}] ${entry.status} ${entry.objectId} (${entry.durationSeconds || 0}s)`,
  );
}

manifest.finishedAt = new Date().toISOString();
await persist();
console.log(
  JSON.stringify(
    {
      total: manifest.total,
      succeeded: manifest.succeeded,
      failed: manifest.failed,
      manifestPath: path.relative(root, manifestPath),
    },
    null,
    2,
  ),
);
