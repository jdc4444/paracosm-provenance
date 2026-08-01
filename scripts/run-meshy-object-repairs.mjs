import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const apiBase = "https://api.meshy.ai/openapi/v1";
const manifestPath = path.join(
  repositoryRoot,
  "data/meshy-object-repair-run-20260728.json",
);
const versionsPath = path.join(repositoryRoot, "data/object-3d-versions.json");
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
        const error = new Error(message);
        error.status = response.status;
        error.body = body;
        throw error;
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
  const extension = path.extname(filePath).toLowerCase();
  const mimeType =
    extension === ".jpg" || extension === ".jpeg"
      ? "image/jpeg"
      : "image/png";
  return `data:${mimeType};base64,${(
    await fs.readFile(filePath)
  ).toString("base64")}`;
};

const parseGlbStats = async (filePath) => {
  const buffer = await fs.readFile(filePath);
  if (buffer.toString("utf8", 0, 4) !== "glTF") {
    return { faces: 0, vertices: 0 };
  }
  const jsonChunkLength = buffer.readUInt32LE(12);
  const jsonChunkType = buffer.readUInt32LE(16);
  if (jsonChunkType !== 0x4e4f534a) {
    return { faces: 0, vertices: 0 };
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

const jobs = [
  {
    objectId: "lavender-check-fuzzy-shoes",
    endpoint: "retexture",
    expectedCredits: 10,
    outputStem: "lavender-check-fuzzy-shoes-v2",
    version: {
      id: "meshy-retexture-v2",
      label: "Meshy retexture v2",
      provider: "Meshy 6 Retexture",
      status: "review",
      note:
        "Image-guided retexture pass from the clean lavender checker and fuzzy trim reference. This pair source is preserved for the separate left and right Blender exports.",
    },
    createPayload: async () => ({
      input_task_id: "019fa6e4-e1af-74a9-b6f0-ed2a9e5be7cc",
      image_style_url: await fileDataUri(
        "public/archive/objects/wardrobe/lavender-check-fuzzy-shoes.png",
      ),
      ai_model: "meshy-6",
      enable_original_uv: true,
      enable_pbr: false,
      target_formats: ["glb"],
      alpha_thumbnail: true,
    }),
  },
  {
    objectId: "burgundy-button-corset",
    endpoint: "multi-image-to-3d",
    expectedCredits: 30,
    outputStem: "burgundy-button-corset-v2",
    version: {
      id: "meshy-multiview-v2",
      label: "Meshy multiview v2",
      provider: "Meshy 6 Multi-Image",
      status: "review",
      note:
        "Multi-image rerun using the front catalog image and a hollow three-quarter reconstruction view. Review the top opening and interior shell.",
    },
    createPayload: async () => {
      const front = await fileDataUri(
        "public/archive/objects/wardrobe/burgundy-button-corset.png",
      );
      return {
        image_urls: [
          front,
          await fileDataUri(
            "public/archive/objects/wardrobe/3d-inputs/burgundy-button-corset-three-quarter.png",
          ),
        ],
        ai_model: "meshy-6",
        should_texture: true,
        enable_pbr: false,
        texture_resolution: "2k",
        texture_image_url: front,
        should_remesh: false,
        remove_lighting: true,
        target_formats: ["glb"],
      };
    },
  },
  {
    objectId: "teal-sculpted-corset",
    endpoint: "multi-image-to-3d",
    expectedCredits: 30,
    outputStem: "teal-sculpted-corset-v2",
    version: {
      id: "meshy-multiview-v2",
      label: "Meshy multiview v2",
      provider: "Meshy 6 Multi-Image",
      status: "review",
      note:
        "Multi-image rerun using the front catalog image and a hollow three-quarter reconstruction view. Review the neck, arm, and lower openings.",
    },
    createPayload: async () => {
      const front = await fileDataUri(
        "public/archive/objects/wardrobe/teal-sculpted-corset.png",
      );
      return {
        image_urls: [
          front,
          await fileDataUri(
            "public/archive/objects/wardrobe/3d-inputs/teal-sculpted-corset-three-quarter.png",
          ),
        ],
        ai_model: "meshy-6",
        should_texture: true,
        enable_pbr: false,
        texture_resolution: "2k",
        texture_image_url: front,
        should_remesh: false,
        remove_lighting: true,
        target_formats: ["glb"],
      };
    },
  },
];

let manifest;
try {
  manifest = await readJson(manifestPath);
} catch {
  const balance = await requestJson(`${apiBase}/balance`);
  manifest = {
    schemaVersion: 1,
    runId: "object-repairs-20260728",
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    initialBalance: balance.balance,
    expectedCredits: jobs.reduce(
      (total, item) => total + item.expectedCredits,
      0,
    ),
    jobs: jobs.map((item) => ({
      objectId: item.objectId,
      endpoint: item.endpoint,
      outputStem: item.outputStem,
      expectedCredits: item.expectedCredits,
      taskId: null,
      status: "queued",
      progress: 0,
      consumedCredits: null,
      error: null,
    })),
  };
  await writeJson(manifestPath, manifest);
}

const manifestByObject = new Map(
  manifest.jobs.map((item) => [item.objectId, item]),
);
const unsubmitted = jobs.filter(
  (item) => !manifestByObject.get(item.objectId)?.taskId,
);
const balance = await requestJson(`${apiBase}/balance`);
const requiredCredits = unsubmitted.reduce(
  (total, item) => total + item.expectedCredits,
  0,
);
if (balance.balance < requiredCredits) {
  throw new Error(
    `Insufficient Meshy balance: ${balance.balance} available, ${requiredCredits} required.`,
  );
}
console.log(
  `[meshy-repair] balance ${balance.balance}; new spend up to ${requiredCredits}.`,
);

const saveManifest = async () => {
  manifest.updatedAt = new Date().toISOString();
  await writeJson(manifestPath, manifest);
};

for (const job of jobs) {
  const entry = manifestByObject.get(job.objectId);
  if (!entry.taskId) {
    const createdAt = Date.now();
    entry.createStartedAt = new Date(createdAt).toISOString();
    await saveManifest();
    try {
      const created = await requestJson(`${apiBase}/${job.endpoint}`, {
        method: "POST",
        body: JSON.stringify(await job.createPayload()),
      });
      entry.taskId = created.result;
      entry.status = "submitted";
      entry.submittedAt = new Date().toISOString();
      await saveManifest();
      console.log(`[submit] ${job.objectId} ${entry.taskId}`);
    } catch (error) {
      entry.status = "ambiguous-submit";
      entry.error = error.message;
      entry.createFailedAt = new Date().toISOString();
      await saveManifest();
      throw new Error(
        `Submission for ${job.objectId} was ambiguous. Inspect Meshy's recent ${job.endpoint} task list before retrying.`,
      );
    }
  }
}

const pollJob = async (job) => {
  const entry = manifestByObject.get(job.objectId);
  if (entry.status === "succeeded" && entry.downloadedAt) return;
  while (true) {
    const task = await requestJson(
      `${apiBase}/${job.endpoint}/${entry.taskId}`,
    );
    entry.status = task.status?.toLowerCase() || "unknown";
    entry.progress = task.progress || 0;
    entry.consumedCredits = task.consumed_credits ?? null;
    entry.precedingTasks = task.preceding_tasks ?? null;
    await saveManifest();
    if (task.status === "SUCCEEDED") {
      const glbUrl = task.model_urls?.glb;
      const thumbnailUrl =
        task.alpha_thumbnail_url ||
        task.thumbnail_url ||
        task.thumbnail_urls?.front;
      if (!glbUrl || !thumbnailUrl) {
        throw new Error(`${job.objectId} succeeded without downloadable assets.`);
      }
      const modelPath = path.join(modelDirectory, `${job.outputStem}.glb`);
      const thumbnailPath = path.join(modelDirectory, `${job.outputStem}.png`);
      await Promise.all([
        download(glbUrl, modelPath),
        download(thumbnailUrl, thumbnailPath),
      ]);
      entry.status = "succeeded";
      entry.downloadedAt = new Date().toISOString();
      entry.assets = {
        model: path.relative(repositoryRoot, modelPath),
        thumbnail: path.relative(repositoryRoot, thumbnailPath),
      };
      entry.stats = await parseGlbStats(modelPath);
      await saveManifest();
      console.log(
        `[complete] ${job.objectId} ${entry.stats.faces} faces ${entry.stats.vertices} vertices`,
      );
      return;
    }
    if (task.status === "FAILED" || task.status === "CANCELED") {
      entry.error =
        task.task_error?.message || `Meshy task ${task.status}.`;
      await saveManifest();
      throw new Error(`${job.objectId}: ${entry.error}`);
    }
    console.log(
      `[poll] ${job.objectId} ${entry.status} ${entry.progress}%`,
    );
    await sleep(pollIntervalMs);
  }
};

await Promise.all(jobs.map((job) => pollJob(job)));

const versions = await readJson(versionsPath);
for (const job of jobs) {
  const entry = manifestByObject.get(job.objectId);
  const record = versions.objects.find(
    (item) => item.objectId === job.objectId,
  );
  if (!record) {
    throw new Error(`Missing 3D registry record for ${job.objectId}.`);
  }
  const nextVersion = {
    ...job.version,
    model: `/archive/objects/3d/${job.outputStem}.glb`,
    thumbnail: `/archive/objects/3d/${job.outputStem}.png`,
    createdAt: new Date().toISOString().slice(0, 10),
    taskId: entry.taskId,
    faces: entry.stats.faces,
    vertices: entry.stats.vertices,
  };
  const existingIndex = record.versions.findIndex(
    (item) => item.id === nextVersion.id,
  );
  if (existingIndex >= 0) record.versions[existingIndex] = nextVersion;
  else record.versions.push(nextVersion);
}
versions.updatedAt = new Date().toISOString().slice(0, 10);
await writeJson(versionsPath, versions);

const finalBalance = await requestJson(`${apiBase}/balance`);
manifest.finalBalance = finalBalance.balance;
manifest.completedAt = new Date().toISOString();
await saveManifest();
console.log(
  `[meshy-repair] complete; balance ${finalBalance.balance}; spent ${manifest.initialBalance - finalBalance.balance}.`,
);
