import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const inventory = JSON.parse(
  await fs.readFile(
    path.join(repositoryRoot, "data/object-inventory.json"),
    "utf8",
  ),
);
const outputPath = path.join(
  repositoryRoot,
  "data/wardrobe-cloth-simulation-plan-20260728.json",
);

const footwearIds = new Set([
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
]);
const excludedIds = new Set([
  ...footwearIds,
  "silver-over-ear-headphones",
]);

const rigidAdornmentIds = new Set([
  "blue-jeweled-headpiece",
  "crystal-tiara",
]);
const corsetIds = new Set([
  "burgundy-button-corset",
  "ivory-striped-corset",
  "pink-striped-corset",
  "red-corset-top",
  "teal-sculpted-corset",
  "navy-corset-vest",
]);
const corsetDressIds = new Set([
  "champagne-ruffle-corset-dress",
  "gray-bustle-dress",
  "silver-puff-sleeve-dress",
  "white-lilac-corset-dress",
  "navy-pinstripe-ruffle-dress",
]);
const sheerIds = new Set([
  "black-lace-crop-top",
  "orange-sheer-shoulder-cape",
  "burgundy-sheer-column-dress",
  "black-sheer-striped-top",
  "multicolor-mesh-top",
  "black-sheer-ruffle-blouse",
  "red-crochet-tights",
]);
const stretchIds = new Set([
  "gray-opera-gloves",
  "pink-ruffle-trousers",
  "cream-cargo-trousers",
  "pink-tie-dye-tights",
  "black-culottes",
  "red-ribbed-tights",
  "purple-plaid-tights",
  "star-knee-socks",
  "geometric-striped-tights",
  "striped-long-sleeve-bodysuit",
]);
const knitIds = new Set([
  "argyle-high-neck-top",
  "lime-open-knit-scarf",
  "olive-crochet-bag",
  "pink-striped-shag-sweater",
  "multicolor-ribbed-top",
  "green-knit-mini-skirt",
  "blue-striped-fuzzy-sweater",
  "striped-short-sleeve-top",
  "white-fluffy-earmuffs",
]);
const satinIds = new Set([
  "brown-satin-bow-blouse",
  "bronze-abstract-gown",
  "black-bow-bubble-skirt",
  "navy-bubble-skirt",
  "burgundy-orange-circle-dress",
  "black-tie-strap-crop-top",
]);
const ruffleIds = new Set([
  "pink-tiered-mini-skirt",
  "purple-ruffle-skirt",
  "black-tiered-tulle-skirt",
  "pink-ruffle-top",
  "pink-ruffle-mini-skirt",
  "red-tiered-maxi-skirt",
  "blue-polka-dot-blouse",
]);
const crispIds = new Set([
  "ivory-pleated-skirt",
  "navy-taffeta-dress",
  "purple-pleated-skirt",
  "teal-pleated-skirt",
  "navy-striped-velvet-skirt",
]);
const tailoredIds = new Set([
  "black-deconstructed-coat-dress",
  "mustard-military-jacket",
  "pale-blue-brocade-jacket",
  "red-shaggy-coat",
  "gray-technical-jacket",
  "olive-cropped-military-jacket",
  "tartan-coat-dress",
  "burgundy-cape-keyhole-top",
]);

const materialClassFor = (objectId) => {
  if (rigidAdornmentIds.has(objectId)) return "rigid-adornment";
  if (corsetIds.has(objectId)) return "rigid-corsetry";
  if (corsetDressIds.has(objectId)) return "structured-ruffle";
  if (sheerIds.has(objectId)) return "sheer-lightweight";
  if (stretchIds.has(objectId)) return "stretch-jersey";
  if (knitIds.has(objectId)) return "knit-fuzzy";
  if (satinIds.has(objectId)) return "satin-fluid";
  if (ruffleIds.has(objectId)) return "tulle-ruffle";
  if (crispIds.has(objectId)) return "crisp-woven";
  if (tailoredIds.has(objectId)) return "tailored-heavy";
  if (objectId === "red-beret") return "felt-structured";
  throw new Error(`No cloth material class assigned to ${objectId}.`);
};

