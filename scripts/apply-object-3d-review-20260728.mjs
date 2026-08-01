import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const versionsPath = path.join(repositoryRoot, "data/object-3d-versions.json");
const productionNotesPath = path.join(
  repositoryRoot,
  "data/object-production-notes.json",
);

const footwearIds = [
  "black-lace-up-platform-boots",
  "red-knee-boots",
  "brown-lace-up-boots",
  "white-mega-platform-sneakers",
  "lavender-check-fuzzy-shoes",
  "green-platform-sneakers",
  "pink-lace-up-boots",
  "black-mary-jane-flats",
  "black-mary-jane-wedges",
  "black-knee-boots",
];

const versionReviews = new Map([
  [
    "piano",
    {
      status: "needs-fix",
      note: "The wood body is usable, but the generated keyboard is not. Rebuild the white and black keys as clean repeated geometry in Blender or Cinema 4D; keep this mesh for the piano case.",
    },
  ],
  [
    "cafe-model",
    {
      status: "needs-fix",
      note: "The miniature structure is usable, but the generated sign lettering is not. Replace every visible word with editable text geometry or a clean decal in the 3D scene.",
    },
  ],
  [
    "green-wall-plate",
    {
      status: "needs-fix",
      note: "Meshy did not resolve this as a wall plate. Rebuild it as simple plate geometry in the 3D program, use the orange plate for scale and profile, and project the original artwork as a texture.",
    },
  ],
  [
    "lavender-wall-plate",
    {
      status: "needs-fix",
      note: "Meshy did not resolve this as a usable wall plate. Rebuild it as simple plate geometry in the 3D program, use the orange plate for scale and profile, and project the original artwork as a texture.",
    },
  ],
  [
    "orange-wall-plate",
    {
      status: "ready",
      note: "Accepted plate result. Preserve it as the scale and profile reference for rebuilding the green, lavender, and purple wall plates.",
    },
  ],
  [
    "purple-wall-plate",
    {
      status: "needs-fix",
      note: "Meshy did not resolve this as a usable wall plate. Rebuild it as simple plate geometry in the 3D program, use the orange plate for scale and profile, and project the original artwork as a texture.",
    },
  ],
  [
    "burgundy-button-corset",
    {
      status: "needs-fix",
      note: "The generated center and interior are incorrectly solid. Convert the garment to a hollow open shell in the 3D program, using the ivory and pink corsets as topology references.",
    },
  ],
  [
    "teal-sculpted-corset",
    {
      status: "needs-fix",
      note: "The generated center and interior are incorrectly solid. Convert the garment to a hollow open shell in the 3D program, using the ivory and pink corsets as topology references.",
    },
  ],
  ...footwearIds.map((objectId) => [
    objectId,
    {
      status: "needs-fix",
      note: "The pair geometry is usable, but animation needs separate left and right models. Split and center the two shoes in Blender or Cinema 4D; keep this pair mesh as the archived source.",
    },
  ]),
]);

versionReviews.set("lavender-check-fuzzy-shoes", {
  status: "needs-fix",
  note: "Split the pair into separate left and right models, then replace the distorted checker and fuzzy trim texture from the clean source image. The base shoe geometry is usable; do not rerun Meshy.",
});
versionReviews.set("black-knee-boots", {
  status: "needs-fix",
  note: "Split the pair into separate left and right models, remove the malformed generated laces, and rebuild the lace or strap detail with clean curves or mesh in the 3D program. Do not rerun Meshy.",
});

const splitNote = (objectId) => ({
  id: "split-shoe-pair",
  kind: "split-review",
  status: "separate-asset",
  title: "Split into individual shoe models",
  detail:
    "Keep the current pair mesh as the archived source. In Blender or Cinema 4D, separate, center, and export the left and right shoes as independent animation assets.",
  relatedObjectIds: [],
  proposedParts: ["Left shoe model", "Right shoe model"],
});

