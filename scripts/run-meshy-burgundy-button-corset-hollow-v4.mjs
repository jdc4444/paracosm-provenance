import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const apiBase = "https://api.meshy.ai/openapi/v1";
const endpoint = "multi-image-to-3d";
const objectId = "burgundy-button-corset";
const outputStem = "burgundy-button-corset-v4";
const versionId = "meshy-hollow-multiview-v4";
const expectedCredits = 30;
const manifestPath = path.join(
  repositoryRoot,
  "data/meshy-burgundy-button-corset-hollow-v4-20260728.json",
);
const versionsPath = path.join(repositoryRoot, "data/object-3d-versions.json");
const notesPath = path.join(
  repositoryRoot,
  "data/object-production-notes.json",
);
const hollowViewsPath = path.join(
  repositoryRoot,
  "data/wardrobe-hollow-multiview-20260728.json",
);
const inventoryPath = path.join(repositoryRoot, "data/object-inventory.json");
const modelDirectory = path.join(
  repositoryRoot,
  "public/archive/objects/3d",
);
const pollIntervalMs = 15_000;
const inputPaths = [
  "public/archive/objects/wardrobe/burgundy-button-corset.png",
  "public/archive/objects/wardrobe/3d-inputs/burgundy-button-corset-top-v4.png",
  "public/archive/objects/wardrobe/3d-inputs/burgundy-button-corset-side-v4.png",
  "public/archive/objects/wardrobe/3d-inputs/burgundy-button-corset-bottom-v4.png",
];

function getApiKey() {
  if (process.env.MESHY_API_KEY) return process.env.MESHY_API_KEY;
  return execFileSync(
    "security",
    ["find-generic-password", "-s", "MESHY_API_KEY", "-w"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
  ).trim();
}

const headers = {
  Authorization: `Bearer ${getApiKey()}`,
  "Content-Type": "application/json",
};
const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));
const readJson = async (filePath) =>
  JSON.parse(await fs.readFile(filePath, "utf8"));

