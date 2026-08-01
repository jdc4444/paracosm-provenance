import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const versionsPath = path.join(repositoryRoot, "data/object-3d-versions.json");
const notesPath = path.join(
  repositoryRoot,
  "data/object-production-notes.json",
);
const inventoryPath = path.join(repositoryRoot, "data/object-inventory.json");
const manifestPath = path.join(
  repositoryRoot,
  "data/blender-object-repairs-20260728.json",
);
const assetDirectory = path.join(
  repositoryRoot,
  "public/archive/objects/3d",
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
const plateIds = [
  "green-wall-plate",
  "lavender-wall-plate",
  "orange-wall-plate",
  "purple-wall-plate",
];

const readJson = async (filePath) =>
  JSON.parse(await fs.readFile(filePath, "utf8"));
const writeJson = async (filePath, value) => {
  const temporaryPath = `${filePath}.${process.pid}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`);
  await fs.rename(temporaryPath, filePath);
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

const versions = await readJson(versionsPath);
const notes = await readJson(notesPath);
const inventory = await readJson(inventoryPath);
const versionsById = new Map(
  versions.objects.map((record) => [record.objectId, record]),
);
const notesById = new Map(
  notes.objects.map((record) => [record.objectId, record]),
);

const upsertVersion = (objectId, version) => {
  const record = versionsById.get(objectId);
  if (!record) throw new Error(`Missing 3D record for ${objectId}.`);
  const existingIndex = record.versions.findIndex(
    (item) => item.id === version.id,
  );
  if (existingIndex >= 0) record.versions[existingIndex] = version;
  else record.versions.push(version);
};

const upsertNote = (objectId, note) => {
  let record = notesById.get(objectId);
  if (!record) {
    record = { objectId, notes: [] };
    notes.objects.push(record);
    notesById.set(objectId, record);
  }
  const existingIndex = record.notes.findIndex((item) => item.id === note.id);
  if (existingIndex >= 0) record.notes[existingIndex] = note;
  else record.notes.push(note);
};

const localVersion = async ({
  objectId,
  id,
  label,
  stem,
  note,
  taskSuffix,
}) => {
  const stats = await parseGlbStats(path.join(assetDirectory, `${stem}.glb`));
  return {
    objectId,
    version: {
      id,
      label,
      provider: "Blender 4.5",
      model: `/archive/objects/3d/${stem}.glb`,
      thumbnail: `/archive/objects/3d/${stem}.png`,
      createdAt: "2026-07-28",
      taskId: `local:blender:${taskSuffix}`,
      faces: stats.faces,
      vertices: stats.vertices,
      status: "ready",
      note,
    },
  };
};

const manualDefinitions = [
  {
    objectId: "piano",
    id: "blender-v2",
    label: "Playable keys v2",
    stem: "piano-v2",
    taskSuffix: "piano-88-key-rebuild-v2",
    note:
      "Production repair with 52 white keys and 36 black keys as 88 separate named mesh nodes. Every key pivots from its back edge and carries its MIDI note for animation.",
    source: "public/archive/objects/3d/source/piano-blender-repair-v2.blend",
  },
  {
    objectId: "cafe-model",
    id: "blender-v2",
    label: "Clean signs v2",
    stem: "cafe-model-v2",
    taskSuffix: "cafe-sign-rebuild-v2",
    note:
      "Production repair with exact PARACOSM, TEA DREAM, OPEN, and COFFEE signage. Editable text remains in the archived Blender source.",
    source:
      "public/archive/objects/3d/source/cafe-model-blender-repair-v2.blend",
  },
  {
    objectId: "ice-cream-shop",
    id: "blender-v2",
    label: "Clean signs v2",
    stem: "ice-cream-shop-v2",
    taskSuffix: "ice-cream-sign-rebuild-v2",
    note:
      "Production repair with exact SUZY'S, ICE CREAM, SINCE 1895, OPEN, and ICE CREAM SHOP signage. Editable text remains in the archived Blender source.",
    source:
      "public/archive/objects/3d/source/ice-cream-shop-blender-repair-v2.blend",
  },
  ...plateIds.map((objectId) => ({
    objectId,
    id: "blender-v2",
    label: "Clean plate v2",
    stem: `${objectId}-v2`,
    taskSuffix: `${objectId}-rebuild-v2`,
    note:
      "Production-ready shallow plate rebuilt as consistent revolved geometry with this object's original artwork projected on the face.",
    source: `public/archive/objects/3d/source/${objectId}-blender-v2.blend`,
  })),
];

const manualRepairs = [];
for (const definition of manualDefinitions) {
  const registered = await localVersion(definition);
  upsertVersion(registered.objectId, registered.version);
  manualRepairs.push({
    objectId: definition.objectId,
    model: `${definition.stem}.glb`,
    thumbnail: `${definition.stem}.png`,
    source: definition.source,
    faces: registered.version.faces,
    vertices: registered.version.vertices,
  });
}

const completedNoteDefinitions = new Map([
  [
    "piano",
    {
      id: "rebuild-keyboard",
      kind: "generation-caution",
      status: "complete",
      title: "Playable 88-key rebuild complete",
      detail:
        "The generated keyboard was covered with a clean 88-key assembly. All 52 white keys and 36 black keys are separate named objects with back-edge pivots and MIDI metadata for animation.",
      relatedObjectIds: [],
      proposedParts: [
        "52 white key objects",
        "36 black key objects",
        "Keyboard bed",
      ],
    },
  ],
  [
    "cafe-model",
    {
      id: "replace-generated-lettering",
      kind: "generation-caution",
      status: "complete",
      title: "Cafe lettering replaced",
      detail:
        "The prominent generated words are covered by exact editable PARACOSM, TEA DREAM, OPEN, and COFFEE sign elements in the Blender repair source.",
      relatedObjectIds: [],
      proposedParts: [
        "Main fascia lettering",
        "Door sign",
        "Sidewalk sign",
      ],
    },
  ],
  [
    "ice-cream-shop",
    {
      id: "replace-generated-lettering",
      kind: "generation-caution",
      status: "complete",
      title: "Ice cream shop lettering replaced",
      detail:
        "The generated words are covered by exact editable SUZY'S, ICE CREAM, SINCE 1895, OPEN, and ICE CREAM SHOP sign elements in the Blender repair source.",
      relatedObjectIds: [],
      proposedParts: ["Main fascia", "Date plaque", "Window signs", "Door sign"],
    },
  ],
]);

for (const objectId of plateIds) {
  completedNoteDefinitions.set(objectId, {
    id: "rebuild-as-wall-plate",
    kind: "generation-caution",
    status: "complete",
    title: "Clean plate geometry complete",
    detail:
      "A consistent shallow plate body and rim were rebuilt in Blender and textured from this plate's original clean artwork.",
    relatedObjectIds: plateIds.filter((item) => item !== objectId),
    proposedParts: ["Plate body", "Shallow rim", "Artwork texture"],
  });
}

const footwearSplits = [];
for (const objectId of footwearIds) {
  versionsById.get(objectId).primaryVersionId = "meshy-v1";
  const outputs = [];
  for (const side of ["left", "right"]) {
    const stem = `${objectId}-v3-${side}`;
    const registered = await localVersion({
      objectId,
      id: `blender-${side}-v3`,
      label: `${side === "left" ? "Left" : "Right"} shoe`,
      stem,
      taskSuffix: `${objectId}-${side}-split-v3`,
      note:
        objectId === "black-knee-boots"
          ? `Independent ${side} boot export. Midline lace or strap artifacts from the pair mesh were removed during the split.`
          : `Independent ${side} shoe export, centered and grounded for animation. The original pair remains preserved as an earlier version.`,
    });
    upsertVersion(objectId, registered.version);
    outputs.push({
      side,
      model: `${stem}.glb`,
      thumbnail: `${stem}.png`,
      faces: registered.version.faces,
      vertices: registered.version.vertices,
    });
  }
  footwearSplits.push({
    objectId,
    source:
      objectId === "lavender-check-fuzzy-shoes"
        ? `${objectId}-v2.glb`
        : `${objectId}-v1.glb`,
    outputs,
  });
  upsertNote(objectId, {
    id: "split-shoe-pair",
    kind: "split-review",
    status: "complete",
    title: "Individual shoe models complete",
    detail:
      "The archived pair mesh is preserved. Separate centered and grounded left and right GLBs are now available as independent 3D versions.",
    relatedObjectIds: [],
    proposedParts: ["Left shoe model", "Right shoe model"],
  });
}

upsertNote("lavender-check-fuzzy-shoes", {
  id: "repair-check-pattern",
  kind: "generation-caution",
  status: "complete",
  title: "Checker and fuzzy trim retextured",
  detail:
    "Meshy retextured the pair from the clean lavender checker reference, and that improved texture is carried into both independent shoe exports.",
  relatedObjectIds: [],
  proposedParts: ["Checker upper material", "Lavender sole", "Fuzzy trim"],
});
upsertNote("black-knee-boots", {
  id: "rebuild-boot-laces",
  kind: "generation-caution",
  status: "complete",
  title: "Malformed midline lace artifacts removed",
  detail:
    "The accidental geometry connecting the pair was discarded during the spatial split. The intended boot straps remain on each independent model.",
  relatedObjectIds: [],
  proposedParts: ["Clean left boot", "Clean right boot", "Intended straps"],
});

for (const objectId of ["burgundy-button-corset", "teal-sculpted-corset"]) {
  upsertNote(objectId, {
    id: "open-corset-shell",
    kind: "generation-caution",
    status: "review",
    title: "Hollow multiview rerun ready",
    detail:
      "Meshy reran this garment from the front catalog image plus a generated three-quarter view that exposes the wearable interior. Review the openings before marking it production-ready.",
    relatedObjectIds: ["ivory-striped-corset", "pink-striped-corset"],
    proposedParts: ["Outer shell", "Open body cavity", "Inner rim thickness"],
  });
}

for (const [objectId, fileName] of [
  [
    "burgundy-button-corset",
    "burgundy-button-corset-three-quarter.png",
  ],
  ["teal-sculpted-corset", "teal-sculpted-corset-three-quarter.png"],
]) {
  const object = inventory.generatedGroups
    .filter((group) => group.category === "Wardrobe")
    .flatMap((group) => group.objects)
    .find((item) => item.id === objectId);
  if (!object) throw new Error(`Missing inventory object ${objectId}.`);
  const alternate = {
    id: "three-quarter-3d-input",
    label: "3D reconstruction angle",
    image: `/archive/objects/wardrobe/3d-inputs/${fileName}`,
    description:
      "Generated three-quarter catalog view exposing the hollow wearable interior for the Meshy multiview rerun.",
  };
  object.alternateImages = [
    ...(object.alternateImages || []).filter(
      (item) => item.id !== alternate.id,
    ),
    alternate,
  ];
}

for (const [objectId, note] of completedNoteDefinitions) {
  upsertNote(objectId, note);
}
versions.updatedAt = "2026-07-28";
notes.updatedAt = "2026-07-28";
notes.objects.sort((left, right) =>
  left.objectId.localeCompare(right.objectId),
);
inventory.updatedAt = "2026-07-28";

const repairManifest = {
  schemaVersion: 1,
  createdAt: "2026-07-28",
  manualRepairs,
  footwearSplits,
  meshyRepairs: [
    {
      objectId: "lavender-check-fuzzy-shoes",
      versionId: "meshy-retexture-v2",
      role: "clean texture source for left and right Blender splits",
    },
    {
      objectId: "burgundy-button-corset",
      versionId: "meshy-multiview-v2",
      role: "hollow-interior multiview rerun",
    },
    {
      objectId: "teal-sculpted-corset",
      versionId: "meshy-multiview-v2",
      role: "hollow-interior multiview rerun",
    },
  ],
};

await Promise.all([
  writeJson(versionsPath, versions),
  writeJson(notesPath, notes),
  writeJson(inventoryPath, inventory),
  writeJson(manifestPath, repairManifest),
]);

console.log(
  JSON.stringify(
    {
      manualRepairs: manualRepairs.length,
      footwearObjects: footwearSplits.length,
      individualShoes: footwearSplits.length * 2,
      totalRegisteredVersions: versions.objects.reduce(
        (total, record) => total + record.versions.length,
        0,
      ),
    },
    null,
    2,
  ),
);
