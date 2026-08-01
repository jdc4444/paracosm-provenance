import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const apiBase = "https://api.meshy.ai/openapi/v1";
const endpoint = "multi-image-to-3d";
const objectId = "house-b";
const versionId = "meshy-original-v1-max";
const outputStem = "house-b-original-v1-max";
const expectedCredits = 35;
const pollIntervalMs = 15_000;
const versionsPath = path.join(
  repositoryRoot,
  "data/object-3d-versions.json",
);
const manifestPath = path.join(
  repositoryRoot,
  "data/meshy-house-b-original-v1-max-20260728.json",
);
const modelDirectory = path.join(
  repositoryRoot,
  "public/archive/objects/3d",
);
const inputs = [
  {
    view: "front",
    inference: false,
    path: "public/archive/objects/house-b-architectural-angles/01-cut1-front-elevation.png",
  },
  {
    view: "right",
    inference: false,
    path: "public/archive/objects/house-b-architectural-angles/02-right-entrance-elevation.png",
  },
  {
    view: "back",
    inference: true,
    path: "public/archive/objects/house-b-architectural-angles/04-rear-elevation-inferred.png",
  },
  {
    view: "left",
    inference: false,
    path: "public/archive/objects/house-b-architectural-angles/03-left-elevation.png",
  },
];
const settings = {
  ai_model: "meshy-6",
  should_texture: true,
  enable_pbr: true,
  texture_resolution: "8k",
  should_remesh: false,
  remove_lighting: true,
  target_formats: ["glb"],
  alpha_thumbnail: true,
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
      let body = null;
      if (raw) {
        try {
          body = JSON.parse(raw);
        } catch {
          body = { message: raw };
        }
      }
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

const fileDataUri = async (relativePath) =>
  `data:image/png;base64,${(
    await fs.readFile(path.join(repositoryRoot, relativePath))
  ).toString("base64")}`;

const listRecentTaskIds = async () => {
  const tasks = await requestJson(
    `${apiBase}/${endpoint}?page_size=10&sort_by=-created_at`,
  );
  return Array.isArray(tasks) ? tasks : [];
};

const reconcileAmbiguousSubmission = async (
  knownTaskIds,
  createStartedAt,
) => {
  const cutoff = Date.parse(createStartedAt) - 5_000;
  const tasks = await listRecentTaskIds();
  const candidates = tasks.filter(
    (task) =>
      !knownTaskIds.has(task.id) &&
      Number(task.created_at || 0) >= cutoff,
  );
  return candidates.length === 1 ? candidates[0].id : null;
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

const registerVersion = async (manifest) => {
  const registry = await readJson(versionsPath);
  let record = registry.objects.find((item) => item.objectId === objectId);
  if (!record) {
    record = { objectId, primaryVersionId: versionId, versions: [] };
    registry.objects.push(record);
  }
  const version = {
    id: versionId,
    label: "Meshy Original palette v1 · Max",
    provider: "Meshy 6 Multi-Image",
    model: `/archive/objects/3d/${outputStem}.glb`,
    thumbnail: `/archive/objects/3d/${outputStem}.png`,
    createdAt: new Date().toISOString().slice(0, 10),
    taskId: manifest.taskId,
    faces: manifest.stats.faces,
    vertices: manifest.stats.vertices,
    status: "review",
    note:
      "Maximum-detail Meshy 6 multi-image pass from the Original palette v1 front, right, inferred rear, and left architectural views. Full-precision triangular geometry, 8K textures, PBR maps, and no remesh.",
  };
  const versionIndex = record.versions.findIndex(
    (item) => item.id === versionId,
  );
  if (versionIndex >= 0) record.versions[versionIndex] = version;
  else record.versions.push(version);
  record.primaryVersionId = versionId;
  registry.objects.sort((left, right) =>
    left.objectId.localeCompare(right.objectId),
  );
  registry.updatedAt = new Date().toISOString().slice(0, 10);
  await writeJson(versionsPath, registry);
};

let manifest;
try {
  manifest = await readJson(manifestPath);
} catch {
  manifest = {
    schemaVersion: 1,
    runId: "house-b-original-v1-max-20260728",
    objectId,
    endpoint,
    versionId,
    expectedCredits,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    taskId: null,
    status: "queued",
    progress: 0,
    consumedCredits: null,
    error: null,
    inputs,
    settings,
  };
  await writeJson(manifestPath, manifest);
}

const saveManifest = async () => {
  manifest.updatedAt = new Date().toISOString();
  await writeJson(manifestPath, manifest);
};

if (!manifest.taskId) {
  const registry = await readJson(versionsPath);
  const registeredVersion = registry.objects
    .find((item) => item.objectId === objectId)
    ?.versions?.find((item) => item.id === versionId);
  if (registeredVersion) {
    throw new Error(
      `${versionId} is already registered; refusing a duplicate paid submission.`,
    );
  }

  const balance = await requestJson(`${apiBase}/balance`);
  manifest.initialBalance = balance.balance;
  await saveManifest();
  if (balance.balance < expectedCredits) {
    throw new Error(
      `Insufficient Meshy balance: ${balance.balance} available, ${expectedCredits} required.`,
    );
  }

  const recentTasks = await listRecentTaskIds();
  const knownTaskIds = new Set(recentTasks.map((task) => task.id));
  manifest.knownTaskIdsBeforeSubmit = [...knownTaskIds];
  manifest.createStartedAt = new Date().toISOString();
  await saveManifest();
  try {
    const created = await requestJson(`${apiBase}/${endpoint}`, {
      method: "POST",
      body: JSON.stringify({
        image_urls: await Promise.all(
          inputs.map((input) => fileDataUri(input.path)),
        ),
        ...settings,
      }),
    });
    manifest.taskId = created.result;
    manifest.status = "submitted";
    manifest.submittedAt = new Date().toISOString();
    await saveManifest();
    console.log(`[submit] ${objectId} ${manifest.taskId}`);
  } catch (error) {
    const reconciledTaskId = await reconcileAmbiguousSubmission(
      knownTaskIds,
      manifest.createStartedAt,
    );
    if (!reconciledTaskId) {
      manifest.status = "ambiguous-submit";
      manifest.error = error.message;
      manifest.createFailedAt = new Date().toISOString();
      await saveManifest();
      throw new Error(
        `Submission was ambiguous. No unique recent ${endpoint} task could be reconciled; inspect the manifest before retrying.`,
      );
    }
    manifest.taskId = reconciledTaskId;
    manifest.status = "submitted-reconciled";
    manifest.reconciledAfterError = error.message;
    manifest.submittedAt = new Date().toISOString();
    await saveManifest();
    console.log(`[reconciled] ${objectId} ${manifest.taskId}`);
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
      await fs.mkdir(modelDirectory, { recursive: true });
      const modelPath = path.join(modelDirectory, `${outputStem}.glb`);
      const thumbnailPath = path.join(
        modelDirectory,
        `${outputStem}.png`,
      );
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

await registerVersion(manifest);
const finalBalance = await requestJson(`${apiBase}/balance`);
manifest.finalBalance = finalBalance.balance;
manifest.completedAt = new Date().toISOString();
await saveManifest();
console.log(
  `[meshy] complete; balance ${finalBalance.balance}; spent ${
    manifest.initialBalance - finalBalance.balance
  }.`,
);
