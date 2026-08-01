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
const registryPath = path.join(root, "data/object-3d-versions.json");
const runPath = path.join(
  root,
  "data/wardrobe-cloth-simulation-run-20260728.json",
);
const logDirectory = path.join(
  root,
  "data/wardrobe-cloth-simulation-logs-20260728",
);
const simulationId = "material-aware-sphere-v1";
let atomicWriteCounter = 0;
const concurrencyFlag = process.argv.indexOf("--concurrency");
const concurrency = Math.max(
  1,
  Math.min(
    4,
    concurrencyFlag >= 0
      ? Number.parseInt(process.argv[concurrencyFlag + 1], 10) || 3
      : 3,
  ),
);

const materialLabels = {
  "rigid-adornment": "rigid adornment",
  "rigid-corsetry": "boned corsetry",
  "structured-ruffle": "structured ruffle",
  "sheer-lightweight": "lightweight sheer",
  "stretch-jersey": "stretch jersey",
  "knit-fuzzy": "soft knit",
  "satin-fluid": "fluid satin",
  "tulle-ruffle": "airy tulle",
  "crisp-woven": "crisp woven",
  "tailored-heavy": "tailored heavy cloth",
  "felt-structured": "structured felt",
};

const structureNotes = {
  "structured-collar": "Collar and neckline stiffness is retained.",
  "structured-upper": "The upper construction stays supported while the lower garment relaxes.",
  "uniform-structured": "Structure is retained consistently across the object.",
  "structured-bodice": "The bodice stays supported while ruffles and skirt layers relax.",
  "structured-cuff": "Cuffs retain more stiffness than the glove bodies.",
  "structured-waistband": "The waistband stays supported while the hanging fabric relaxes.",
  "structured-accessory": "The core accessory shape is retained while softer parts settle.",
};

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

function runCommand(command, args, logPath) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const output = [];
    child.stdout.on("data", (chunk) => output.push(chunk));
    child.stderr.on("data", (chunk) => output.push(chunk));
    child.on("error", reject);
    child.on("close", async (code) => {
      const log = Buffer.concat(output).toString("utf8");
      await writeFile(logPath, log);
      if (code === 0) {
        resolve(log);
      } else {
        reject(
          new Error(
            `${path.basename(command)} exited ${code}; see ${path.relative(root, logPath)}`,
          ),
        );
      }
    });
  });
}

function publicPath(absolutePath) {
  return `/${path.relative(path.join(root, "public"), absolutePath)}`;
}

function simulationPaths(objectId) {
  const directory = path.join(
    root,
    "public/archive/objects/3d/simulations",
    objectId,
  );
  const stem = `${objectId}-cloth-sphere-v1`;
  return {
    directory,
    metadata: path.join(directory, `${stem}-metadata.json`),
    forwardVideo: path.join(directory, `${stem}.mp4`),
    loopVideo: path.join(directory, `${stem}-loop.mp4`),
    poster: path.join(directory, `${stem}-final.png`),
    settledModel: path.join(directory, `${stem}-settled.glb`),
    scene: path.join(directory, `${stem}.blend`),
  };
}

function upsertSimulation(registry, entry, paths) {
  const record = registry.objects.find(
    (candidate) => candidate.objectId === entry.objectId,
  );
  if (!record) {
    throw new Error(`Missing 3D registry record for ${entry.objectId}`);
  }
  const materialLabel = materialLabels[entry.materialClass];
  const simulation = {
    id: simulationId,
    label: "Material-aware sphere drape",
    solver: `Blender cloth · ${materialLabel}`,
    video: publicPath(paths.loopVideo),
    poster: publicPath(paths.poster),
    settledModel: publicPath(paths.settledModel),
    scene: publicPath(paths.scene),
    createdAt: "2026-07-28",
    collisionObject: "Invisible sphere",
    settledFrame: 48,
    note: `A ${materialLabel} solve tuned for this garment's weight, stretch, bending, damping, and friction. ${structureNotes[entry.structureMode]}`,
  };
  record.simulations ??= [];
  const existingIndex = record.simulations.findIndex(
    (candidate) => candidate.id === simulationId,
  );
  if (existingIndex >= 0) {
    record.simulations[existingIndex] = simulation;
  } else {
    record.simulations.push(simulation);
  }
}

const plan = JSON.parse(await readFile(planPath, "utf8"));
const registry = JSON.parse(await readFile(registryPath, "utf8"));
const entries = plan.objects.filter((entry) => !entry.existingSimulation);
await mkdir(logDirectory, { recursive: true });

const run = {
  schemaVersion: 1,
  startedAt: new Date().toISOString(),
  updatedAt: new Date().toISOString(),
  concurrency,
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
    run.succeeded = run.objects.filter(
      (entry) => entry.status === "succeeded",
    ).length;
    run.failed = run.objects.filter(
      (entry) => entry.status === "failed",
    ).length;
    run.running = run.objects.filter(
      (entry) => entry.status === "running",
    ).length;
    run.pending = run.objects.filter(
      (entry) => entry.status === "pending",
    ).length;
    registry.updatedAt = "2026-07-28";
    await Promise.all([
      writeJsonAtomic(runPath, run),
      writeJsonAtomic(registryPath, registry),
    ]);
  });
  return persistChain;
}

async function buildOne(entry) {
  const runEntry = run.objects.find(
    (candidate) => candidate.objectId === entry.objectId,
  );
  const paths = simulationPaths(entry.objectId);
  runEntry.status = "running";
  runEntry.startedAt = new Date().toISOString();
  await persist();
  try {
    await mkdir(paths.directory, { recursive: true });
    const required = [
      paths.metadata,
      paths.forwardVideo,
      paths.poster,
      paths.settledModel,
      paths.scene,
    ];
    const hasSolve = (
      await Promise.all(required.map((filePath) => exists(filePath)))
    ).every(Boolean);
    if (!hasSolve) {
      await runCommand(
        blender,
        [
          "--background",
          "--factory-startup",
          "--python",
          builder,
          "--",
          "--object-id",
          entry.objectId,
        ],
        path.join(logDirectory, `${entry.objectId}.blender.log`),
      );
    }
    if (!(await exists(paths.loopVideo))) {
      await runCommand(
        "ffmpeg",
        [
          "-y",
          "-i",
          paths.forwardVideo,
          "-filter_complex",
          "[0:v]split[forward][reverse];[reverse]reverse[backward];[forward][backward]concat=n=2:v=1:a=0,format=yuv420p[video]",
          "-map",
          "[video]",
          "-movflags",
          "+faststart",
          paths.loopVideo,
        ],
        path.join(logDirectory, `${entry.objectId}.ffmpeg.log`),
      );
    }
    const finalAssets = [
      paths.loopVideo,
      paths.poster,
      paths.settledModel,
      paths.scene,
    ];
    if (
      !(
        await Promise.all(finalAssets.map((filePath) => exists(filePath)))
      ).every(Boolean)
    ) {
      throw new Error("One or more final simulation assets are missing.");
    }
    upsertSimulation(registry, entry, paths);
    runEntry.status = "succeeded";
    runEntry.finishedAt = new Date().toISOString();
    runEntry.resumed = hasSolve;
    console.log(
      `[${run.succeeded + run.failed + 1}/${entries.length}] ${entry.objectId}: succeeded${hasSolve ? " (resumed)" : ""}`,
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
process.exitCode = run.failed > 0 ? 1 : 0;
