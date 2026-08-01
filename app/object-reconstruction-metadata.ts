import reconstructionData from "../data/object-reconstruction-plan.json";

export type ReconstructionMode =
  | "single-image"
  | "multi-image"
  | "assembly-component"
  | "assembly-guide";

export type ReconstructionPriority = "hero" | "standard" | "context";

export type ObjectReconstructionStrategy = {
  id: string;
  objectIds: string[];
  mode: ReconstructionMode;
  priority: ReconstructionPriority;
  summary: string;
  inputSourceFiles: string[];
  relatedObjectIds: string[];
  assemblyIds: string[];
  modelingSteps: string[];
  captureNeeds: string[];
  cautions: string[];
};

export type ReconstructionPlacement = {
  objectId: string;
  window: string;
  level: string;
  order: number;
};

export type ReconstructionAssembly = {
  id: string;
  name: string;
  intent: string;
  sourceFiles: string[];
  componentObjectIds: string[];
  plannedParts: string[];
  relations: string[];
  reconstructionOrder: string[];
  placements?: ReconstructionPlacement[];
};

type ReconstructionManifest = {
  schemaVersion: number;
  updatedAt: string;
  sourceAudit: {
    status: "complete";
    sourceCount: number;
    summary: string;
    sources: Array<{
      sourceFile: string;
      scene: string;
      summary: string;
      objectIds: string[];
      assemblyIds: string[];
    }>;
  };
  defaultAssetStrategy: Omit<
    ObjectReconstructionStrategy,
    "id" | "objectIds" | "inputSourceFiles" | "relatedObjectIds" | "assemblyIds"
  >;
  assetStrategies: ObjectReconstructionStrategy[];
  assemblies: ReconstructionAssembly[];
};

const manifest = reconstructionData as ReconstructionManifest;
const strategyByObjectId = new Map(
  manifest.assetStrategies.flatMap((strategy) =>
    strategy.objectIds.map((objectId) => [objectId, strategy] as const),
  ),
);

export const reconstructionSourceAudit = manifest.sourceAudit;

export function reconstructionStrategyForObject(
  object:
    | {
        id: string;
        sourceFiles: string[];
      }
    | null
    | undefined,
): ObjectReconstructionStrategy | null {
  if (!object) return null;
  const strategy = strategyByObjectId.get(object.id);
  if (strategy) return strategy;
  return {
    id: `default-${object.id}`,
    objectIds: [object.id],
    inputSourceFiles: object.sourceFiles,
    relatedObjectIds: [],
    assemblyIds: [],
    ...manifest.defaultAssetStrategy,
  };
}

export function reconstructionAssembliesForObject(
  objectId: string | null | undefined,
) {
  if (!objectId) return [];
  return manifest.assemblies.filter(
    (assembly) =>
      assembly.id === objectId ||
      assembly.componentObjectIds.includes(objectId),
  );
}

export function reconstructionModeLabel(mode: ReconstructionMode) {
  if (mode === "multi-image") return "Multi-image";
  if (mode === "assembly-component") return "Assembly component";
  if (mode === "assembly-guide") return "Assembly guide";
  return "Single image";
}

export function reconstructionPriorityLabel(
  priority: ReconstructionPriority,
) {
  if (priority === "hero") return "Hero";
  if (priority === "context") return "Context";
  return "Standard";
}
