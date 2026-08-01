#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const apiBase = "https://api.meshy.ai/openapi/v1";
const runPath = path.join(
  root,
  "data/meshy-casually-tossed-gloves-v2-20260729.json",
);
const outputDirectory = path.join(root, "public/archive/objects/3d");
const pollIntervalMs = 12_000;
const estimatedCreditsPerTask = 30;
const sourceImage =
  "/archive/objects/wardrobe/tossed/gray-opera-gloves.png";
const stem = "gray-opera-gloves-casually-tossed-v2";

const sleep = (milliseconds) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

const apiKey =
  process.env.MESHY_API_KEY ||
  execFileSync(
    "security",
    ["find-generic-password", "-s", "MESHY_API_KEY", "-w"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
  ).trim();
const headers = {
  Authorization: `Bearer ${apiKey}`,
  "Content-Type": "application/json",
};

async function requestJson(url, options = {}, attempts = 7) {
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
    try {
      body = raw ? JSON.parse(raw) : null;
    } catch {
      body = { message: raw };
    }
    if (response.ok) return body;
    const error = new Error(
      body?.message ||
        body?.task_error?.message ||
        `${response.status} ${response.statusText}`,
    );
    error.status = response.status;
    if (
      !isGet ||
      attempt === attempts ||
      (!([408, 429].includes(response.status)) && response.status < 500)
    ) {
      throw error;
    }
    await sleep(delayMs);
    delayMs = Math.min(delayMs * 2, 30_000);
  }
  throw new Error("Meshy request failed without a response.");
}

let writeSequence = 0;
let writeQueue = Promise.resolve();
async function writeRun(run) {
  run.updatedAt = new Date().toISOString();
  writeSequence += 1;
  const temporaryPath = `${runPath}.${process.pid}.${writeSequence}.tmp`;
  const body = `${JSON.stringify(run, null, 2)}\n`;
  const operation = writeQueue.then(async () => {
    await fs.writeFile(temporaryPath, body);
    await fs.rename(temporaryPath, runPath);
  });
  writeQueue = operation.catch(() => {});
  return operation;
}

async function fileDataUri(publicPath) {
  const filePath = path.join(root, "public", publicPath.replace(/^\//, ""));
  return `data:image/png;base64,${(
    await fs.readFile(filePath)
  ).toString("base64")}`;
}

async function download(url, destination) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Download failed: ${response.status}`);
  }
  const temporaryPath = `${destination}.${process.pid}.tmp`;
  await fs.writeFile(
    temporaryPath,
    Buffer.from(await response.arrayBuffer()),
  );
  await fs.rename(temporaryPath, destination);
}

async function parseGlbStats(filePath) {
  const buffer = await fs.readFile(filePath);
  if (buffer.toString("utf8", 0, 4) !== "glTF") {
    throw new Error(`${path.basename(filePath)} is not a GLB`);
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
      const positions = document.accessors?.[primitive.attributes?.POSITION];
      vertices += positions?.count || 0;
      faces +=
        primitive.indices === undefined
          ? Math.floor((positions?.count || 0) / 3)
          : Math.floor(
              (document.accessors?.[primitive.indices]?.count || 0) / 3,
            );
    }
  }
  return { faces, vertices };
}

let run;
try {
  run = JSON.parse(await fs.readFile(runPath, "utf8"));
} catch {
  const balance = await requestJson(`${apiBase}/balance`);
  run = {
    schemaVersion: 1,
    runId: "meshy-casually-tossed-gloves-v2-20260729",
    purpose:
      "Reconstruct the white-background casually tossed Gray Opera Gloves reference as a textured static Meshy model",
    createdAt: new Date().toISOString(),
    initialBalance: balance.balance,
    estimatedCreditsPerTask,
    object: {
      objectId: "gray-opera-gloves",
      name: "Gray Opera Gloves",
      input: sourceImage,
      status: "queued",
      taskId: null,
      consumedCredits: null,
      progress: 0,
    },
  };
  await writeRun(run);
}

const item = run.object;
if (item.status !== "succeeded") {
  const balance = await requestJson(`${apiBase}/balance`);
  const requiredCredits = item.taskId ? 0 : estimatedCreditsPerTask;
  if (balance.balance < requiredCredits) {
    throw new Error(
      `Insufficient Meshy credits: ${balance.balance} available, ${requiredCredits} estimated`,
    );
  }
  console.log(
    JSON.stringify({
      balance: balance.balance,
      taskId: item.taskId,
      estimatedNewSpend: requiredCredits,
    }),
  );

  if (!item.taskId) {
    item.status = "submitting";
    await writeRun(run);
    const created = await requestJson(`${apiBase}/image-to-3d`, {
      method: "POST",
      body: JSON.stringify({
        image_url: await fileDataUri(item.input),
        ai_model: "meshy-6",
        should_texture: true,
        enable_pbr: false,
        should_remesh: false,
        remove_lighting: true,
        image_enhancement: true,
        target_formats: ["glb"],
      }),
    });
    item.taskId = created.result;
    item.status = "submitted";
    item.submittedAt = new Date().toISOString();
    await writeRun(run);
    console.log(`[submit] ${item.objectId} ${item.taskId}`);
  }

  let task;
  while (true) {
    task = await requestJson(`${apiBase}/image-to-3d/${item.taskId}`);
    item.status = task.status?.toLowerCase() || "unknown";
    item.progress = task.progress || 0;
    item.consumedCredits = task.consumed_credits ?? null;
    await writeRun(run);
    console.log(`[poll] ${item.status} ${item.progress}%`);
    if (task.status === "SUCCEEDED") break;
    if (["FAILED", "CANCELED"].includes(task.status)) {
      item.status = "remote-failed";
      item.error =
        task.task_error?.message || `Meshy task ${task.status}`;
      await writeRun(run);
      throw new Error(`${item.objectId}: ${item.error}`);
    }
    await sleep(pollIntervalMs);
  }

  const modelUrl = task.model_urls?.glb;
  const thumbnailUrl =
    task.alpha_thumbnail_url ||
    task.thumbnail_url ||
    task.thumbnail_urls?.front;
  if (!modelUrl || !thumbnailUrl) {
    throw new Error(`${item.objectId}: Meshy returned incomplete assets`);
  }

  await fs.mkdir(outputDirectory, { recursive: true });
  const modelPath = path.join(outputDirectory, `${stem}.glb`);
  const thumbnailPath = path.join(outputDirectory, `${stem}.png`);
  await Promise.all([
    download(modelUrl, modelPath),
    download(thumbnailUrl, thumbnailPath),
  ]);
  const stats = await parseGlbStats(modelPath);
  item.status = "succeeded";
  item.progress = 100;
  item.model = `/archive/objects/3d/${stem}.glb`;
  item.thumbnail = `/archive/objects/3d/${stem}.png`;
  item.faces = stats.faces;
  item.vertices = stats.vertices;
  item.completedAt = new Date().toISOString();
  const finalBalance = await requestJson(`${apiBase}/balance`);
  run.finalBalance = finalBalance.balance;
  run.finishedAt = new Date().toISOString();
  await writeRun(run);
  console.log(
    JSON.stringify({
      status: item.status,
      taskId: item.taskId,
      faces: item.faces,
      vertices: item.vertices,
      spent: run.initialBalance - run.finalBalance,
      finalBalance: run.finalBalance,
    }),
  );
} else {
  console.log(
    JSON.stringify({
      status: item.status,
      taskId: item.taskId,
      model: item.model,
      thumbnail: item.thumbnail,
      resumed: true,
    }),
  );
}