const structureModeFor = (objectId, materialClass) => {
  if (
    materialClass === "rigid-adornment" ||
    materialClass === "felt-structured" ||
    materialClass === "rigid-corsetry"
  ) {
    return "uniform-structured";
  }
  if (materialClass === "structured-ruffle") return "structured-bodice";
  if (
    /skirt/.test(objectId) ||
    /trousers|culottes|tights|socks/.test(objectId)
  ) {
    return "structured-waistband";
  }
  if (/dress|gown|coat/.test(objectId)) return "structured-upper";
  if (/gloves/.test(objectId)) return "structured-cuff";
  if (/bag|earmuffs/.test(objectId)) return "structured-accessory";
  return "structured-collar";
};

const wardrobeObjects = inventory.generatedGroups
  .filter((group) => group.category === "Wardrobe")
  .flatMap((group) =>
    group.objects.map((object) => ({
      objectId: object.id,
      name: object.name,
      inventoryGroupId: group.id,
    })),
  );
const eligibleObjects = wardrobeObjects
  .filter((object) => !excludedIds.has(object.objectId))
  .map((object) => {
    const materialClass = materialClassFor(object.objectId);
    return {
      ...object,
      sourceModel: `/archive/objects/3d/${object.objectId}-v1.glb`,
      materialClass,
      structureMode: structureModeFor(object.objectId, materialClass),
      existingSimulation:
        object.objectId === "red-corset-top"
          ? "blender-cloth-sphere-v2"
          : null,
    };
  });

const manifest = {
  schemaVersion: 1,
  createdAt: "2026-07-28",
  purpose:
    "Material- and construction-aware Blender cloth simulations for Wardrobe assets.",
  target: {
    collisionObject: "Invisible sphere",
    background: "White studio",
    settledFrame: 48,
    loop: "Forward and reverse",
  },
  scope: {
    wardrobeObjects: wardrobeObjects.length,
    eligibleObjects: eligibleObjects.length,
    newSimulations: eligibleObjects.filter(
      (object) => !object.existingSimulation,
    ).length,
    excludedObjects: wardrobeObjects
      .filter((object) => excludedIds.has(object.objectId))
      .map((object) => ({
        objectId: object.objectId,
        reason:
          object.objectId === "silver-over-ear-headphones"
            ? "Headphones excluded by request."
            : "Footwear excluded by request.",
      })),
  },
  materialClasses: {
    "rigid-adornment":
      "Very high bending and structural stiffness; jewelry and rigid head structures retain construction.",
    "rigid-corsetry":
      "High structural stiffness and damping; boned panels resist collapse.",
    "structured-ruffle":
      "Stiff bodice region with lighter skirt, gathered, and ruffle response.",
    "sheer-lightweight":
      "Low mass and bending resistance with gentle air damping.",
    "stretch-jersey":
      "Low bending resistance with moderate tension recovery for fitted pieces.",
    "knit-fuzzy":
      "Moderate stretch, higher damping, and soft rounded folding.",
    "satin-fluid":
      "Low bending stiffness, low friction, and fluid heavy folds.",
    "tulle-ruffle":
      "Light mass, low bend resistance, and enough air damping to preserve layered volume.",
    "crisp-woven":
      "Moderate-high bend resistance for pleats, taffeta, and velvet structure.",
    "tailored-heavy":
      "Higher mass and structured upper panels for coats and jackets.",
    "felt-structured":
      "Uniform medium-high bending stiffness for molded felt headwear.",
  },
  objects: eligibleObjects,
};

await fs.writeFile(outputPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(
  `Planned ${manifest.scope.newSimulations} new cloth solves across ${manifest.scope.eligibleObjects} eligible Wardrobe objects.`,
);