async function writeJsonAtomically(filePath, value) {
  const temporaryPath = `${filePath}.${process.pid}.${randomUUID()}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await fs.rename(temporaryPath, filePath);
}

async function requestJson(url, options = {}, attempts = 6) {
  const isGet = !options.method || options.method === "GET";
  let delayMs = 2_000;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      const response = await fetch(url, {
        ...options,
        headers: { ...headers, ...(options.headers || {}) },
      });
      const raw = await response.text();
      const body = raw ? JSON.parse(raw) : null;
      if (response.ok) return body;
      const message =
        body?.message ||
        body?.task_error?.message ||
        `${response.status} ${response.statusText}`;
      const retryable =
        isGet &&
        (response.status === 408 ||
          response.status === 429 ||
          response.status >= 500);
      if (!retryable || attempt === attempts) throw new Error(message);
    } catch (error) {
      if (!isGet || attempt === attempts) throw error;
    }
    await sleep(delayMs);
    delayMs = Math.min(delayMs * 2, 30_000);
  }
  throw new Error("Meshy request failed without a response.");
}

async function fileDataUri(relativePath) {
  return `data:image/png;base64,${(
    await fs.readFile(path.join(repositoryRoot, relativePath))
  ).toString("base64")}`;
}

async function parseGlbStats(filePath) {
  const buffer = await fs.readFile(filePath);
  if (buffer.toString("utf8", 0, 4) !== "glTF") {
    throw new Error(`${path.basename(filePath)} is not a GLB.`);
  }
  const jsonChunkLength = buffer.readUInt32LE(12);
  const document = JSON.parse(
    buffer
      .subarray(20, 20 + jsonChunkLength)
      .toString("utf8")
      .replace(/\u0000+$/g, ""),
  );
  let faces = 0;
  let vertices = 0;
  for (const mesh of document.meshes || []) {
    for (const primitive of mesh.primitives || []) {
      const positionAccessor =
        document.accessors?.[primitive.attributes?.POSITION];
      vertices += positionAccessor?.count || 0;
      if (primitive.indices !== undefined) {
        faces += Math.floor(
          (document.accessors?.[primitive.indices]?.count || 0) / 3,
        );
      } else {
        faces += Math.floor((positionAccessor?.count || 0) / 3);
      }
    }
  }
  return { faces, vertices };
}

async function download(url, destination) {
  const temporaryPath = `${destination}.${process.pid}.${randomUUID()}.tmp`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(
      `Download failed for ${path.basename(destination)}: ${response.status}`,
    );
  }
  await fs.writeFile(
    temporaryPath,
    Buffer.from(await response.arrayBuffer()),
  );
  await fs.rename(temporaryPath, destination);
}

for (const inputPath of inputPaths) {
  await fs.access(path.join(repositoryRoot, inputPath));
}

let manifest;
try {
  manifest = await readJson(manifestPath);
} catch {
  const modelPath = path.join(modelDirectory, `${outputStem}.glb`);
  const thumbnailPath = path.join(modelDirectory, `${outputStem}.png`);
  const unexpectedAssets = await Promise.all(
    [modelPath, thumbnailPath].map(async (filePath) => {
      try {
        await fs.access(filePath);
        return filePath;
      } catch {
        return null;
      }
    }),
  );
  if (unexpectedAssets.some(Boolean)) {
    throw new Error(
      "Found v4 assets without a task manifest; reconcile them before submitting.",
    );
  }
  manifest = {
    schemaVersion: 1,
    runId: "burgundy-button-corset-hollow-multiview-v4-20260728",
    objectId,
    endpoint,
    expectedCredits,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    taskId: null,
    status: "queued",
    progress: 0,
    consumedCredits: null,
    error: null,
    inputs: inputPaths,
  };
  await writeJsonAtomically(manifestPath, manifest);
}

async function saveManifest() {
  manifest.updatedAt = new Date().toISOString();
  await writeJsonAtomically(manifestPath, manifest);
}

if (!manifest.taskId) {
  const balance = await requestJson(`${apiBase}/balance`);
  manifest.initialBalance = balance.balance;
  await saveManifest();
  if (balance.balance < expectedCredits) {
    throw new Error(
      `Insufficient Meshy balance: ${balance.balance} available, ${expectedCredits} required.`,
    );
  }

  const front = await fileDataUri(inputPaths[0]);
  manifest.createStartedAt = new Date().toISOString();
  await saveManifest();
  try {
    const created = await requestJson(`${apiBase}/${endpoint}`, {
      method: "POST",
      body: JSON.stringify({
        image_urls: [
          front,
          await fileDataUri(inputPaths[1]),
          await fileDataUri(inputPaths[2]),
          await fileDataUri(inputPaths[3]),
        ],
        ai_model: "meshy-6",
        should_texture: true,
        enable_pbr: false,
        texture_resolution: "2k",
        texture_image_url: front,
        should_remesh: false,
        remove_lighting: true,
        target_formats: ["glb"],
      }),
    });
    manifest.taskId = created.result;
    manifest.status = "submitted";
    manifest.submittedAt = new Date().toISOString();
    await saveManifest();
    console.log(`[submit] ${objectId} ${manifest.taskId}`);
  } catch (error) {
    manifest.status = "ambiguous-submit";
    manifest.error = error.message;
    manifest.createFailedAt = new Date().toISOString();
    await saveManifest();
    throw new Error(
      `Submission was ambiguous. Inspect Meshy's recent ${endpoint} tasks before retrying.`,
    );
  }
}

if (!(manifest.status === "succeeded" && manifest.downloadedAt)) {
  while (true) {
    const task = await requestJson(
      `${apiBase}/${endpoint}/${manifest.taskId}`,
    );
    manifest.status = task.status?.toLowerCase() || "unknown";
    manifest.progress = task.progress || 0;
    manifest.consumedCredits = task.consumed_credits ?? null;
    manifest.precedingTasks = task.preceding_tasks ?? null;
    await saveManifest();

    if (task.status === "SUCCEEDED") {
      const glbUrl = task.model_urls?.glb;
      const thumbnailUrl =
        task.alpha_thumbnail_url ||
        task.thumbnail_url ||
        task.thumbnail_urls?.front;
      if (!glbUrl || !thumbnailUrl) {
        throw new Error("Meshy succeeded without downloadable assets.");
      }
      const modelPath = path.join(modelDirectory, `${outputStem}.glb`);
      const thumbnailPath = path.join(modelDirectory, `${outputStem}.png`);
      await Promise.all([
        download(glbUrl, modelPath),
        download(thumbnailUrl, thumbnailPath),
      ]);
      manifest.status = "succeeded";
      manifest.downloadedAt = new Date().toISOString();
      manifest.assets = {
        model: path.relative(repositoryRoot, modelPath),
        thumbnail: path.relative(repositoryRoot, thumbnailPath),
      };
      manifest.stats = await parseGlbStats(modelPath);
      await saveManifest();
      console.log(
        `[complete] ${objectId} ${manifest.stats.faces} faces ${manifest.stats.vertices} vertices`,
      );
      break;
    }
    if (task.status === "FAILED" || task.status === "CANCELED") {
      manifest.error =
        task.task_error?.message || `Meshy task ${task.status}.`;
      await saveManifest();
      throw new Error(`${objectId}: ${manifest.error}`);
    }
    console.log(
      `[poll] ${objectId} ${manifest.status} ${manifest.progress}%`,
    );
    await sleep(pollIntervalMs);
  }
}

