import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const apiBase = "https://api.meshy.ai/openapi/v1";
const endpoint = "multi-image-to-3d";
const objectId = "navy-corset-vest";
const outputStem = "navy-corset-vest-v3";
const expectedCredits = 30;
const manifestPath = path.join(
  repositoryRoot,
  "data/meshy-navy-corset-vest-multiview-v3-20260728.json",
);
const versionsPath = path.join(repositoryRoot, "data/object-3d-versions.json");
const notesPath = path.join(
  repositoryRoot,
  "data/object-production-notes.json",
);
const inventoryPath = path.join(repositoryRoot, "data/object-inventory.json");
const modelDirectory = path.join(
  repositoryRoot,
  "public/archive/objects/3d",
);
const pollIntervalMs = 15_000;

const getApiKey = () => {
  if (process.env.MESHY_API_KEY) return process.env.MESHY_API_KEY;
  return execFileSync(
    "security",
    ["find-generic-password", "-s", "MESHY_API_KEY", "-w"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
  ).trim();
};

const headers = {
  Authorization: `Bearer ${getApiKey()}`,
  "Content-Type": "application/json",
};
const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));
const readJson = async (filePath) =>
  JSON.parse(await fs.readFile(filePath, "utf8"));

let writeCounter = 0;
const writeJson = async (filePath, value) => {
  writeCounter += 1;
  const temporaryPath = `${filePath}.${process.pid}.${writeCounter}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await fs.rename(temporaryPath, filePath);
};

const requestJson = async (url, options = {}, attempts = 6) => {
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
      if (!retryable || attempt === attempts) {
        throw new Error(message);
      }
    } catch (error) {
      if (!isGet || attempt === attempts) throw error;
    }
    await sleep(delayMs);
    delayMs = Math.min(delayMs * 2, 30_000);
  }
  throw new Error("Meshy request failed without a response.");
};

const fileDataUri = async (relativePath) => {
  const filePath = path.join(repositoryRoot, relativePath);
  return `data:image/png;base64,${(
    await fs.readFile(filePath)
  ).toString("base64")}`;
};

const parseGlbStats = async (filePath) => {
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
};

const download = async (url, destination) => {
  const temporaryPath = `${destination}.${process.pid}.tmp`;
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
};

let manifest;
try {
  manifest = await readJson(manifestPath);
} catch {
  manifest = {
    schemaVersion: 1,
    runId: "navy-corset-vest-hollow-multiview-v3-20260728",
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
    inputs: [
      "public/archive/objects/wardrobe/navy-corset-vest.png",
      "public/archive/objects/wardrobe/3d-inputs/navy-corset-vest-top-v3.png",
      "public/archive/objects/wardrobe/3d-inputs/navy-corset-vest-side-v3.png",
      "public/archive/objects/wardrobe/3d-inputs/navy-corset-vest-bottom-v3.png",
    ],
  };
  await writeJson(manifestPath, manifest);
}

const saveManifest = async () => {
  manifest.updatedAt = new Date().toISOString();
  await writeJson(manifestPath, manifest);
};

if (!manifest.taskId) {
  const balance = await requestJson(`${apiBase}/balance`);
  manifest.initialBalance = balance.balance;
  await saveManifest();
  if (balance.balance < expectedCredits) {
    throw new Error(
      `Insufficient Meshy balance: ${balance.balance} available, ${expectedCredits} required.`,
    );
  }

  const front = await fileDataUri(manifest.inputs[0]);
  manifest.createStartedAt = new Date().toISOString();
  await saveManifest();
  try {
    const created = await requestJson(`${apiBase}/${endpoint}`, {
      method: "POST",
      body: JSON.stringify({
        image_urls: [
          front,
          await fileDataUri(manifest.inputs[1]),
          await fileDataUri(manifest.inputs[2]),
          await fileDataUri(manifest.inputs[3]),
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
if (!versionRecord) {
  throw new Error(`Missing 3D registry record for ${objectId}.`);
}
const nextVersion = {
  id: "meshy-hollow-multiview-v3",
  label: "Meshy hollow multiview v3",
  provider: "Meshy 6 Multi-Image",
  model: `/archive/objects/3d/${outputStem}.glb`,
  thumbnail: `/archive/objects/3d/${outputStem}.png`,
  createdAt: new Date().toISOString().slice(0, 10),
  taskId: manifest.taskId,
  faces: manifest.stats.faces,
  vertices: manifest.stats.vertices,
  status: "review",
  note:
    "Four-image rerun using the source front plus generated top, side, and underside views that explicitly expose the collar, armholes, torso cavity, and open hem.",
};
const versionIndex = versionRecord.versions.findIndex(
  (item) => item.id === nextVersion.id,
);
if (versionIndex >= 0) versionRecord.versions[versionIndex] = nextVersion;
else versionRecord.versions.push(nextVersion);
versions.updatedAt = new Date().toISOString().slice(0, 10);
await writeJson(versionsPath, versions);

const notes = await readJson(notesPath);
let noteRecord = notes.objects.find((item) => item.objectId === objectId);
if (!noteRecord) {
  noteRecord = { objectId, notes: [] };
  notes.objects.push(noteRecord);
}
const noteUpdate = {
  id: "open-corset-shell",
  title: "New hollow multiview repair ready",
  detail:
    "Meshy reran the vest from four views that explicitly expose the collar, both armholes, the torso interior, and the open lower hem. Review the negative space before approval.",
  kind: "generation-caution",
  status: "review",
  relatedObjectIds: [],
  proposedParts: [
    "Thin outer shell",
    "Open torso cavity",
    "Open collar passage",
    "Separate armholes",
    "Open lower hem",
  ],
};
const noteIndex = noteRecord.notes.findIndex(
  (item) => item.id === noteUpdate.id,
);
if (noteIndex >= 0) noteRecord.notes[noteIndex] = noteUpdate;
else noteRecord.notes.push(noteUpdate);
notes.updatedAt = new Date().toISOString().slice(0, 10);
await writeJson(notesPath, notes);

const inventory = await readJson(inventoryPath);
const inventoryObject = inventory.generatedGroups
  .filter((group) => group.category === "Wardrobe")
  .flatMap((group) => group.objects)
  .find((item) => item.id === objectId);
if (!inventoryObject) {
  throw new Error(`Missing inventory object ${objectId}.`);
}
const alternates = [
  {
    id: "hollow-top-3d-input-v3",
    label: "Hollow top view",
    image:
      "/archive/objects/wardrobe/3d-inputs/navy-corset-vest-top-v3.png",
    description:
      "Overhead Meshy input exposing the collar, torso cavity, armholes, and open hem.",
  },
  {
    id: "hollow-side-3d-input-v3",
    label: "Hollow side view",
    image:
      "/archive/objects/wardrobe/3d-inputs/navy-corset-vest-side-v3.png",
    description:
      "Orthographic side Meshy input establishing shell depth and open passages.",
  },
  {
    id: "hollow-bottom-3d-input-v3",
    label: "Hollow underside view",
    image:
      "/archive/objects/wardrobe/3d-inputs/navy-corset-vest-bottom-v3.png",
    description:
      "Underside Meshy input exposing the open hem, collar passage, and both armholes.",
  },
];
const alternateIds = new Set(alternates.map((item) => item.id));
inventoryObject.alternateImages = [
  ...(inventoryObject.alternateImages || []).filter(
    (item) => !alternateIds.has(item.id),
  ),
  ...alternates,
];
inventory.updatedAt = new Date().toISOString().slice(0, 10);
await writeJson(inventoryPath, inventory);

const finalBalance = await requestJson(`${apiBase}/balance`);
manifest.finalBalance = finalBalance.balance;
manifest.completedAt = new Date().toISOString();
await saveManifest();
console.log(
  `[meshy] complete; balance ${finalBalance.balance}; spent ${
    manifest.initialBalance - finalBalance.balance
  }.`,
);
