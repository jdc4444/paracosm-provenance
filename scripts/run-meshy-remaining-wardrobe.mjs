import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const inventoryPath = path.join(repositoryRoot, "data/object-inventory.json");
const hollowViewsPath = path.join(
  repositoryRoot,
  "data/wardrobe-hollow-multiview-20260728.json",
);
const versionsPath = path.join(repositoryRoot, "data/object-3d-versions.json");
const runPath = path.join(
  repositoryRoot,
  "data/meshy-remaining-wardrobe-run-20260728.json",
);
const modelDirectory = path.join(
  repositoryRoot,
  "public/archive/objects/3d",
);
const apiBase = "https://api.meshy.ai/openapi/v1";
const estimatedCreditsPerTask = 30;
const concurrency = Math.max(
  1,
  Math.min(
    10,
    Number.parseInt(process.env.MESHY_CONCURRENCY || "8", 10),
  ),
);
const pollIntervalMs = Math.max(
  5_000,
  Number.parseInt(process.env.MESHY_POLL_INTERVAL_MS || "15000", 10),
);

const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));
const readJson = async (filePath) =>
  JSON.parse(await fs.readFile(filePath, "utf8"));

let writeSequence = 0;
let writeQueue = Promise.resolve();
const writeJson = async (filePath, value) => {
  const body = `${JSON.stringify(value, null, 2)}\n`;
  writeSequence += 1;
  const temporaryPath = `${filePath}.${process.pid}.${writeSequence}.tmp`;
  const operation = writeQueue.then(async () => {
    await fs.writeFile(temporaryPath, body);
    await fs.rename(temporaryPath, filePath);
  });
  writeQueue = operation.catch(() => {});
  return operation;
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

const requestJson = async (url, options = {}, attempts = 8) => {
  const isGet = !options.method || options.method === "GET";
  let delayMs = 2_000;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    let response;
    try {
      response = await fetch(url, {
        ...options,
        headers: { ...headers, ...(options.headers || {}) },
      });
    } catch (error) {
      if (!isGet || attempt === attempts) throw error;
      await sleep(delayMs);
      delayMs = Math.min(delayMs * 2, 30_000);
      continue;
    }

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

    const error = new Error(
      body?.message ||
        body?.task_error?.message ||
        `${response.status} ${response.statusText}`,
    );
    error.status = response.status;
    error.body = body;
    const retryable =
      isGet &&
      (response.status === 408 ||
        response.status === 429 ||
        response.status >= 500);
    if (!retryable || attempt === attempts) throw error;
    await sleep(delayMs);
    delayMs = Math.min(delayMs * 2, 30_000);
  }
  throw new Error("Meshy request failed without a response.");
};

const absolutePublicPath = (assetPath) =>
  path.join(
    repositoryRoot,
    "public",
    assetPath.startsWith("/") ? assetPath.slice(1) : assetPath,
  );

const fileDataUri = async (assetPath) => {
  const filePath = absolutePublicPath(assetPath);
  const extension = path.extname(filePath).toLowerCase();
  const mimeType =
    extension === ".jpg" || extension === ".jpeg"
      ? "image/jpeg"
      : "image/png";
  return `data:${mimeType};base64,${(
    await fs.readFile(filePath)
  ).toString("base64")}`;
};

const download = async (url, destination) => {
  let response;
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    try {
      response = await fetch(url);
      if (response.ok) break;
      if (response.status < 500 || attempt === 6) {
        throw new Error(
          `Download failed for ${path.basename(destination)}: ${response.status}`,
        );
      }
    } catch (error) {
      if (attempt === 6) throw error;
    }
    await sleep(Math.min(2 ** attempt * 1_000, 15_000));
  }
  if (!response?.ok) {
    throw new Error(`Download failed for ${path.basename(destination)}.`);
  }
  const temporaryPath = `${destination}.${process.pid}.tmp`;
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
  const jsonChunkType = buffer.readUInt32LE(16);
  if (jsonChunkType !== 0x4e4f534a) {
    throw new Error(`${path.basename(filePath)} has no JSON GLB chunk.`);
  }
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

const inventory = await readJson(inventoryPath);
const hollowViews = await readJson(hollowViewsPath);
let versions = await readJson(versionsPath);
const versionedObjectIds = new Set(
  versions.objects.flatMap((item) =>
    item.versions?.length ? [item.objectId] : [],
  ),
);
const wardrobeObjects = inventory.generatedGroups.flatMap((group) =>
  group.category !== "Wardrobe"
    ? []
    : group.objects.map((item) => ({
        ...item,
        category: group.category,
        image: item.image || `${group.imageDirectory}/${item.id}.png`,
        sourceFiles: item.sourceFiles || group.sourceFiles || [],
      })),
);
const hollowByObjectId = new Map(
  hollowViews.objects.map((item) => [item.objectId, item]),
);
const missingObjects = wardrobeObjects.filter(
  (item) => !versionedObjectIds.has(item.id),
);

