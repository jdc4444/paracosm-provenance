/** Cloudflare Worker entry point for the vinext-starter template. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";
import initialFeedbackData from "../data/feedback.json";
import shotRegistryData from "../data/canonical/shot-registry.json";

interface Env {
  ASSETS: Fetcher;
  DB: D1Database;
  MEDIA: R2Bucket;
  MEDIA_UPLOAD_TOKEN?: string;
  IMAGES: {
    input(stream: ReadableStream): {
      transform(options: Record<string, unknown>): {
        output(options: { format: string; quality: number }): Promise<{ response(): Response }>;
      };
    };
  };
}

type UploadedPart = {
  etag: string;
  partNumber: number;
};

const MEDIA_PREFIX = "/archive/";
const MEDIA_API_PREFIX = "/api/media/";
const FEEDBACK_KEY = "site-state/feedback.json";

type FeedbackRecord = {
  id: string;
  title?: string;
  name?: string;
  noteDescription: string;
  dependency: string;
  parentIds?: string[];
  shotIds: string[];
  retiredShotIds?: string[];
  status?: string;
};

type FeedbackData = {
  updatedAt: string;
  parents: FeedbackRecord[];
  notes: FeedbackRecord[];
  generalNotes: FeedbackRecord[];
  editNotes: FeedbackRecord[];
  [key: string]: unknown;
};

type FeedbackUpdate = {
  kind?: string;
  id?: string;
  title?: string;
  noteDescription?: string;
  dependency?: string;
  parentIds?: string[];
  shotIds?: string[];
  status?: string;
};

const initialFeedback = initialFeedbackData as FeedbackData;
const validShotIds = new Set(
  (shotRegistryData.shots as Array<{ shotId: string }>).map(
    (shot) => shot.shotId,
  ),
);
const activeShotIds = new Set(
  (shotRegistryData.shots as Array<{ shotId: string; active?: boolean }>)
    .filter((shot) => shot.active)
    .map((shot) => shot.shotId),
);

function mediaKey(pathname: string, prefix: string): string | null {
  let key: string;
  try {
    key = decodeURIComponent(pathname.slice(prefix.length));
  } catch {
    return null;
  }

  if (
    !key ||
    key.startsWith("/") ||
    key.split("/").some((segment) => segment === "..")
  ) {
    return null;
  }
  return prefix === MEDIA_PREFIX ? `archive/${key}` : `archive/${key}`;
}

function uploadAuthorized(request: Request, env: Env): boolean {
  const expected = env.MEDIA_UPLOAD_TOKEN;
  return Boolean(
    expected &&
      request.headers.get("x-paracosm-upload-key") === expected,
  );
}

function jsonResponse(value: unknown, status = 200): Response {
  return Response.json(value, {
    status,
    headers: { "cache-control": "no-store" },
  });
}

function feedbackRecordsForKind(feedback: FeedbackData, kind: string) {
  if (kind === "note") return feedback.notes;
  if (kind === "general") return feedback.generalNotes;
  if (kind === "edit") return feedback.editNotes;
  return feedback.parents;
}

function validateFeedbackUpdate(body: FeedbackUpdate) {
  if (!body.kind || !["note", "parent", "general", "edit"].includes(body.kind)) {
    throw new Error("A valid feedback record kind is required.");
  }
  if (!body.id) throw new Error("A feedback record id is required.");
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
    (!body.title.trim() || body.title.length > 300)
  ) {
    throw new Error("Note must have a name under 300 characters.");
  }
  if (
    !Array.isArray(body.shotIds) ||
    body.shotIds.some((shotId) => !validShotIds.has(shotId))
  ) {
    throw new Error("Shot assignments must use known stable shot ids.");
  }
  if (
    body.parentIds !== undefined &&
    (body.kind !== "note" ||
      !body.parentIds.length ||
      body.parentIds.some((parentId) => !parentId))
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

async function readHostedFeedback(env: Env): Promise<FeedbackData> {
  const stored = await env.MEDIA.get(FEEDBACK_KEY);
  if (!stored) return structuredClone(initialFeedback);
  return stored.json<FeedbackData>();
}

async function handleFeedback(request: Request, env: Env): Promise<Response> {
  if (request.method === "GET") {
    return jsonResponse(await readHostedFeedback(env));
  }
  if (request.method !== "POST") {
    return new Response("Method Not Allowed", {
      status: 405,
      headers: { Allow: "GET, POST" },
    });
  }

  try {
    const body = (await request.json()) as FeedbackUpdate;
    validateFeedbackUpdate(body);
    const feedback = await readHostedFeedback(env);
    const records = feedbackRecordsForKind(feedback, body.kind!);
    const record = records.find((item) => item.id === body.id);
    if (!record) return jsonResponse({ error: "Feedback record not found." }, 404);

    if (body.kind === "note" && body.parentIds !== undefined) {
      const parentIds = [...new Set(body.parentIds)];
      const knownParents = new Set(feedback.parents.map((parent) => parent.id));
      const invalidParent = parentIds.find((parentId) => !knownParents.has(parentId));
      if (invalidParent) {
        return jsonResponse({ error: `Unknown feedback parent: ${invalidParent}` }, 400);
      }
      record.parentIds = parentIds;
    }

    const shotIds = [...new Set(body.shotIds!)];
    record.noteDescription = body.noteDescription!;
    record.dependency = body.dependency!;
    record.shotIds = shotIds;
    record.retiredShotIds = shotIds.filter((shotId) => !activeShotIds.has(shotId));
    if (body.kind !== "parent" && typeof body.title === "string") {
      record.title = body.title.trim();
    }
    if (body.kind === "edit" && typeof body.status === "string") {
      record.status = body.status;
    }
    feedback.updatedAt = new Date().toISOString();
    await env.MEDIA.put(FEEDBACK_KEY, JSON.stringify(feedback), {
      httpMetadata: {
        contentType: "application/json; charset=utf-8",
        cacheControl: "no-store",
      },
    });
    return jsonResponse({ ok: true, feedback, record });
  } catch (error) {
    return jsonResponse(
      { error: error instanceof Error ? error.message : "Unable to save feedback." },
      400,
    );
  }
}

async function handleMediaUpload(request: Request, env: Env): Promise<Response> {
  if (!uploadAuthorized(request, env)) {
    return new Response("Unauthorized", { status: 401 });
  }

  const url = new URL(request.url);
  const key = mediaKey(url.pathname, MEDIA_API_PREFIX);
  const action = url.searchParams.get("action");
  if (!key || !action) {
    return new Response("Missing or invalid media key/action", { status: 400 });
  }

  if (request.method === "HEAD" && action === "head") {
    const object = await env.MEDIA.head(key);
    if (!object) return new Response(null, { status: 404 });
    return new Response(null, {
      headers: {
        "content-length": String(object.size),
        etag: object.httpEtag,
      },
    });
  }

  const contentType =
    url.searchParams.get("contentType") ?? "application/octet-stream";
  const httpMetadata = {
    contentType,
    cacheControl: "public, max-age=31536000, immutable",
  };

  if (request.method === "PUT" && action === "put") {
    if (!request.body) return new Response("Missing body", { status: 400 });
    const object = await env.MEDIA.put(key, request.body, { httpMetadata });
    return jsonResponse({ key: object.key, etag: object.httpEtag });
  }

  if (request.method === "POST" && action === "mpu-create") {
    const upload = await env.MEDIA.createMultipartUpload(key, { httpMetadata });
    return jsonResponse({ key: upload.key, uploadId: upload.uploadId });
  }

  const uploadId = url.searchParams.get("uploadId");
  if (!uploadId) {
    return new Response("Missing uploadId", { status: 400 });
  }
  const upload = env.MEDIA.resumeMultipartUpload(key, uploadId);

  if (request.method === "PUT" && action === "mpu-uploadpart") {
    const partNumber = Number(url.searchParams.get("partNumber"));
    if (!request.body || !Number.isInteger(partNumber) || partNumber < 1) {
      return new Response("Missing body or invalid part number", { status: 400 });
    }
    const part = await upload.uploadPart(partNumber, request.body);
    return jsonResponse(part);
  }

  if (request.method === "POST" && action === "mpu-complete") {
    const body = (await request.json()) as { parts?: UploadedPart[] };
    if (!Array.isArray(body.parts) || body.parts.length === 0) {
      return new Response("Missing uploaded parts", { status: 400 });
    }
    const object = await upload.complete(body.parts);
    return jsonResponse({ key: object.key, etag: object.httpEtag });
  }

  if (request.method === "DELETE" && action === "mpu-abort") {
    await upload.abort();
    return new Response(null, { status: 204 });
  }

  return new Response("Method Not Allowed", {
    status: 405,
    headers: { Allow: "HEAD, PUT, POST, DELETE" },
  });
}

async function serveMedia(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const key = mediaKey(url.pathname, MEDIA_PREFIX);
  if (!key) return new Response("Invalid media key", { status: 400 });

  const object = await env.MEDIA.get(key, {
    onlyIf: request.headers,
    range: request.headers,
  });
  if (!object) {
    return env.ASSETS.fetch(request);
  }

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("accept-ranges", "bytes");
  headers.set(
    "cache-control",
    headers.get("cache-control") ?? "public, max-age=31536000, immutable",
  );

  let status = 200;
  if (request.headers.has("range") && "range" in object && object.range) {
    const { offset, length } = object.range;
    headers.set(
      "content-range",
      `bytes ${offset}-${offset + length - 1}/${object.size}`,
    );
    headers.set("content-length", String(length));
    status = 206;
  }

  return new Response(object.body, { status, headers });
}

interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

// Image security config. SVG sources with .svg extension auto-skip the
// optimization endpoint on the client side (served directly, no proxy).
// To route SVGs through the optimizer (with security headers), set
// dangerouslyAllowSVG: true in next.config.js and uncomment below:
// const imageConfig: ImageConfig = { dangerouslyAllowSVG: true };

const worker = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname.startsWith(MEDIA_API_PREFIX)) {
      return handleMediaUpload(request, env);
    }

    if (url.pathname === "/api/feedback") {
      return handleFeedback(request, env);
    }

    if (url.pathname === "/api/feedback/update") {
      return handleFeedback(request, env);
    }

    if (url.pathname.startsWith(MEDIA_PREFIX)) {
      return serveMedia(request, env);
    }

    if (url.pathname === "/_vinext/image") {
      const allowedWidths = [...DEFAULT_DEVICE_SIZES, ...DEFAULT_IMAGE_SIZES];
      return handleImageOptimization(request, {
        fetchAsset: (path) => env.ASSETS.fetch(new Request(new URL(path, request.url))),
        transformImage: async (body, { width, format, quality }) => {
          const result = await env.IMAGES.input(body).transform(width > 0 ? { width } : {}).output({ format, quality });
          return result.response();
        },
      }, allowedWidths);
    }

    return handler.fetch(request, env, ctx);
  },
};

export default worker;
