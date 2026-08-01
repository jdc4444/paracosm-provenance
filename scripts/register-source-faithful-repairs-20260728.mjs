import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const versionsPath = path.join(root, "data/object-3d-versions.json");
const notesPath = path.join(root, "data/object-production-notes.json");
const manifestPath = path.join(
  root,
  "data/source-faithful-object-repairs-20260728.json",
);

const versionsDocument = JSON.parse(fs.readFileSync(versionsPath, "utf8"));
const notesDocument = JSON.parse(fs.readFileSync(notesPath, "utf8"));
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

const parseGlbStats = (filePath) => {
  const buffer = fs.readFileSync(filePath);
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

const versionSpecs = [
  {
    objectId: "cafe-model",
    id: "blender-source-artwork-v3",
    label: "Source artwork v3",
    model: "/archive/objects/3d/cafe-model-v3.glb",
    thumbnail: "/archive/objects/3d/cafe-model-v3.png",
    taskId: "local:blender:cafe-source-artwork-v3",
    status: "ready",
    note: "Source-faithful repair using image crops from the original catalog object for the PARACOSM TEA DREAM fascia, OPEN plaque, and Coffee sidewalk board. No substitute type was used.",
  },
  {
    objectId: "ice-cream-shop",
    id: "blender-source-artwork-v3",
    label: "Source artwork v3",
    model: "/archive/objects/3d/ice-cream-shop-v3.glb",
    thumbnail: "/archive/objects/3d/ice-cream-shop-v3.png",
    taskId: "local:blender:ice-cream-source-artwork-v3",
    status: "ready",
    note: "Source-faithful repair using image crops from the original catalog object for the fascia illustration, date plaque, door plaque, and both window signs. No substitute type was used.",
  },
];

for (const [objectId, rejectedVersionId] of [
  ["burgundy-button-corset", "blender-true-hollow-v3"],
  ["navy-corset-vest", "blender-true-hollow-v2"],
]) {
  const entry = versionsDocument.objects.find(
    (candidate) => candidate.objectId === objectId,
  );
  if (entry) {
    entry.versions = entry.versions.filter(
      (version) => version.id !== rejectedVersionId,
    );
  }
}

for (const spec of versionSpecs) {
  const entry = versionsDocument.objects.find(
    (candidate) => candidate.objectId === spec.objectId,
  );
  if (!entry) {
    throw new Error(`Missing 3D registry object: ${spec.objectId}`);
  }
  const repairResult = [...manifest.shops, ...manifest.corsets].find(
    (candidate) => candidate.objectId === spec.objectId,
  );
  if (!repairResult) {
    throw new Error(`Missing repair manifest result: ${spec.objectId}`);
  }
  const modelPath = path.join(root, "public", spec.model.replace(/^\//, ""));
  const thumbnailPath = path.join(
    root,
    "public",
    spec.thumbnail.replace(/^\//, ""),
  );
  if (!fs.existsSync(modelPath) || !fs.existsSync(thumbnailPath)) {
    throw new Error(`Missing repaired assets for ${spec.objectId}`);
  }
  const stats = parseGlbStats(modelPath);
  const nextVersion = {
    ...spec,
    provider: "Blender 4.5",
    createdAt: "2026-07-28",
    faces: repairResult.faces || stats.faces,
    vertices: repairResult.vertices || stats.vertices,
  };
  const existingIndex = entry.versions.findIndex(
    (version) => version.id === spec.id,
  );
  if (existingIndex >= 0) {
    entry.versions[existingIndex] = nextVersion;
  } else {
    entry.versions.push(nextVersion);
  }
}

const noteUpdates = new Map([
  [
    "cafe-model",
    {
      id: "replace-generated-lettering",
      title: "Source artwork restored",
      detail:
        "The typed repair was replaced with artwork cropped directly from the catalog object: main fascia, door plaque, and sidewalk board.",
    },
  ],
  [
    "ice-cream-shop",
    {
      id: "replace-generated-lettering",
      title: "Source artwork restored",
      detail:
        "The typed repair was replaced with artwork cropped directly from the catalog object: fascia illustration, date plaque, door plaque, and both window signs.",
    },
  ],
  [
    "burgundy-button-corset",
    {
      id: "open-corset-shell",
      title: "Corset repair deferred",
      detail:
        "The manual clean-geometry pass was rejected and removed from active versions. Existing generated versions remain archived for reference; no replacement is currently approved.",
      status: "tracked",
    },
  ],
  [
    "navy-corset-vest",
    {
      id: "open-corset-shell",
      title: "Corset repair deferred",
      detail:
        "The manual clean-geometry pass was rejected and removed from active versions. Existing generated versions remain archived for reference; no replacement is currently approved.",
      status: "tracked",
    },
  ],
]);

for (const [objectId, update] of noteUpdates) {
  let entry = notesDocument.objects.find(
    (candidate) => candidate.objectId === objectId,
  );
  if (!entry) {
    entry = { objectId, notes: [] };
    notesDocument.objects.push(entry);
  }
  const note = entry.notes.find((candidate) => candidate.id === update.id);
  if (note) {
    Object.assign(note, update, { status: update.status || "complete" });
  } else {
    entry.notes.push({
      ...update,
      kind: "generation-caution",
      status: update.status || "complete",
      relatedObjectIds: [],
      proposedParts: [],
    });
  }
}

fs.writeFileSync(versionsPath, `${JSON.stringify(versionsDocument, null, 2)}\n`);
fs.writeFileSync(notesPath, `${JSON.stringify(notesDocument, null, 2)}\n`);
console.log(
  JSON.stringify(
    {
      registered: versionSpecs.map(({ objectId, id }) => ({ objectId, id })),
      updatedNotes: [...noteUpdates.keys()],
    },
    null,
    2,
  ),
);
