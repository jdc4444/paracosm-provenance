#!/usr/bin/env node

import { spawn } from "node:child_process";
import {
  access,
  mkdir,
  readFile,
  rename,
  writeFile,
} from "node:fs/promises";
import { constants as fsConstants } from "node:fs";
import path from "node:path";
import process from "node:process";

const root = "/Users/alphaone/Documents/Code/paracosm-provenance";
const blender = "/Applications/Blender.app/Contents/MacOS/Blender";
const builder = path.join(
  root,
  "scripts/build_wardrobe_material_cloth_sim.py",
);
const planPath = path.join(
  root,
  "data/wardrobe-cloth-simulation-plan-20260728.json",
);
const runPath = path.join(
  root,
  "data/wardrobe-static-cloth-proof-batch-20260728.json",
);
const logDirectory = path.join(
  root,
  "data/wardrobe-static-cloth-proof-logs-20260728",
);

const concurrencyFlag = process.argv.indexOf("--concurrency");
const concurrency = Math.max(
  1,
  Math.min(
    3,
    concurrencyFlag >= 0
      ? Number.parseInt(process.argv[concurrencyFlag + 1], 10) || 2
      : 2,
  ),
);
const idsFlag = process.argv.indexOf("--ids");
const requestedIds =
  idsFlag >= 0
    ? new Set(
        (process.argv[idsFlag + 1] || "")
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
      )
    : null;
const force = process.argv.includes("--force");
let atomicWriteCounter = 0;

async function exists(filePath) {
  try {
    await access(filePath, fsConstants.F_OK);
    return true;
  } catch {
    return false;
  }
}

async function writeJsonAtomic(filePath, value) {
  atomicWriteCounter += 1;
  const temporaryPath = `${filePath}.${process.pid}.${Date.now()}.${atomicWriteCounter}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await rename(temporaryPath, filePath);
}

function proofPaths(objectId) {
  const directory = path.join(
    root,
    "public/archive/objects/3d/simulations",
    objectId,
  );
  const stem = `${objectId}-cloth-static-proof-v1`;
  return {
    directory,
    metadata: path.join(directory, `${stem}-metadata.json`),
    medium: path.join(directory, `${stem}-final.png`),
    closeup: path.join(directory, `${stem}-closeup.png`),
    settledModel: path.join(directory, `${stem}-settled.glb`),
    scene: path.join(directory, `${stem}.blend`),
  };
}

function runBlender(entry, logPath) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      blender,
      [
        "--background",
        "--factory-startup",
        "--python",
        builder,
        "--",
        "--object-id",
        entry.objectId,
        "--proof-static",
      ],
      {
        cwd: root,
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    const output = [];
    child.stdout.on("data", (chunk) => output.push(chunk));
    child.stderr.on("data", (chunk) => output.push(chunk));
    child.on("error", reject);
    child.on("close", async (code) => {
      const log = Buffer.concat(output).toString("utf8");
      await writeFile(logPath, log);
      if (code === 0) resolve(log);
      else {
        reject(
          new Error(
            `Blender exited ${code}; see ${path.relative(root, logPath)}`,
          ),
        );
      }
    });
  });
}

const plan = JSON.parse(await readFile(planPath, "utf8"));
let entries = plan.objects.filter((entry) => !entry.existingSimulation);
if (requestedIds) {
  entries = entries.filter((entry) => requestedIds.has(entry.objectId));
  const found = new Set(entries.map((entry) => entry.objectId));
  const missing = [...requestedIds].filter((objectId) => !found.has(objectId));
  if (missing.length > 0) {
    throw new Error(`Unknown or excluded proof ids: ${missing.join(", ")}`);
  }
}
await mkdir(logDirectory, { recursive: true });

const run = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  mode: "high-resolution-medium-and-closeup-static-proofs",
  concurrency,
  force,
  total: entries.length,
  succeeded: 0,
  failed: 0,
  running: 0,
  pending: entries.length,
  objects: entries.map((entry) => ({
    objectId: entry.objectId,
    materialClass: entry.materialClass,
    structureMode: entry.structureMode,
    status: "pending",
  })),
};

let persistChain = Promise.resolve();
function persist() {
  persistChain = persistChain.then(async () => {
    run.updatedAt = new Date().toISOString();
    for (const status of ["succeeded", "failed", "running", "pending"]) {
      run[status] = run.objects.filter(
        (entry) => entry.status === status,
      ).length;
    }
    await writeJsonAtomic(runPath, run);
  });
  return persistChain;
}

async function buildOne(entry) {
  const runEntry = run.objects.find(
    (candidate) => candidate.objectId === entry.objectId,
  );
  const paths = proofPaths(entry.objectId);
  runEntry.status = "running";
  runEntry.startedAt = new Date().toISOString();
  await persist();

  try {
    await mkdir(paths.directory, { recursive: true });
    const required = [
      paths.metadata,
      paths.medium,
      paths.closeup,
      paths.settledModel,
      paths.scene,
    ];
    const completeBeforeRun = (
      await Promise.all(required.map((filePath) => exists(filePath)))
    ).every(Boolean);
    if (force || !completeBeforeRun) {
      await runBlender(
        entry,
        path.join(logDirectory, `${entry.objectId}.blender.log`),
      );
    }
    const missingAfterRun = [];
    for (const filePath of required) {
      if (!(await exists(filePath))) {
        missingAfterRun.push(path.relative(root, filePath));
      }
    }
    if (missingAfterRun.length > 0) {
      throw new Error(`Missing proof assets: ${missingAfterRun.join(", ")}`);
    }
    const metadata = JSON.parse(await readFile(paths.metadata, "utf8"));
    if (
      metadata.outputMode !== "static-proof" ||
      metadata.assets.closeup == null
    ) {
      throw new Error("Proof metadata is missing the closeup contract.");
    }
    runEntry.status = "succeeded";
    runEntry.finishedAt = new Date().toISOString();
    runEntry.resumed = completeBeforeRun && !force;
    runEntry.assets = {
      medium: path.relative(root, paths.medium),
      closeup: path.relative(root, paths.closeup),
      scene: path.relative(root, paths.scene),
      metadata: path.relative(root, paths.metadata),
    };
    runEntry.metrics = {
      sourceFaces: metadata.sourceFaces,
      renderFaces: metadata.renderFaces,
      cageFaces: metadata.cageFaces,
      cageIslandsBeforeCleanup: metadata.cageIslandsBeforeCleanup,
      cageIslandsRetained: metadata.cageIslandsRetained,
    };
    console.log(
      `[${run.succeeded + run.failed + 1}/${entries.length}] ${entry.objectId}: static proofs ready${runEntry.resumed ? " (resumed)" : ""}`,
    );
  } catch (error) {
    runEntry.status = "failed";
    runEntry.finishedAt = new Date().toISOString();
    runEntry.error = error instanceof Error ? error.message : String(error);
    console.error(`${entry.objectId}: ${runEntry.error}`);
  }
  await persist();
}

let cursor = 0;
async function worker() {
  while (cursor < entries.length) {
    const index = cursor;
    cursor += 1;
    await buildOne(entries[index]);
  }
}

await persist();
await Promise.all(Array.from({ length: concurrency }, () => worker()));
run.finishedAt = new Date().toISOString();
await persist();

console.log(
  JSON.stringify(
    {
      total: run.total,
      succeeded: run.succeeded,
      failed: run.failed,
      manifest: path.relative(root, runPath),
    },
    null,
    2,
  ),
);
