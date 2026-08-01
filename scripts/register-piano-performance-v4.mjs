import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const versionsPath = path.join(root, "data/object-3d-versions.json");
const notesPath = path.join(root, "data/object-production-notes.json");
const performancePath = path.join(root, "data/piano-performance-vid5.json");
const modelPath = path.join(root, "public/archive/objects/3d/piano-v4.glb");
const thumbnailPath = path.join(root, "public/archive/objects/3d/piano-v4.png");

function readGlb(filePath) {
  const buffer = fs.readFileSync(filePath);
  if (buffer.toString("utf8", 0, 4) !== "glTF") {
    throw new Error(`${path.basename(filePath)} is not a GLB.`);
  }
  const jsonChunkLength = buffer.readUInt32LE(12);
  return JSON.parse(
    buffer
      .subarray(20, 20 + jsonChunkLength)
      .toString("utf8")
      .replace(/\u0000+$/g, "")
      .trim(),
  );
}

function modelStats(document) {
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
}

for (const filePath of [performancePath, modelPath, thumbnailPath]) {
  if (!fs.existsSync(filePath)) {
    throw new Error(`Missing piano performance asset: ${filePath}`);
  }
}

const performance = JSON.parse(fs.readFileSync(performancePath, "utf8"));
const document = readGlb(modelPath);
const animation = document.animations?.find(
  (item) => item.name === "VID_5 Performance",
);
if (!animation || animation.channels.length !== performance.summary.distinctKeys) {
  throw new Error("The piano performance animation is incomplete.");
}

const stats = modelStats(document);
const manifest = JSON.parse(fs.readFileSync(versionsPath, "utf8"));
const record = manifest.objects.find((item) => item.objectId === "piano");
if (!record) throw new Error("Missing piano 3D registry record.");

const version = {
  id: "blender-performance-v4",
  label: "VID_5 performance rig v4",
  provider: "Blender 4.5",
  model: "/archive/objects/3d/piano-v4.glb",
  thumbnail: "/archive/objects/3d/piano-v4.png",
  createdAt: "2026-07-28",
  taskId: "local:blender:piano-vid5-performance-v4",
  faces: stats.faces,
  vertices: stats.vertices,
  status: "ready",
  note:
    "The fitted 88-key keyboard now includes the reviewed VID_5 performance as a native glTF animation. Eight waveform-confirmed chord attacks drive 14 named MIDI keys with restrained acoustic key travel and clean sustains.",
};
const versionIndex = record.versions.findIndex((item) => item.id === version.id);
if (versionIndex >= 0) record.versions[versionIndex] = version;
else record.versions.push(version);

const notesManifest = JSON.parse(fs.readFileSync(notesPath, "utf8"));
const noteRecord = notesManifest.objects.find(
  (item) => item.objectId === "piano",
);
if (!noteRecord) throw new Error("Missing piano production-note record.");
const productionNote = {
  id: "vid5-performance",
  kind: "generation-caution",
  status: "complete",
  title: "VID_5 chord performance mapped and animated",
  detail:
    "The waveform contains eight strong attacks: E, D, E, A, then E, D, E, A. Pitch-detector retriggers were discarded, the chord shapes were checked against the frames, and each voicing now moves once and sustains cleanly.",
  relatedObjectIds: [],
  proposedParts: [
    "8 waveform-confirmed chord attacks",
    "14 animated key objects",
    "E–D–A progression in A major",
    "Optional browser confirmation synth",
  ],
};
const noteIndex = noteRecord.notes.findIndex(
  (item) => item.id === productionNote.id,
);
if (noteIndex >= 0) noteRecord.notes[noteIndex] = productionNote;
else noteRecord.notes.push(productionNote);

fs.writeFileSync(versionsPath, `${JSON.stringify(manifest, null, 2)}\n`);
fs.writeFileSync(notesPath, `${JSON.stringify(notesManifest, null, 2)}\n`);
console.log(JSON.stringify({ version, animation: animation.name }, null, 2));
