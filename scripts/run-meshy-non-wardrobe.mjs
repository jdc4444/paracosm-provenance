import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const inventoryPath = path.join(repositoryRoot, "data/object-inventory.json");
const versionsPath = path.join(repositoryRoot, "data/object-3d-versions.json");
const scope = process.env.MESHY_SCOPE || "non-wardrobe";
const solidWardrobeSelectionPath = path.join(
  repositoryRoot,
  "data/meshy-solid-wardrobe-selection-20260728.json",
);
const runPath = path.join(
  repositoryRoot,
  scope === "solid-wardrobe"
    ? "data/meshy-solid-wardrobe-run-20260728.json"
    : "data/meshy-non-wardrobe-run-20260727.json",
);
const modelDirectory = path.join(
  repositoryRoot,
  "public/archive/objects/3d",
);
const apiBase = "https://api.meshy.ai/openapi/v1";
const concurrency = Math.max(
  1,
  Math.min(10, Number.parseInt(process.env.MESHY_CONCURRENCY || "8", 10)),
);
const pollIntervalMs = Math.max(
  5_000,
  Number.parseInt(process.env.MESHY_POLL_INTERVAL_MS || "15000", 10),
);
const estimatedCreditsPerTask = 30;

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
  if (process.env.MESHY_API_KEY) {
    return process.env.MESHY_API_KEY;
  }
  return execFileSync(
    "security",
    ["find-generic-password", "-s", "MESHY_API_KEY", "-w"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
  ).trim();
};

const apiKey = getApiKey();
const headers = {
  Authorization: `Bearer ${apiKey}`,
  "Content-Type": "application/json",
};

const requestJson = async (url, options = {}, attempts = 8) => {
  let delayMs = 2_000;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    let response;
    try {
      response = await fetch(url, {
        ...options,
        headers: { ...headers, ...(options.headers || {}) },
      });
    } catch (error) {
      const canRetry = (options.method || "GET") === "GET";
      if (!canRetry || attempt === attempts) {
        throw error;
      }
      await sleep(delayMs);
      delayMs = Math.min(delayMs * 2, 30_000);
      continue;
    }
    const text = await response.text();
    let body = null;
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = { message: text };
      }
    }
    if (response.ok) {
      return body;
    }
    const message =
      body?.message ||
      body?.task_error?.message ||
      `${response.status} ${response.statusText}`;
    const retryable =
      response.status === 429 || response.status >= 500 || response.status === 408;
    if (!retryable || attempt === attempts) {
      const error = new Error(message);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    await sleep(delayMs);
    delayMs = Math.min(delayMs * 2, 30_000);
  }
  throw new Error("Meshy request failed without a response.");
};

const download = async (url, destination) => {
  let response;
  for (let attempt = 1; attempt <= 6; attempt += 1) {
    try {
      response = await fetch(url);
      if (response.ok) {
        break;
      }
      if (response.status < 500 || attempt === 6) {
        throw new Error(
          `Download failed for ${path.basename(destination)}: ${response.status}`,
        );
      }
    } catch (error) {
      if (attempt === 6) {
        throw error;
      }
    }
    await sleep(Math.min(2 ** attempt * 1_000, 15_000));
  }
  if (!response?.ok) {
    throw new Error(`Download failed for ${path.basename(destination)}.`);
  }
  const temporaryPath = `${destination}.tmp`;
  await fs.writeFile(
    temporaryPath,
    Buffer.from(await response.arrayBuffer()),
  );
  await fs.rename(temporaryPath, destination);
};

const parseGlbStats = async (filePath) => {
  const buffer = await fs.readFile(filePath);
  if (buffer.toString("utf8", 0, 4) !== "glTF") {
    return { faces: null, vertices: null };
  }
  const jsonChunkLength = buffer.readUInt32LE(12);
  const jsonChunkType = buffer.readUInt32LE(16);
  if (jsonChunkType !== 0x4e4f534a) {
    return { faces: null, vertices: null };
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
      const positionAccessor = document.accessors?.[primitive.attributes?.POSITION];
      if (positionAccessor?.count) {
        vertices += positionAccessor.count;
      }
      if (primitive.indices !== undefined) {
        const indexAccessor = document.accessors?.[primitive.indices];
        faces += Math.floor((indexAccessor?.count || 0) / 3);
      } else if (positionAccessor?.count) {
        faces += Math.floor(positionAccessor.count / 3);
      }
    }
  }
  return { faces, vertices };
};

