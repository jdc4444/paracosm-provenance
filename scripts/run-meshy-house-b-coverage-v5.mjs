import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";


const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const apiBase = "https://api.meshy.ai/openapi/v1";
const endpoint = "multi-image-to-3d";
const objectId = "house-b";
const versionId = "meshy-coverage-rerun-v5";
const outputStem = "house-b-meshy-coverage-rerun-v5";
const runId = "house-b-meshy-coverage-rerun-v5-20260728";
const expectedCredits = 35;
const pollIntervalMs = 15_000;
const manifestPath = path.join(
  repositoryRoot,
  "data/meshy-house-b-coverage-rerun-v5-20260728.json",
);
const modelDirectory = path.join(
  repositoryRoot,
  "public/archive/objects/3d",
);
const inputDirectory =
  "public/archive/objects/house-b-meshy-coverage-v5-inputs";
const inputs = [
  {
    view: "front",
    path: `${inputDirectory}/01-front.png`,
    purpose: "Preserve the Cut 1 facade and main-window axis",
  },
  {
    view: "elevated-front-right",
    path: `${inputDirectory}/02-elevated-front-right.png`,
    purpose: "Expose the formerly missing connector walls under the roofs",
  },
  {
    view: "elevated-right",
    path: `${inputDirectory}/03-elevated-right.png`,
    purpose: "Lock side depth, roof overlap, and enclosed wall junctions",
  },
  {
    view: "rear-right",
    path: `${inputDirectory}/04-rear-right.png`,
    purpose: "Constrain rear massing and close the final hidden surfaces",
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
  multi_view_thumbnails: true,
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
      if (!retryable || attempt === attempts) throw new Error(message);
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

const listRecentTasks = async () => {
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
  const tasks = await listRecentTasks();
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
  return {
    bytes: buffer.length,
    meshes: document.meshes?.length || 0,
    materials: document.materials?.length || 0,
    images: document.images?.length || 0,
    faces,
    vertices,
  };
};

let manifest;
try {
  manifest = await readJson(manifestPath);
} catch {
  manifest = {
    schemaVersion: 1,
    runId,
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
    comparisonBase: {
      versionId: "meshy-original-v1-max",
      model: "public/archive/objects/3d/house-b-original-v1-max.glb",
    },
  };
  await writeJson(manifestPath, manifest);
}

const saveManifest = async () => {
  manifest.updatedAt = new Date().toISOString();
  await writeJson(manifestPath, manifest);
};

if (!manifest.taskId) {
  const versions = await readJson(
    path.join(repositoryRoot, "data/object-3d-versions.json"),
  );
  const alreadyRegistered = versions.objects
    .find((item) => item.objectId === objectId)
    ?.versions?.some((item) => item.id === versionId);
  if (alreadyRegistered) {
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

  const recentTasks = await listRecentTasks();
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
      manifest.thumbnailUrls = task.thumbnail_urls || null;
      manifest.stats = await parseGlbStats(modelPath);
      manifest.finalBalance = (
        await requestJson(`${apiBase}/balance`)
      ).balance;
      manifest.completedAt = new Date().toISOString();
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

console.log(JSON.stringify(manifest, null, 2));
