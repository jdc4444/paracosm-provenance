#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import { access, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const defaultIds = [
  "pink-striped-shag-sweater",
  "navy-taffeta-dress",
  "burgundy-button-corset",
];
const idArgumentIndex = process.argv.indexOf("--ids");
const selectedIds =
  idArgumentIndex >= 0
    ? process.argv[idArgumentIndex + 1].split(",")
    : defaultIds;
const force = process.argv.includes("--force");
const proxyUv = process.argv.includes("--proxy-uv");
const dropOnly = process.argv.includes("--drop-only");
const surfaceMode = proxyUv ? "proxy-uv" : "source-deform";
const compressionMode = dropOnly ? "drop-only" : "gates";
const variant = proxyUv
  ? "houdini-floor-v4-proxy"
  : dropOnly
    ? "houdini-floor-v4-drop"
    : "houdini-floor-v4";
const manifestPath = path.join(
  root,
  proxyUv
    ? "data/houdini-wardrobe-floor-v4-proxy-pilots-20260729.json"
    : dropOnly
      ? "data/houdini-wardrobe-floor-v4-drop-pilots-20260729.json"
      : "data/houdini-wardrobe-floor-v4-pilots-20260729.json",
);
const logDirectory = path.join(
  root,
  proxyUv
    ? "data/houdini-wardrobe-floor-v4-proxy-logs-20260729"
    : dropOnly
      ? "data/houdini-wardrobe-floor-v4-drop-logs-20260729"
      : "data/houdini-wardrobe-floor-v4-logs-20260729",
);
const houdini = path.join(
  "/Applications/Houdini/Houdini22.0.368/Frameworks",
  "Houdini.framework/Versions/Current/Resources/bin/hython",
);
const blender = "/Applications/Blender.app/Contents/MacOS/Blender";
const houdiniScript = path.join(
  root,
  "scripts/build_houdini_wardrobe_vellum_floor_v4.py",
);
const blenderScript = path.join(
  root,
  "scripts/render_houdini_wardrobe_vellum_floor_v4.py",
);

async function writeJsonAtomically(targetPath, value) {
  const temporaryPath = `${targetPath}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(temporaryPath, targetPath);
}

function pathsFor(objectId) {
  const directory = path.join(
    root,
    `public/archive/objects/3d/simulations/${objectId}/${variant}`,
  );
  const stem = `${objectId}-${variant}`;
  return {
    directory,
    metadata: path.join(directory, `${stem}-metadata.json`),
    medium: path.join(directory, `${stem}-medium.png`),
    closeup: path.join(directory, `${stem}-closeup.png`),
    scene: path.join(directory, `${stem}.hipnc`),
    model: path.join(directory, `${stem}-frame72.obj`),
    renderScene: path.join(directory, `${stem}-render.blend`),
  };
}

async function complete(paths) {
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
      metadata.schemaVersion === 4 &&
        metadata.frame === 72 &&
        metadata.surfaceMode === surfaceMode &&
        metadata.compressionMode === compressionMode &&
        metadata.render?.texturePreserved &&
        metadata.render?.surfaceMode === surfaceMode &&
        metadata.render?.compressionMode === compressionMode &&
        metadata.render?.presentation,
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
let manifest;
try {
  manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (manifest.schemaVersion !== 4 || !Array.isArray(manifest.objects)) {
    throw new Error("Incompatible v4 manifest");
  }
} catch {
  manifest = {
    schemaVersion: 4,
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    mode: proxyUv
      ? "watertight-silhouette-proxy-uv-floor-pilots"
      : dropOnly
        ? "watertight-silhouette-proxy-textured-floor-drop-pilots"
        : "watertight-silhouette-proxy-textured-floor-pilots",
    total: 0,
    succeeded: 0,
    failed: 0,
    objects: [],
  };
}
manifest.force = force;
manifest.lastRunStartedAt = new Date().toISOString();
for (const objectId of selectedIds) {
  if (!manifest.objects.some((record) => record.objectId === objectId)) {
    manifest.objects.push({ objectId, status: "pending" });
  }
}
const selectedRecords = selectedIds.map((objectId) =>
  manifest.objects.find((record) => record.objectId === objectId),
);

async function persist() {
  manifest.updatedAt = new Date().toISOString();
  manifest.succeeded = manifest.objects.filter(
    (item) => item.status === "succeeded",
  ).length;
  manifest.failed = manifest.objects.filter(
    (item) => item.status === "failed",
  ).length;
  manifest.total = manifest.objects.length;
  await writeJsonAtomically(manifestPath, manifest);
}

await persist();
for (const record of selectedRecords) {
  const paths = pathsFor(record.objectId);
  if (!force && (await complete(paths))) {
    record.status = "succeeded";
    record.resumed = true;
    await persist();
    console.log(`reused ${record.objectId}`);
    continue;
  }

  record.status = "running";
  record.startedAt = new Date().toISOString();
  await persist();
  console.log(`starting ${record.objectId}`);
  const startedAtMs = Date.now();
  const houdiniResult = run(houdini, [
    houdiniScript,
    "--object-id",
    record.objectId,
    "--surface-mode",
    surfaceMode,
    "--compression-mode",
    compressionMode,
  ]);
  let blenderResult = null;
  if (houdiniResult.status === 0) {
    blenderResult = run(blender, [
      "--background",
      "--python",
      blenderScript,
      "--",
      "--object-id",
      record.objectId,
      "--surface-mode",
      surfaceMode,
      "--compression-mode",
      compressionMode,
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
  await writeFile(
    path.join(logDirectory, `${record.objectId}.log`),
    log,
  );
  if (
    houdiniResult.status !== 0 ||
    blenderResult?.status !== 0 ||
    !(await complete(paths))
  ) {
    record.status = "failed";
    record.error = {
      houdiniExitCode: houdiniResult.status,
      blenderExitCode: blenderResult?.status ?? null,
      assetsComplete: await complete(paths),
    };
  } else {
    record.status = "succeeded";
    record.assets = Object.fromEntries(
      Object.entries(paths)
        .filter(([key]) => key !== "directory")
        .map(([key, value]) => [key, path.relative(root, value)]),
    );
  }
  record.durationSeconds = Math.round((Date.now() - startedAtMs) / 1000);
  record.finishedAt = new Date().toISOString();
  await persist();
  console.log(
    `${record.status} ${record.objectId} (${record.durationSeconds}s)`,
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
      manifest: path.relative(root, manifestPath),
    },
    null,
    2,
  ),
);
