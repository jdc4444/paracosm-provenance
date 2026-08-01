import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const versionsPath = path.join(root, "data/object-3d-versions.json");
const notesPath = path.join(root, "data/object-production-notes.json");
const manifestPath = path.join(root, "data/piano-keyboard-repair-20260728.json");
const modelPath = path.join(root, "public/archive/objects/3d/piano-v3.glb");
const thumbnailPath = path.join(root, "public/archive/objects/3d/piano-v3.png");

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

if (
  !fs.existsSync(manifestPath) ||
  !fs.existsSync(modelPath) ||
  !fs.existsSync(thumbnailPath)
) {
  throw new Error("Piano v3 repair assets are incomplete.");
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
if (manifest.keys !== 88 || manifest.whiteKeys !== 52 || manifest.blackKeys !== 36) {
  throw new Error("Piano v3 does not contain the complete 88-key keyboard.");
}
const stats = parseGlbStats(modelPath);
const versions = JSON.parse(fs.readFileSync(versionsPath, "utf8"));
const record = versions.objects.find((item) => item.objectId === "piano");
if (!record) throw new Error("Missing piano 3D registry record.");

const version = {
  id: "blender-integrated-v3",
  label: "Integrated playable keys v3",
  provider: "Blender 4.5",
  model: "/archive/objects/3d/piano-v3.glb",
  thumbnail: "/archive/objects/3d/piano-v3.png",
  createdAt: "2026-07-28",
  taskId: "local:blender:piano-integrated-keyboard-v3",
  faces: stats.faces,
  vertices: stats.vertices,
  status: "ready",
  note:
    "The malformed generated keyboard was physically removed. A recessed keywell now carries 52 white and 36 black keys fitted between the cheek blocks, with rear pivots seated beneath the fallboard lip.",
};
const existingIndex = record.versions.findIndex((item) => item.id === version.id);
if (existingIndex >= 0) record.versions[existingIndex] = version;
else record.versions.push(version);

const notes = JSON.parse(fs.readFileSync(notesPath, "utf8"));
const noteRecord = notes.objects.find((item) => item.objectId === "piano");
if (!noteRecord) throw new Error("Missing piano production-note record.");
const note = noteRecord.notes.find((item) => item.id === "rebuild-keyboard");
if (!note) throw new Error("Missing piano keyboard production note.");
Object.assign(note, {
  status: "complete",
  title: "Integrated playable keyboard complete",
  detail:
    "The malformed generated keyboard was physically removed rather than covered. The replacement is recessed inside the original case: 52 white keys and 36 shorter black keys sit between new front and rear walnut rails, with rear-edge pivots and MIDI naming preserved.",
  proposedParts: [
    "52 fitted white key objects",
    "36 shorter black key objects",
    "Recessed keywell",
    "Front key slip",
    "Fallboard lip and rear felt",
  ],
});

fs.writeFileSync(versionsPath, `${JSON.stringify(versions, null, 2)}\n`);
fs.writeFileSync(notesPath, `${JSON.stringify(notes, null, 2)}\n`);
console.log(JSON.stringify({ version, manifest }, null, 2));
