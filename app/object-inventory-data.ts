import objectInventoryData from "../data/object-inventory.json";
import wardrobeHollowMultiviewData from "../data/wardrobe-hollow-multiview-20260728.json";
import type { ObjectItem } from "./object-asset-inspector";

type GeneratedObjectGroup = {
  id: string;
  category: string;
  imageDirectory: string;
  alternateImageDirectories?: Array<{
    id: string;
    label: string;
    directory: string;
    description?: string;
  }>;
  sourceFiles?: string[];
  objects: Array<
    Pick<ObjectItem, "id" | "name"> & {
      image?: string;
      sourceFiles?: string[];
      alternateImages?: ObjectItem["alternateImages"];
    }
  >;
};

type ObjectInventorySourceManifest = {
  schemaVersion: number;
  updatedAt: string;
  sourceFolder: string;
  objects: ObjectItem[];
  generatedGroups: GeneratedObjectGroup[];
};

type WardrobeHollowMultiviewManifest = {
  objects: Array<{
    objectId: string;
    assets: {
      multiview: string;
      top: string;
      side: string;
      bottom: string;
    };
  }>;
};

const sourceManifest = objectInventoryData as ObjectInventorySourceManifest;
const hollowMultiviewManifest =
  wardrobeHollowMultiviewData as WardrobeHollowMultiviewManifest;
const hollowMultiviewByObjectId = new Map(
  hollowMultiviewManifest.objects.map((item) => [
    item.objectId,
    [
      {
        id: "hollow-top-3d-input",
        label: "Hollow top view",
        image: item.assets.top,
        description:
          "Overhead angle showing the garment opening and interior volume.",
      },
      {
        id: "hollow-side-3d-input",
        label: "Hollow side view",
        image: item.assets.side,
        description:
          "Side angle preserving the garment silhouette and depth.",
      },
      {
        id: "hollow-bottom-3d-input",
        label: "Hollow underside view",
        image: item.assets.bottom,
        description:
          "Underside angle showing hem, cuff, sole, or base construction.",
      },
    ] satisfies NonNullable<ObjectItem["alternateImages"]>,
  ]),
);

export const objectInventoryManifest = {
  schemaVersion: sourceManifest.schemaVersion,
  updatedAt: sourceManifest.updatedAt,
  sourceFolder: sourceManifest.sourceFolder,
  objects: [
    ...sourceManifest.objects,
    ...sourceManifest.generatedGroups.flatMap((group) =>
      group.objects.map((item) => ({
        ...item,
        category: group.category,
        image: item.image || `${group.imageDirectory}/${item.id}.png`,
        sourceFiles: item.sourceFiles || group.sourceFiles || [],
        alternateImages: [
          ...(item.alternateImages || []),
          ...(group.alternateImageDirectories || []).map((alternate) => ({
            id: alternate.id,
            label: alternate.label,
            image: `${alternate.directory}/${item.id}.png`,
            description: alternate.description,
          })),
          ...(hollowMultiviewByObjectId.get(item.id) || []),
        ],
      })),
    ),
  ],
};