const plannedEntries = missingObjects.map((object) => {
  const hollow = hollowByObjectId.get(object.id);
  if (hollow) {
    return {
      objectId: object.id,
      name: object.name,
      category: object.category,
      endpoint: "multi-image-to-3d",
      inputs: [
        hollow.referenceImage,
        hollow.assets.top,
        hollow.assets.side,
        hollow.assets.bottom,
      ],
    };
  }
  return {
    objectId: object.id,
    name: object.name,
    category: object.category,
    endpoint: "image-to-3d",
    inputs: [object.image],
  };
});

if (
  plannedEntries.some(
    (entry) =>
      entry.endpoint === "image-to-3d" &&
      entry.objectId !== "lime-open-knit-scarf",
  )
) {
  throw new Error(
    "A remaining hollow Wardrobe object is missing its multiview inputs.",
  );
}

let run;
try {
  run = await readJson(runPath);
} catch {
  const initialBalance = await requestJson(`${apiBase}/balance`);
  run = {
    schemaVersion: 1,
    runId: "remaining-wardrobe-meshy-v1-20260728",
    scope: "remaining-wardrobe",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    provider: "Meshy 6",
    concurrency,
    initialBalance: initialBalance.balance,
    estimatedCreditsPerTask,
    estimatedTotalCredits:
      plannedEntries.length * estimatedCreditsPerTask,
    objects: plannedEntries.map((entry) => ({
      ...entry,
      status: "queued",
      taskId: null,
      progress: 0,
      consumedCredits: null,
      attempts: 0,
      error: null,
    })),
  };
  await writeJson(runPath, run);
}

const runByObjectId = new Map(
  run.objects.map((entry) => [entry.objectId, entry]),
);
for (const entry of plannedEntries) {
  if (runByObjectId.has(entry.objectId)) continue;
  const runEntry = {
    ...entry,
    status: "queued",
    taskId: null,
    progress: 0,
    consumedCredits: null,
    attempts: 0,
    error: null,
  };
  run.objects.push(runEntry);
  runByObjectId.set(entry.objectId, runEntry);
}

const saveRun = async () => {
  run.updatedAt = new Date().toISOString();
  await writeJson(runPath, run);
};

const queueEntries = run.objects.filter((entry) => {
  if (versionedObjectIds.has(entry.objectId)) return false;
  if (entry.status === "ambiguous-submit") return false;
  if (entry.status === "remote-failed") return false;
  if (entry.status === "failed" && !entry.taskId) return false;
  return entry.status !== "succeeded" || !entry.downloadedAt;
});
const unsubmittedEntries = queueEntries.filter((entry) => !entry.taskId);
const currentBalance = await requestJson(`${apiBase}/balance`);
const requiredBalance =
  unsubmittedEntries.length * estimatedCreditsPerTask;
if (currentBalance.balance < requiredBalance) {
  throw new Error(
    `Insufficient Meshy credits: ${currentBalance.balance} available, ${requiredBalance} required for ${unsubmittedEntries.length} unsubmitted objects.`,
  );
}

console.log(
  `[meshy-wardrobe] ${wardrobeObjects.length} Wardrobe objects; ${
    wardrobeObjects.length - missingObjects.length
  } already versioned; ${queueEntries.length} queued/resuming.`,
);
console.log(
  `[meshy-wardrobe] balance ${currentBalance.balance}; estimated new spend ${requiredBalance}; concurrency ${concurrency}.`,
);

const submissionPayload = async (entry) => {
  const inputs = await Promise.all(
    entry.inputs.map((assetPath) => fileDataUri(assetPath)),
  );
  if (entry.endpoint === "multi-image-to-3d") {
    return {
      image_urls: inputs,
      ai_model: "meshy-6",
      should_texture: true,
      enable_pbr: false,
      texture_resolution: "2k",
      texture_image_url: inputs[0],
      should_remesh: false,
      remove_lighting: true,
      target_formats: ["glb"],
    };
  }
  return {
    image_url: inputs[0],
    ai_model: "meshy-6",
    should_texture: true,
    enable_pbr: false,
    should_remesh: false,
    remove_lighting: true,
    image_enhancement: true,
    target_formats: ["glb"],
  };
};

const submitTask = async (entry) => {
  entry.status = "submitting";
  entry.createStartedAt = new Date().toISOString();
  entry.attempts += 1;
  entry.error = null;
  await saveRun();
  try {
    const created = await requestJson(`${apiBase}/${entry.endpoint}`, {
      method: "POST",
      body: JSON.stringify(await submissionPayload(entry)),
    });
    entry.taskId = created.result;
    entry.status = "submitted";
    entry.submittedAt = new Date().toISOString();
    await saveRun();
    console.log(
      `[submit] ${entry.objectId} ${entry.endpoint} ${entry.taskId}`,
    );
  } catch (error) {
    entry.error = error.message;
    entry.createFailedAt = new Date().toISOString();
    if (error.status) {
      entry.status = "failed";
    } else {
      entry.status = "ambiguous-submit";
    }
    await saveRun();
    if (!error.status) {
      throw new Error(
        `Ambiguous submission for ${entry.objectId}; reconcile recent ${entry.endpoint} tasks before retrying.`,
      );
    }
    throw error;
  }
};