const inventory = await readJson(inventoryPath);
let versions = await readJson(versionsPath);
const versionedObjectIds = new Set(
  versions.objects.flatMap((item) =>
    item.versions?.length ? [item.objectId] : [],
  ),
);

const nonWardrobeObjects = [
  ...inventory.objects,
  ...inventory.generatedGroups.flatMap((group) =>
    group.category === "Wardrobe"
      ? []
      : group.objects.map((item) => ({
          ...item,
          category: group.category,
          image:
            item.image || `${group.imageDirectory}/${item.id}.png`,
          sourceFiles: item.sourceFiles || group.sourceFiles || [],
        })),
  ),
];

let targetObjects = nonWardrobeObjects;
let selection = null;
if (scope === "solid-wardrobe") {
  selection = await readJson(solidWardrobeSelectionPath);
  const selectedIds = new Set(
    selection.objects.map((item) => item.objectId),
  );
  const wardrobeObjects = inventory.generatedGroups.flatMap((group) =>
    group.category !== "Wardrobe"
      ? []
      : group.objects.map((item) => ({
          ...item,
          category: group.category,
          image:
            item.image || `${group.imageDirectory}/${item.id}.png`,
          sourceFiles: item.sourceFiles || group.sourceFiles || [],
        })),
  );
  targetObjects = wardrobeObjects.filter((item) => selectedIds.has(item.id));
  const resolvedIds = new Set(targetObjects.map((item) => item.id));
  const unresolvedIds = [...selectedIds].filter((id) => !resolvedIds.has(id));
  if (unresolvedIds.length) {
    throw new Error(
      `Solid wardrobe selection contains unknown object IDs: ${unresolvedIds.join(", ")}`,
    );
  }
}

if (scope !== "non-wardrobe" && scope !== "solid-wardrobe") {
  throw new Error(`Unsupported Meshy scope: ${scope}`);
}

const missingObjects = targetObjects.filter(
  (item) => !versionedObjectIds.has(item.id),
);