const versions = await readJson(versionsPath);
const versionRecord = versions.objects.find(
  (item) => item.objectId === objectId,
);
if (!versionRecord) throw new Error(`Missing 3D registry record for ${objectId}.`);
const nextVersion = {
  id: versionId,
  label: "Meshy hollow multiview v4",
  provider: "Meshy 6 Multi-Image",
  model: `/archive/objects/3d/${outputStem}.glb`,
  thumbnail: `/archive/objects/3d/${outputStem}.png`,
  createdAt: new Date().toISOString().slice(0, 10),
  taskId: manifest.taskId,
  faces: manifest.stats.faces,
  vertices: manifest.stats.vertices,
  status: "review",
  note:
    "Four-image rerun using the source front plus new top, side, and underside views that explicitly expose the empty body cavity and open lower hem.",
};
const versionIndex = versionRecord.versions.findIndex(
  (item) => item.id === nextVersion.id,
);
if (versionIndex >= 0) versionRecord.versions[versionIndex] = nextVersion;
else versionRecord.versions.push(nextVersion);
versions.updatedAt = new Date().toISOString();
await writeJsonAtomically(versionsPath, versions);

const notes = await readJson(notesPath);
let noteRecord = notes.objects.find((item) => item.objectId === objectId);
if (!noteRecord) {
  noteRecord = { objectId, notes: [] };
  notes.objects.push(noteRecord);
}
const noteUpdate = {
  id: "open-corset-shell",
  title: "Full hollow multiview repair ready",
  detail:
    "Meshy reran the corset from four views that explicitly expose the empty upper cavity, thin side shell, and open lower hem. Review the negative space before approval.",
  kind: "generation-caution",
  status: "review",
  relatedObjectIds: ["ivory-striped-corset", "pink-striped-corset"],
  proposedParts: [
    "Thin outer shell",
    "Empty wearable cavity",
    "Open top rim",
    "Open lower hem",
    "Separate shoulder ties",
  ],
};
const noteIndex = noteRecord.notes.findIndex(
  (item) => item.id === noteUpdate.id,
);
if (noteIndex >= 0) noteRecord.notes[noteIndex] = noteUpdate;
else noteRecord.notes.push(noteUpdate);
notes.updatedAt = new Date().toISOString();
await writeJsonAtomically(notesPath, notes);

const hollowViews = await readJson(hollowViewsPath);
const hollowRecord = {
  objectId,
  name: "Burgundy Button Corset",
  inventoryGroupId: "wardrobe-historical",
  referenceImage: "/archive/objects/wardrobe/burgundy-button-corset.png",
  assets: {
    top: "/archive/objects/wardrobe/3d-inputs/burgundy-button-corset-top-v4.png",
    side: "/archive/objects/wardrobe/3d-inputs/burgundy-button-corset-side-v4.png",
    bottom:
      "/archive/objects/wardrobe/3d-inputs/burgundy-button-corset-bottom-v4.png",
  },
  meshyInputOrder: inputPaths.map(
    (inputPath) => `/${path.relative("public", inputPath)}`,
  ),
};
const hollowIndex = hollowViews.objects.findIndex(
  (item) => item.objectId === objectId,
);
if (hollowIndex >= 0) hollowViews.objects[hollowIndex] = hollowRecord;
else hollowViews.objects.push(hollowRecord);
hollowViews.objects.sort((left, right) =>
  left.objectId.localeCompare(right.objectId),
);
hollowViews.scope.generatedInputSets = hollowViews.objects.length;
hollowViews.updatedAt = new Date().toISOString();
await writeJsonAtomically(hollowViewsPath, hollowViews);

const inventory = await readJson(inventoryPath);
inventory.updatedAt = new Date().toISOString();
await writeJsonAtomically(inventoryPath, inventory);

const finalBalance = await requestJson(`${apiBase}/balance`);
manifest.finalBalance = finalBalance.balance;
manifest.completedAt = new Date().toISOString();
await saveManifest();
console.log(
  `[meshy] complete; balance ${finalBalance.balance}; spent ${
    manifest.initialBalance - finalBalance.balance
  }.`,
);
