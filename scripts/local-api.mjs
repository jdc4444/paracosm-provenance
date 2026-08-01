import {
  createReadStream,
  existsSync,
  readFileSync,
  renameSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { spawn } from "node:child_process";

const ROOT = process.cwd();
const PORT = 3498;
const STATE_PATH = join(ROOT, "public", "data", "state.json");
const FEEDBACK_PATH = join(ROOT, "data", "feedback.json");
const SHOT_REGISTRY_PATH = join(ROOT, "data", "canonical", "shot-registry.json");
const ARCHIVE_ROOT = resolve(ROOT, "public", "archive");
let scanProcess = null;
let scanStartedAt = null;
let scanOutput = [];

const appForKind = {
  premiere: "Adobe Premiere Pro 2026",
  after_effects: "Adobe After Effects 2026",
  cinema4d: "Cinema 4D 2026",
  resolve: "DaVinci Resolve",
};

function send(res, status, body, type = "application/json") {
  res.writeHead(status, {
    "Content-Type": type,
    "Cache-Control": "no-store",
    "Access-Control-Allow-Origin": "http://localhost:3497",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  });
  res.end(typeof body === "string" ? body : JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolveBody, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1_000_000) reject(new Error("Request too large"));
    });
    req.on("end", () => {
      try {
        resolveBody(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function copyToClipboard(value) {
  return new Promise((resolveCopy, reject) => {
    const process = spawn("pbcopy", [], {
      stdio: ["pipe", "ignore", "ignore"],
    });
    process.on("error", reject);
    process.on("close", (code) => {
      if (code === 0) resolveCopy();
      else reject(new Error(`pbcopy exited with code ${code ?? "unknown"}`));
    });
    process.stdin.end(value);
  });
}

function safeArchivePath(urlPath) {
  const relative = decodeURIComponent(urlPath.replace(/^\/archive\//, ""));
  const candidate = resolve(ARCHIVE_ROOT, normalize(relative));
  return candidate.startsWith(`${ARCHIVE_ROOT}/`) ? candidate : null;
}

function readFeedback() {
  return JSON.parse(readFileSync(FEEDBACK_PATH, "utf8"));
}

function writeFeedback(feedback) {
  const temporaryPath = `${FEEDBACK_PATH}.${process.pid}.tmp`;
  writeFileSync(temporaryPath, `${JSON.stringify(feedback, null, 2)}\n`);
  renameSync(temporaryPath, FEEDBACK_PATH);
}

function validateFeedbackUpdate(body) {
  if (!body || !["note", "parent", "general", "edit"].includes(body.kind)) {
    throw new Error("A valid feedback record kind is required.");
  }
  if (typeof body.id !== "string" || !body.id) {
    throw new Error("A feedback record id is required.");
  }
  if (
    typeof body.noteDescription !== "string" ||
    body.noteDescription.length > 10_000
  ) {
    throw new Error("Note Description must be text under 10,000 characters.");
  }
  if (typeof body.dependency !== "string" || body.dependency.length > 10_000) {
    throw new Error("Dependency must be text under 10,000 characters.");
  }
  if (
    body.kind !== "parent" &&
    body.title !== undefined &&
    (typeof body.title !== "string" ||
      !body.title.trim() ||
      body.title.length > 300)
  ) {
    throw new Error("Note must have a name under 300 characters.");
  }
  if (
    !Array.isArray(body.shotIds) ||
    body.shotIds.some((shotId) => typeof shotId !== "string")
  ) {
    throw new Error("Shot assignments must be a list of stable shot ids.");
  }
  if (
    body.parentIds !== undefined &&
    (body.kind !== "note" ||
      !Array.isArray(body.parentIds) ||
      !body.parentIds.length ||
      body.parentIds.some(
        (parentId) => typeof parentId !== "string" || !parentId,
      ))
  ) {
    throw new Error("Parent must be one or more valid feedback categories.");
  }
  if (
    body.kind === "edit" &&
    body.status !== undefined &&
    !["to-incorporate", "incorporated", "superseded"].includes(body.status)
  ) {
    throw new Error("Edit status is not recognized.");
  }
  if (body.kind === "edit" && body.shotIds.length !== 2) {
    throw new Error("A swap edit must keep exactly two shot assignments.");
  }
}

function startScan(quick = false) {
  if (scanProcess) return false;
  scanStartedAt = new Date().toISOString();
  scanOutput = [];
  scanProcess = spawn("python3", ["scripts/scan.py", ...(quick ? ["--quick"] : [])], {
    cwd: ROOT,
    env: process.env,
  });
  const collect = (chunk) => {
    scanOutput.push(...chunk.toString().split(/\r?\n/).filter(Boolean));
    scanOutput = scanOutput.slice(-80);
  };
  scanProcess.stdout.on("data", collect);
  scanProcess.stderr.on("data", collect);
  scanProcess.on("exit", (code) => {
    scanOutput.push(`Scan finished with code ${code ?? "unknown"}`);
    scanProcess = null;
  });
  return true;
}

const server = createServer(async (req, res) => {
  if (req.method === "OPTIONS") return send(res, 204, "");
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (req.method === "GET" && url.pathname === "/api/state") {
    if (!existsSync(STATE_PATH)) {
      return send(res, 404, { error: "No scan exists yet", scanning: Boolean(scanProcess) });
    }
    return send(res, 200, readFileSync(STATE_PATH, "utf8"));
  }

  if (req.method === "GET" && url.pathname === "/api/status") {
    return send(res, 200, {
      scanning: Boolean(scanProcess),
      startedAt: scanStartedAt,
      output: scanOutput,
      hasState: existsSync(STATE_PATH),
    });
  }

  if (req.method === "GET" && url.pathname === "/api/feedback") {
    if (!existsSync(FEEDBACK_PATH)) {
      return send(res, 404, { error: "Feedback data has not been prepared." });
    }
    return send(res, 200, readFileSync(FEEDBACK_PATH, "utf8"));
  }

  if (req.method === "POST" && url.pathname === "/api/feedback/update") {
    try {
      const body = await readBody(req);
      validateFeedbackUpdate(body);
      const feedback = readFeedback();
      const records =
        body.kind === "note"
          ? feedback.notes
          : body.kind === "general"
            ? feedback.generalNotes || []
            : body.kind === "edit"
              ? feedback.editNotes || []
            : feedback.parents;
      const record = records.find((item) => item.id === body.id);
      if (!record) {
        return send(res, 404, { error: "Feedback record not found." });
      }

      if (body.kind === "note" && body.parentIds !== undefined) {
        const parentIds = [...new Set(body.parentIds)];
        const validParentIds = new Set(
          feedback.parents.map((parent) => parent.id),
        );
        const invalidParentIds = parentIds.filter(
          (parentId) => !validParentIds.has(parentId),
        );
        if (invalidParentIds.length) {
          return send(res, 400, {
            error: `Unknown feedback parent: ${invalidParentIds.join(", ")}`,
          });
        }
        record.parentIds = parentIds;
      }

      const state = JSON.parse(readFileSync(STATE_PATH, "utf8"));
      const registry = JSON.parse(readFileSync(SHOT_REGISTRY_PATH, "utf8"));
      const validShotIds = new Set(
        registry.shots.map((shot) => shot.shotId),
      );
      const activeShotIds = new Set(state.cuts.map((cut) => cut.shotId));
      const shotIds = [...new Set(body.shotIds)];
      const invalidShotIds = shotIds.filter(
        (shotId) => !validShotIds.has(shotId),
      );
      if (invalidShotIds.length) {
        return send(res, 400, {
          error: `Unknown shot assignment: ${invalidShotIds.join(", ")}`,
        });
      }

      record.noteDescription = body.noteDescription;
      record.dependency = body.dependency;
      record.shotIds = shotIds;
      record.retiredShotIds = shotIds.filter(
        (shotId) => !activeShotIds.has(shotId),
      );
      if (body.kind !== "parent" && typeof body.title === "string") {
        record.title = body.title.trim();
      }
      if (body.kind === "edit" && typeof body.status === "string") {
        record.status = body.status;
      }
      feedback.updatedAt = new Date().toISOString();
      writeFeedback(feedback);
      return send(res, 200, { ok: true, feedback, record });
    } catch (error) {
      return send(res, 400, {
        error: error instanceof Error ? error.message : "Unable to save feedback.",
      });
    }
  }

  if (req.method === "POST" && url.pathname === "/api/rescan") {
    const body = await readBody(req).catch(() => ({}));
    const started = startScan(Boolean(body.quick));
    return send(res, started ? 202 : 409, {
      started,
      message: started ? "Read-only scan started" : "A scan is already running",
    });
  }

  if (req.method === "POST" && url.pathname === "/api/reveal") {
    const body = await readBody(req);
    if (!body.path || !existsSync(body.path)) {
      return send(res, 404, { error: "Path is missing or unavailable" });
    }
    const directory = statSync(body.path).isDirectory()
      ? body.path
      : dirname(body.path);
    spawn("open", ["-R", body.path], { detached: true, stdio: "ignore" }).unref();
    const clipboardValue = body.copyPath
      ? body.path
      : body.copyDirectory
        ? directory
        : "";
    if (clipboardValue) {
      try {
        await copyToClipboard(clipboardValue);
      } catch {
        return send(res, 500, {
          error: "Finder opened, but the requested path could not be copied",
        });
      }
    }
    return send(res, 200, {
      ok: true,
      directory: body.copyDirectory ? directory : undefined,
      path: body.copyPath ? body.path : undefined,
    });
  }

  if (req.method === "POST" && url.pathname === "/api/open") {
    const body = await readBody(req);
    if (!body.path || !existsSync(body.path)) {
      return send(res, 404, { error: "Path is missing or unavailable" });
    }
    const app = appForKind[body.kind];
    const args = app ? ["-a", app, body.path] : [body.path];
    spawn("open", args, { detached: true, stdio: "ignore" }).unref();
    return send(res, 200, { ok: true, app: app || "default" });
  }

  if (req.method === "GET" && url.pathname.startsWith("/archive/")) {
    const path = safeArchivePath(url.pathname);
    if (!path || !existsSync(path) || !statSync(path).isFile()) {
      return send(res, 404, "Not found", "text/plain");
    }
    const type = {
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".png": "image/png",
      ".webp": "image/webp",
      ".json": "application/json",
    }[extname(path).toLowerCase()] || "application/octet-stream";
    res.writeHead(200, {
      "Content-Type": type,
      "Cache-Control": "no-store",
      "Access-Control-Allow-Origin": "http://localhost:3497",
    });
    return createReadStream(path).pipe(res);
  }

  return send(res, 404, { error: "Unknown endpoint" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`Paracosm archive API: http://127.0.0.1:${PORT}`);
  if (!existsSync(STATE_PATH)) startScan(false);
});