const pollTask = async (entry) => {
  while (true) {
    const task = await requestJson(
      `${apiBase}/${entry.endpoint}/${entry.taskId}`,
    );
    entry.status = task.status?.toLowerCase() || "unknown";
    entry.progress = task.progress || 0;
    entry.consumedCredits = task.consumed_credits ?? null;
    entry.precedingTasks = task.preceding_tasks ?? null;
    await saveRun();
    if (task.status === "SUCCEEDED") return task;
    if (task.status === "FAILED" || task.status === "CANCELED") {
      entry.status = "remote-failed";
      entry.error =
        task.task_error?.message || `Meshy task ${task.status}.`;
      await saveRun();
      const error = new Error(entry.error);
      error.remoteFinal = true;
      throw error;
    }
    await sleep(pollIntervalMs);
  }
};

const registerVersion = async (entry, stats) => {
  if (versionedObjectIds.has(entry.objectId)) return;
  const multiImage = entry.endpoint === "multi-image-to-3d";
  versions.objects.push({
    objectId: entry.objectId,
    versions: [
      {
        id: "meshy-v1",
        label: "Meshy v1",
        provider: multiImage ? "Meshy 6 Multi-Image" : "Meshy 6",
        model: `/archive/objects/3d/${entry.objectId}-v1.glb`,
        thumbnail: `/archive/objects/3d/${entry.objectId}-v1.png`,
        createdAt: new Date().toISOString().slice(0, 10),
        taskId: entry.taskId,
        faces: stats.faces,
        vertices: stats.vertices,
        status: "review",
        note: multiImage
          ? "Meshy 6 first pass from the catalog front plus cleaned top, side, and underside hollow views; awaiting negative-space and silhouette review."
          : "Meshy 6 first pass from the clean catalog image; awaiting silhouette and material review.",
      },
    ],
  });
  versions.objects.sort((left, right) =>
    left.objectId.localeCompare(right.objectId),
  );
  versions.updatedAt = new Date().toISOString().slice(0, 10);
  await writeJson(versionsPath, versions);
  versionedObjectIds.add(entry.objectId);
};

const completeTask = async (entry, task) => {
  const modelUrl = task.model_urls?.glb;
  const thumbnailUrl =
    task.alpha_thumbnail_url ||
    task.thumbnail_url ||
    task.thumbnail_urls?.front ||
    task.model_urls?.front;
  if (!modelUrl || !thumbnailUrl) {
    throw new Error("Meshy succeeded without both GLB and thumbnail URLs.");
  }
  const modelPath = path.join(
    modelDirectory,
    `${entry.objectId}-v1.glb`,
  );
  const thumbnailPath = path.join(
    modelDirectory,
    `${entry.objectId}-v1.png`,
  );
  await Promise.all([
    download(modelUrl, modelPath),
    download(thumbnailUrl, thumbnailPath),
  ]);
  const stats = await parseGlbStats(modelPath);
  entry.status = "succeeded";
  entry.progress = 100;
  entry.completedAt = new Date().toISOString();
  entry.downloadedAt = new Date().toISOString();
  entry.model = path.relative(repositoryRoot, modelPath);
  entry.thumbnail = path.relative(repositoryRoot, thumbnailPath);
  entry.faces = stats.faces;
  entry.vertices = stats.vertices;
  entry.error = null;
  await registerVersion(entry, stats);
  await saveRun();
  console.log(
    `[done] ${entry.objectId} faces=${stats.faces} vertices=${stats.vertices}`,
  );
};

let nextIndex = 0;
let fatalError = null;
const worker = async (workerNumber) => {
  while (true) {
    if (fatalError) return;
    const index = nextIndex;
    nextIndex += 1;
    if (index >= queueEntries.length) return;
    const entry = queueEntries[index];
    try {
      if (!entry.taskId) await submitTask(entry);
      const task = await pollTask(entry);
      await completeTask(entry, task);
    } catch (error) {
      if (
        entry.status !== "ambiguous-submit" &&
        entry.status !== "remote-failed" &&
        entry.status !== "failed"
      ) {
        entry.status = "recoverable-error";
        entry.error = error.message;
        entry.failedAt = new Date().toISOString();
        await saveRun();
      }
      console.error(
        `[failed] worker=${workerNumber} ${entry.objectId}: ${error.message}`,
      );
      if (error.status === 401 || error.status === 402) {
        fatalError = error;
        return;
      }
    }
  }
};

await fs.mkdir(modelDirectory, { recursive: true });
await Promise.all(
  Array.from({ length: concurrency }, (_, index) => worker(index + 1)),
);

const finalBalance = await requestJson(`${apiBase}/balance`);
run.completedAt = new Date().toISOString();
run.finalBalance = finalBalance.balance;
run.summary = Object.fromEntries(
  Object.entries(
    Object.groupBy(run.objects, (entry) => entry.status),
  ).map(([status, entries]) => [status, entries.length]),
);
await saveRun();
console.log(
  `[meshy-wardrobe] complete summary=${JSON.stringify(run.summary)} balance=${finalBalance.balance}`,
);