let run;
try {
  run = await readJson(runPath);
} catch {
  const initialBalance = await requestJson(`${apiBase}/balance`);
  run = {
    schemaVersion: 1,
    runId:
      scope === "solid-wardrobe"
        ? "solid-wardrobe-meshy-v1-20260728"
        : "non-wardrobe-meshy-v1-20260727",
    scope,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    provider: "Meshy 6",
    endpoint: "image-to-3d",
    settings: {
      ai_model: "meshy-6",
      should_texture: true,
      enable_pbr: false,
      should_remesh: false,
      remove_lighting: true,
      image_enhancement: true,
      target_formats: ["glb"],
    },
    concurrency,
    initialBalance: initialBalance.balance,
    estimatedCreditsPerTask,
    estimatedTotalCredits: missingObjects.length * estimatedCreditsPerTask,
    selection:
      scope === "solid-wardrobe"
        ? path.relative(repositoryRoot, solidWardrobeSelectionPath)
        : null,
    objects: missingObjects.map((item) => ({
      objectId: item.id,
      name: item.name,
      category: item.category,
      image: item.image,
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

const manifestById = new Map(
  run.objects.map((item) => [item.objectId, item]),
);

for (const object of missingObjects) {
  if (!manifestById.has(object.id)) {
    const entry = {
      objectId: object.id,
      name: object.name,
      category: object.category,
      image: object.image,
      status: "queued",
      taskId: null,
      progress: 0,
      consumedCredits: null,
      attempts: 0,
      error: null,
    };
    run.objects.push(entry);
    manifestById.set(object.id, entry);
  }
}

const saveRun = async () => {
  run.updatedAt = new Date().toISOString();
  await writeJson(runPath, run);
};

const queueEntries = run.objects.filter((entry) => {
  const alreadyVersioned = versionedObjectIds.has(entry.objectId);
  return !alreadyVersioned && entry.status !== "succeeded";
});

const unsubmittedCount = queueEntries.filter((entry) => !entry.taskId).length;
const currentBalance = await requestJson(`${apiBase}/balance`);
const requiredBalance = unsubmittedCount * estimatedCreditsPerTask;
if (currentBalance.balance < requiredBalance) {
  throw new Error(
    `Insufficient Meshy credits: ${currentBalance.balance} available, ${requiredBalance} required for ${unsubmittedCount} unsubmitted objects.`,
  );
}

console.log(
  `[meshy] ${targetObjects.length} ${scope} objects; ${
    targetObjects.filter((item) => versionedObjectIds.has(item.id)).length
  } already versioned; ${queueEntries.length} queued/resuming.`,
);
console.log(
  `[meshy] balance ${currentBalance.balance}; estimated new spend ${requiredBalance}; concurrency ${concurrency}.`,
);

const inventoryById = new Map(
  targetObjects.map((item) => [item.id, item]),
);

const submitTask = async (entry) => {
  const object = inventoryById.get(entry.objectId);
  const imagePath = path.join(repositoryRoot, "public", object.image);
  const imageBuffer = await fs.readFile(imagePath);
  const extension = path.extname(imagePath).toLowerCase();
  const mimeType = extension === ".jpg" || extension === ".jpeg"
    ? "image/jpeg"
    : "image/png";
  const imageUrl = `data:${mimeType};base64,${imageBuffer.toString("base64")}`;
  const created = await requestJson(`${apiBase}/image-to-3d`, {
    method: "POST",
    body: JSON.stringify({
      image_url: imageUrl,
      ...run.settings,
    }),
  });
  entry.taskId = created.result;
  entry.status = "submitted";
  entry.progress = 0;
  entry.attempts += 1;
  entry.submittedAt = new Date().toISOString();
  entry.error = null;
  await saveRun();
  console.log(`[submit] ${entry.objectId} ${entry.taskId}`);
};

const pollTask = async (entry) => {
  while (true) {
    const task = await requestJson(
      `${apiBase}/image-to-3d/${entry.taskId}`,
    );
    entry.status = task.status?.toLowerCase() || "unknown";
    entry.progress = task.progress || 0;
    entry.consumedCredits = task.consumed_credits ?? null;
    entry.precedingTasks = task.preceding_tasks ?? null;
    await saveRun();
    if (task.status === "SUCCEEDED") {
      return task;
    }
    if (task.status === "FAILED" || task.status === "CANCELED") {
      throw new Error(
        task.task_error?.message || `Meshy task ${task.status}`,
      );
    }
    await sleep(pollIntervalMs);
  }
};

const addVersion = async (entry, task, stats) => {
  if (versionedObjectIds.has(entry.objectId)) {
    return;
  }
  versions.objects.push({
    objectId: entry.objectId,
    versions: [
      {
        id: "meshy-v1",
        label: "Meshy v1",
        provider: "Meshy 6",
        model: `/archive/objects/3d/${entry.objectId}-v1.glb`,
        thumbnail: `/archive/objects/3d/${entry.objectId}-v1.png`,
        createdAt: new Date().toISOString().slice(0, 10),
        taskId: entry.taskId,
        faces: stats.faces,
        vertices: stats.vertices,
        status: "review",
        note:
          scope === "solid-wardrobe"
            ? "Automated Meshy 6 first pass for a shape-stable wardrobe object from the clean catalog image; awaiting review."
            : "Automated Meshy 6 first pass from the clean catalog image; awaiting review.",
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
    task.thumbnail_url || task.model_urls?.front || task.model_urls?.right;
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
  entry.model = path.relative(repositoryRoot, modelPath);
  entry.thumbnail = path.relative(repositoryRoot, thumbnailPath);
  entry.faces = stats.faces;
  entry.vertices = stats.vertices;
  entry.error = null;
  await addVersion(entry, task, stats);
  await saveRun();
  console.log(
    `[done] ${entry.objectId} faces=${stats.faces ?? "?"} vertices=${stats.vertices ?? "?"}`,
  );
};

let nextIndex = 0;
let fatalError = null;

const worker = async (workerNumber) => {
  while (true) {
    if (fatalError) {
      return;
    }
    const index = nextIndex;
    nextIndex += 1;
    if (index >= queueEntries.length) {
      return;
    }
    const entry = queueEntries[index];
    try {
      if (!entry.taskId) {
        await submitTask(entry);
      }
      const task = await pollTask(entry);
      await completeTask(entry, task);
    } catch (error) {
      entry.status = "failed";
      entry.error = error.message;
      entry.failedAt = new Date().toISOString();
      await saveRun();
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
  `[meshy] complete summary=${JSON.stringify(run.summary)} balance=${finalBalance.balance}`,
);

if (fatalError) {
  throw fatalError;
}
if (run.objects.some((entry) => entry.status !== "succeeded")) {
  process.exitCode = 2;
}
