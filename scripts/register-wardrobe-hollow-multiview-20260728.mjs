import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const inventoryPath = path.join(repositoryRoot, "data/object-inventory.json");
const outputPath = path.join(
  repositoryRoot,
  "data/wardrobe-hollow-multiview-20260728.json",
);
const inputDirectory = path.join(
  repositoryRoot,
  "public/archive/objects/wardrobe/3d-inputs",
);

const inventory = JSON.parse(fs.readFileSync(inventoryPath, "utf8"));
const wardrobeGroups = inventory.generatedGroups.filter(
  (group) => group.category === "Wardrobe",
);
const wardrobeById = new Map(
  wardrobeGroups.flatMap((group) =>
    group.objects.map((object) => [
      object.id,
      {
        ...object,
        groupId: group.id,
      },
    ]),
  ),
);

const objectIds = fs
  .readdirSync(inputDirectory)
  .filter((fileName) => fileName.endsWith("-multiview.png"))
  .map((fileName) => fileName.slice(0, -"-multiview.png".length))
  .sort();

if (objectIds.length !== 55) {
  throw new Error(
    `Expected 55 hollow wardrobe multiview sheets, found ${objectIds.length}.`,
  );
}

const objects = objectIds.map((objectId) => {
  const object = wardrobeById.get(objectId);
  if (!object) {
    throw new Error(`Missing Wardrobe inventory object ${objectId}.`);
  }

  const assets = Object.fromEntries(
    ["multiview", "top", "side", "bottom"].map((view) => {
      const cleanSideFileName = `${objectId}-side-clean.png`;
      const fileName =
        view === "side" &&
        fs.existsSync(path.join(inputDirectory, cleanSideFileName))
          ? cleanSideFileName
          : `${objectId}-${view}.png`;
      const absolutePath = path.join(inputDirectory, fileName);
      if (!fs.existsSync(absolutePath)) {
        throw new Error(`Missing ${view} asset for ${objectId}.`);
      }
      return [
        view,
        `/archive/objects/wardrobe/3d-inputs/${fileName}`,
      ];
    }),
  );

  return {
    objectId,
    name: object.name,
    inventoryGroupId: object.groupId,
    referenceImage: `/archive/objects/wardrobe/${objectId}.png`,
    assets,
    meshyInputOrder: [
      `/archive/objects/wardrobe/${objectId}.png`,
      assets.top,
      assets.side,
      assets.bottom,
    ],
  };
});

const manifest = {
  schemaVersion: 1,
  createdAt: "2026-07-28",
  purpose:
    "Reference-preserving hollow-garment views for Meshy multi-image reconstruction.",
  scope: {
    wardrobeObjects: wardrobeById.size,
    generatedInputSets: objects.length,
    definition:
      "Remaining unmodeled Wardrobe garments and containers whose wearable or functional cavities need explicit geometric evidence.",
    excluded: [
      {
        objectId: "lime-open-knit-scarf",
        reason:
          "Flat open-knit textile with surface apertures but no enclosed wearable cavity.",
      },
    ],
  },
  viewContract: {
    top:
      "Orthographic overhead view showing the upper opening and hollow interior.",
    side: "Orthographic left-side view preserving exact silhouette and depth.",
    bottom:
      "Orthographic underside view showing hem, cuff, sole, or closed-base construction as applicable.",
    preservation:
      "Exact source silhouette, materials, transparency, pattern, trim, openings, and proportions; no wearer or mannequin.",
  },
  objects,
};

fs.writeFileSync(outputPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(
  `Registered ${objects.length} hollow wardrobe multiview input sets in ${path.relative(repositoryRoot, outputPath)}.`,
);
