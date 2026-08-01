import objectProductionData from "../data/object-production-notes.json";

export type ObjectProductionNoteKind =
  | "generation-caution"
  | "relationship"
  | "split-review";

export type ObjectProductionNoteStatus =
  | "tracked"
  | "separate-asset"
  | "repair-3d"
  | "complete"
  | "review";

export type ObjectProductionNote = {
  id: string;
  kind: ObjectProductionNoteKind;
  status: ObjectProductionNoteStatus;
  title: string;
  detail: string;
  relatedObjectIds: string[];
  proposedParts: string[];
};

type ObjectProductionRecord = {
  objectId: string;
  notes: ObjectProductionNote[];
};

type ObjectProductionManifest = {
  schemaVersion: number;
  updatedAt: string;
  objects: ObjectProductionRecord[];
};

const manifest = objectProductionData as ObjectProductionManifest;
const notesByObjectId = new Map(
  manifest.objects.map((record) => [record.objectId, record.notes]),
);

export function productionNotesForObject(objectId: string | undefined) {
  return objectId ? notesByObjectId.get(objectId) || [] : [];
}

export function productionNoteKindLabel(kind: ObjectProductionNoteKind) {
  if (kind === "generation-caution") return "Model caution";
  if (kind === "relationship") return "Relationship";
  return "Split review";
}

export function productionNoteStatusLabel(
  status: ObjectProductionNoteStatus,
) {
  if (status === "separate-asset") return "Separate 3D asset";
  if (status === "repair-3d") return "3D cleanup";
  if (status === "complete") return "Complete";
  if (status === "review") return "Review";
  return "Tracked";
}

export function productionNoteSummary(notes: ObjectProductionNote[]) {
  const activeNotes = notes.filter((note) => note.status !== "complete");
  if (activeNotes.some((note) => note.kind === "split-review")) {
    return "Split review";
  }
  if (activeNotes.some((note) => note.kind === "relationship")) {
    return "Linked asset";
  }
  return activeNotes.length ? "Model caution" : "";
}