const cleanupNotes = new Map([
  [
    "piano",
    {
      id: "rebuild-keyboard",
      kind: "generation-caution",
      status: "repair-3d",
      title: "Rebuild the piano keys",
      detail:
        "Keep the generated wood case. Replace the keyboard with evenly spaced white keys and correctly grouped raised black keys as editable repeated geometry.",
      relatedObjectIds: [],
      proposedParts: ["White key row", "Black key groups", "Keyboard bed"],
    },
  ],
  [
    "cafe-model",
    {
      id: "replace-generated-lettering",
      kind: "generation-caution",
      status: "repair-3d",
      title: "Replace every generated word",
      detail:
        "The miniature building and materials are useful, but generated lettering is not production-ready. Remove it and add exact editable sign text or decals after the structure is locked.",
      relatedObjectIds: [],
      proposedParts: ["Main fascia lettering", "Door sign", "Sidewalk sign"],
    },
  ],
  [
    "burgundy-button-corset",
    {
      id: "open-corset-shell",
      kind: "generation-caution",
      status: "repair-3d",
      title: "Open the solid corset interior",
      detail:
        "Meshy filled the body opening. Remove the filled center and interior surfaces, then build a hollow garment shell with usable thickness. Match the open construction already present on the ivory and pink corsets.",
      relatedObjectIds: ["ivory-striped-corset", "pink-striped-corset"],
      proposedParts: ["Outer shell", "Open body cavity", "Inner rim thickness"],
    },
  ],
  [
    "teal-sculpted-corset",
    {
      id: "open-corset-shell",
      kind: "generation-caution",
      status: "repair-3d",
      title: "Open the solid corset interior",
      detail:
        "Meshy filled the body opening. Remove the filled center and interior surfaces, then build a hollow garment shell with usable thickness. Match the open construction already present on the ivory and pink corsets.",
      relatedObjectIds: ["ivory-striped-corset", "pink-striped-corset"],
      proposedParts: ["Outer shell", "Open body cavity", "Inner rim thickness"],
    },
  ],
  [
    "lavender-check-fuzzy-shoes",
    {
      id: "repair-check-pattern",
      kind: "generation-caution",
      status: "repair-3d",
      title: "Replace the distorted checker texture",
      detail:
        "The shoe form is usable, but the lavender checker pattern and fuzzy trim need a clean texture pass from the source image after the pair is split.",
      relatedObjectIds: [],
      proposedParts: ["Checker upper material", "Lavender sole", "Fuzzy trim"],
    },
  ],
  [
    "black-knee-boots",
    {
      id: "rebuild-boot-laces",
      kind: "generation-caution",
      status: "repair-3d",
      title: "Remove and rebuild the malformed laces",
      detail:
        "The boot shell is usable. Delete the generated lace or strap artifacts and rebuild the front detail with clean curves or simple mesh after separating the two boots.",
      relatedObjectIds: [],
      proposedParts: ["Clean boot shell", "Lace or strap curves", "Fasteners"],
    },
  ],
]);

for (const objectId of [
  "green-wall-plate",
  "lavender-wall-plate",
  "purple-wall-plate",
]) {
  cleanupNotes.set(objectId, {
    id: "rebuild-as-wall-plate",
    kind: "generation-caution",
    status: "repair-3d",
    title: "Rebuild as plate geometry",
    detail:
      "This Meshy result is not a usable plate. Build a clean shallow plate from simple revolved geometry, match the accepted orange plate profile, and apply this plate's original artwork as a texture.",
    relatedObjectIds: ["orange-wall-plate"],
    proposedParts: ["Plate body", "Shallow rim", "Artwork texture"],
  });
}

const readJson = async (filePath) =>
  JSON.parse(await fs.readFile(filePath, "utf8"));
const writeJson = async (filePath, value) =>
  fs.writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`);

const versions = await readJson(versionsPath);
for (const record of versions.objects) {
  const review = versionReviews.get(record.objectId);
  if (!review) continue;
  const latestVersion = record.versions.at(-1);
  if (!latestVersion) continue;
  latestVersion.status = review.status;
  latestVersion.note = review.note;
}
versions.updatedAt = "2026-07-28";
await writeJson(versionsPath, versions);

const productionNotes = await readJson(productionNotesPath);
const recordsById = new Map(
  productionNotes.objects.map((record) => [record.objectId, record]),
);

const addOrReplaceNote = (objectId, note) => {
  let record = recordsById.get(objectId);
  if (!record) {
    record = { objectId, notes: [] };
    recordsById.set(objectId, record);
    productionNotes.objects.push(record);
  }
  const existingIndex = record.notes.findIndex((item) => item.id === note.id);
  if (existingIndex >= 0) record.notes[existingIndex] = note;
  else record.notes.push(note);
};

for (const objectId of footwearIds) {
  addOrReplaceNote(objectId, splitNote(objectId));
}
for (const [objectId, note] of cleanupNotes) {
  addOrReplaceNote(objectId, note);
}

productionNotes.objects.sort((left, right) =>
  left.objectId.localeCompare(right.objectId),
);
productionNotes.updatedAt = "2026-07-28";
await writeJson(productionNotesPath, productionNotes);

console.log(
  JSON.stringify(
    {
      reviewedVersions: versionReviews.size,
      footwearSplits: footwearIds.length,
      cleanupNotes: cleanupNotes.size,
    },
    null,
    2,
  ),
);
