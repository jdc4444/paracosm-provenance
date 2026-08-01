import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const apiBase = "https://api.meshy.ai/openapi/v1";
const endpoint = "multi-image-to-3d";
const expectedCredits = 30;
const version = process.env.MESHY_HEAD_VERSION || "v1";
if (!/^v\d+$/.test(version)) {
  throw new Error(`Invalid MESHY_HEAD_VERSION: ${version}`);
}
const pollIntervalMs = Number.parseInt(
  process.env.MESHY_POLL_INTERVAL_MS || "15000",
  10,
);
const assetRoot = path.join(
  repositoryRoot,
  `public/archive/character-reference/abby/meshy/delighted-side-glance-head-${version}`,
);
const inputRoot = path.join(assetRoot, "inputs");
const manifestPath = path.join(
  repositoryRoot,
  `data/meshy-abby-delighted-side-glance-head-${version}-20260729.json`,
);
const inputPaths = [
  path.join(inputRoot, "front.png"),
  path.join(inputRoot, "left.png"),
  path.join(inputRoot, "right.png"),
  path.join(inputRoot, "back.png"),
];
const modelPath = path.join(
  assetRoot,
  `delighted-side-glance-head-meshy-${version}.glb`,
);
const previewPath = path.join(
  assetRoot,
  `delighted-side-glance-head-meshy-${version}.png`,
);

const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

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

const fileDataUri = async (filePath) =>
  `data:image/png;base64,${(await fs.readFile(filePath)).toString("base64")}`;

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

await Promise.all(inputPaths.map((inputPath) => fs.access(inputPath)));
await fs.mkdir(assetRoot, { recursive: true });

let manifest;
try {
  manifest = await readJson(manifestPath);
} catch {
  manifest = {
    schemaVersion: 1,
    runId: `abby-delighted-side-glance-head-meshy-${version}-20260729`,
    subjectId: "abby-delighted-side-glance-head",
    endpoint,
    expectedCredits,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    taskId: null,
    status: "queued",
    progress: 0,
    consumedCredits: null,
    error: null,
    inputs: inputPaths.map((inputPath) =>
      path.relative(repositoryRoot, inputPath),
    ),
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

  const views = await Promise.all(inputPaths.map(fileDataUri));
  manifest.createStartedAt = new Date().toISOString();
  await saveManifest();
  try {
    const created = await requestJson(`${apiBase}/${endpoint}`, {
      method: "POST",
      body: JSON.stringify({
        image_urls: views,
        ai_model: "meshy-6",
        should_texture: true,
        enable_pbr: false,
        texture_resolution: "2k",
        texture_image_url: views[0],
        should_remesh: false,
        remove_lighting: true,
        target_formats: ["glb"],
      }),
    });
    manifest.taskId = created.result;
    manifest.status = "submitted";
    manifest.submittedAt = new Date().toISOString();
    await saveManifest();
    console.log(`[submit] ${manifest.subjectId} ${manifest.taskId}`);
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
    console.log(
      `[poll] ${manifest.status} ${manifest.progress}% preceding=${manifest.precedingTasks ?? "?"}`,
    );

    if (task.status === "SUCCEEDED") {
      const glbUrl = task.model_urls?.glb;
      const previewUrl =
        task.alpha_thumbnail_url ||
        task.thumbnail_url ||
        task.thumbnail_urls?.front;
      if (!glbUrl || !previewUrl) {
        throw new Error("Meshy succeeded without downloadable assets.");
      }
      await Promise.all([
        download(glbUrl, modelPath),
        download(previewUrl, previewPath),
      ]);
      manifest.status = "succeeded";
      manifest.downloadedAt = new Date().toISOString();
      manifest.assets = {
        model: path.relative(repositoryRoot, modelPath),
        preview: path.relative(repositoryRoot, previewPath),
      };
      manifest.stats = await parseGlbStats(modelPath);
      const finalBalance = await requestJson(`${apiBase}/balance`);
      manifest.finalBalance = finalBalance.balance;
      await saveManifest();
      console.log(
        `[complete] ${manifest.stats.faces} faces ${manifest.stats.vertices} vertices balance=${manifest.finalBalance}`,
      );
      break;
    }

    if (task.status === "FAILED" || task.status === "CANCELED") {
      manifest.error =
        task.task_error?.message || `Meshy task ${task.status.toLowerCase()}.`;
      await saveManifest();
      throw new Error(manifest.error);
    }

    await sleep(pollIntervalMs);
  }
}
