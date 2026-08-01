"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent as ReactDragEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import bundledFeedbackData from "../data/feedback.json";
import { RightInspectorPanel } from "./right-inspector-panel";
import { ShotCardDetails } from "./shot-card-details";
import {
  SourceApplicationLinks,
  type SourceApplicationCut,
} from "./source-application-links";

type FeedbackCut = {
  id: string;
  shotId: string;
  shotName: string;
  description: string;
  thumbnail: string;
  scrubProxy?: string | null;
  scrubStart?: number;
  scrubEnd?: number;
  sectionCode: string;
  timecode: string;
  endTimecode: string;
  start: number;
  end: number;
  duration: number;
  isGap?: boolean;
} & Pick<SourceApplicationCut, "lineage" | "c4dVerification">;

type FeedbackParent = {
  id: string;
  name: string;
  tier: string;
  noteDescription: string;
  dependency: string;
  shotIds: string[];
  retiredShotIds?: string[];
  sourceIds: string[];
};

type FeedbackNote = {
  id: string;
  title: string;
  parentIds: string[];
  tier: string;
  noteDescription: string;
  dependency: string;
  shotIds: string[];
  retiredShotIds?: string[];
  sourceIds: string[];
};

type FeedbackGeneralNote = FeedbackNote;

type EditFeedbackStatus =
  | "to-incorporate"
  | "incorporated"
  | "superseded";

type FeedbackEditNote = FeedbackNote & {
  status: EditFeedbackStatus;
  operation: "swap";
};

type SourceRow = {
  id: string;
  values: Record<string, string | number | null>;
};

type FeedbackData = {
  schemaVersion: number;
  updatedAt: string;
  sourceWorkbook: string;
  sourceSheet: string;
  sourceColumns: string[];
  generalNotes: FeedbackGeneralNote[];
  parents: FeedbackParent[];
  notes: FeedbackNote[];
  editNotes: FeedbackEditNote[];
  sourceRows: SourceRow[];
};

type FeedbackRecord =
  | { kind: "parent"; record: FeedbackParent }
  | { kind: "note"; record: FeedbackNote }
  | { kind: "general"; record: FeedbackGeneralNote }
  | { kind: "edit"; record: FeedbackEditNote };

const bundledFeedback = bundledFeedbackData as FeedbackData;

const parentTone: Record<string, string> = {
  "facial-expression": "face",
  "character-motion": "motion",
  hair: "hair",
  environment: "environment",
  camera: "camera",
};

const SHOW_FEEDBACK_SOURCE_APPLICATION_TAGS = false;

function recordKey(record: FeedbackRecord) {
  return `${record.kind}:${record.record.id}`;
}

function recordTitle(record: FeedbackRecord) {
  return record.kind === "parent" ? record.record.name : record.record.title;
}

function editStatusLabel(status: EditFeedbackStatus) {
  return status
    .split("-")
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(" ");
}

function recordBadge(record: FeedbackRecord) {
  return record.kind === "edit"
    ? editStatusLabel(record.record.status)
    : `Tier ${record.record.tier}`;
}

function applyEditFeedbackOrder(
  cuts: FeedbackCut[],
  editNotes: FeedbackEditNote[],
) {
  const ordered = [...cuts];
  for (const note of editNotes) {
    if (
      note.status !== "to-incorporate" ||
      note.operation !== "swap" ||
      note.shotIds.length !== 2
    ) {
      continue;
    }
    const firstIndex = ordered.findIndex(
      (cut) => cut.shotId === note.shotIds[0],
    );
    const secondIndex = ordered.findIndex(
      (cut) => cut.shotId === note.shotIds[1],
    );
    if (firstIndex < 0 || secondIndex < 0) continue;
    [ordered[firstIndex], ordered[secondIndex]] = [
      ordered[secondIndex],
      ordered[firstIndex],
    ];
  }
  return ordered;
}

function splitShotName(value: string) {
  const [first = "", ...rest] = value.trim().split(/\s+/);
  if (/^\d+[A-Z0-9]*$/i.test(first)) {
    return {
      code: first.toUpperCase(),
      name: rest.join(" "),
    };
  }
  return { code: "", name: value };
}

function sourceValue(value: string | number | null) {
  if (value === null || value === "") return "—";
  return String(value);
}

function feedbackRecordForKey(
  feedback: FeedbackData | null,
  key: string,
): FeedbackRecord | null {
  if (!feedback || !key) return null;
  const [kind, id] = key.split(":");
  if (kind === "parent") {
    const record = feedback.parents.find((item) => item.id === id);
    return record ? { kind: "parent", record } : null;
  }
  if (kind === "general") {
    const record = feedback.generalNotes.find((item) => item.id === id);
    return record ? { kind: "general", record } : null;
  }
  if (kind === "edit") {
    const record = feedback.editNotes.find((item) => item.id === id);
    return record ? { kind: "edit", record } : null;
  }
  const record = feedback.notes.find((item) => item.id === id);
  return record ? { kind: "note", record } : null;
}

export function FeedbackTracker({
  cuts,
  apiBase,
  fps,
  hoverProxy,
}: {
  cuts: FeedbackCut[];
  apiBase: string;
  fps: number;
  hoverProxy?: string | null;
}) {
  const [feedback, setFeedback] = useState<FeedbackData | null>(null);
  const [loadError, setLoadError] = useState("");
  const [query, setQuery] = useState("");
  const [section, setSection] = useState("ALL");
  const [feedbackScope, setFeedbackScope] = useState("all");
  const [feedbackNavPinned, setFeedbackNavPinned] = useState(false);
  const [feedbackNavExpanded, setFeedbackNavExpanded] = useState(false);
  const [selectedShotId, setSelectedShotId] = useState(
    cuts[0]?.shotId || "",
  );
  const [expandedNotesShotId, setExpandedNotesShotId] = useState("");
  const [selectedRecordKey, setSelectedRecordKey] = useState("");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [draftDependency, setDraftDependency] = useState("");
  const [draftParentIds, setDraftParentIds] = useState<string[]>([]);
  const [draftShotIds, setDraftShotIds] = useState<string[]>([]);
  const [draftEditStatus, setDraftEditStatus] =
    useState<EditFeedbackStatus>("to-incorporate");
  const [assignmentQuery, setAssignmentQuery] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">(
    "idle",
  );
  const [saveMessage, setSaveMessage] = useState("");
  const [detachingRecordKey, setDetachingRecordKey] = useState("");
  const [feedbackActionMessage, setFeedbackActionMessage] = useState("");
  const [scrub, setScrub] = useState<{
    shotId: string;
    fraction: number;
    time: number;
  } | null>(null);
  const [scrubReadyShotId, setScrubReadyShotId] = useState("");
  const [inspectorScrub, setInspectorScrub] = useState<{
    shotId: string;
    fraction: number;
    time: number;
  } | null>(null);
  const [inspectorScrubReadyShotId, setInspectorScrubReadyShotId] =
    useState("");
  const [draggedRecordKey, setDraggedRecordKey] = useState("");
  const [dragOverShotId, setDragOverShotId] = useState("");
  const [dropSavingShotId, setDropSavingShotId] = useState("");
  const scrubVideoRef = useRef<HTMLVideoElement | null>(null);
  const inspectorScrubVideoRef = useRef<HTMLVideoElement | null>(null);
  const autoSaveQueueRef = useRef<Promise<void>>(Promise.resolve());
  const autoSaveVersionRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    function hydrateFeedback(result: FeedbackData) {
      result.editNotes ||= [];
      setFeedback(result);
      const firstShotId = cuts[0]?.shotId || "";
      setSelectedShotId((current) => current || firstShotId);
      const initialParent = result.parents.find((parent) =>
        parent.shotIds.includes(firstShotId),
      );
      const initialNote = result.notes.find((note) =>
        note.shotIds.includes(firstShotId),
      );
      const initialGeneral = result.generalNotes.find((note) =>
        note.shotIds.includes(firstShotId),
      );
      const initialEdit = result.editNotes.find((note) =>
        note.shotIds.includes(firstShotId),
      );
      const initial = initialParent
        ? ({ kind: "parent", record: initialParent } as FeedbackRecord)
        : initialGeneral
          ? ({ kind: "general", record: initialGeneral } as FeedbackRecord)
          : initialNote
            ? ({ kind: "note", record: initialNote } as FeedbackRecord)
            : result.generalNotes[0]
              ? ({
                  kind: "general",
                  record: result.generalNotes[0],
                } as FeedbackRecord)
              : initialEdit
                ? ({ kind: "edit", record: initialEdit } as FeedbackRecord)
              : result.parents[0]
                ? ({
                    kind: "parent",
                    record: result.parents[0],
                  } as FeedbackRecord)
                : null;
      if (initial) {
        setSelectedRecordKey(recordKey(initial));
        setDraftTitle(recordTitle(initial));
        setDraftDescription(initial.record.noteDescription);
        setDraftDependency(initial.record.dependency);
        setDraftParentIds(
          initial.kind === "note" ? initial.record.parentIds : [],
        );
        setDraftShotIds(initial.record.shotIds || []);
        setDraftEditStatus(
          initial.kind === "edit"
            ? initial.record.status
            : "to-incorporate",
        );
      }
    }

    async function loadFeedback() {
      setLoadError("");
      try {
        const response = await fetch(`${apiBase}/api/feedback`, {
          cache: "no-store",
        });
        const result = (await response.json()) as FeedbackData & { error?: string };
        if (!response.ok) throw new Error(result.error || "Unable to load feedback.");
        if (!cancelled) hydrateFeedback(result);
      } catch {
        if (!cancelled) {
          hydrateFeedback(structuredClone(bundledFeedback));
        }
      }
    }
    void loadFeedback();
    return () => {
      cancelled = true;
    };
  }, [apiBase, cuts]);

  useEffect(() => {
    const video = scrubVideoRef.current;
    if (!video || !scrub) return;
    const seek = () => {
      video.pause();
      if (Math.abs(video.currentTime - scrub.time) > 0.015) {
        video.currentTime = scrub.time;
      }
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      seek();
      return;
    }
    video.addEventListener("loadedmetadata", seek, { once: true });
    return () => video.removeEventListener("loadedmetadata", seek);
  }, [scrub]);

  useEffect(() => {
    const video = inspectorScrubVideoRef.current;
    if (!video || !inspectorScrub) return;
    const seek = () => {
      video.pause();
      if (Math.abs(video.currentTime - inspectorScrub.time) > 0.015) {
        video.currentTime = inspectorScrub.time;
      }
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      seek();
      return;
    }
    video.addEventListener("loadedmetadata", seek, { once: true });
    return () => video.removeEventListener("loadedmetadata", seek);
  }, [inspectorScrub]);

  const parentById = useMemo(
    () => new Map(feedback?.parents.map((parent) => [parent.id, parent]) || []),
    [feedback],
  );

  const recordsByShot = useMemo(() => {
    const index = new Map<string, FeedbackRecord[]>();
    for (const cut of cuts) index.set(cut.shotId, []);
    for (const parent of feedback?.parents || []) {
      for (const shotId of parent.shotIds || []) {
        index.get(shotId)?.push({ kind: "parent", record: parent });
      }
    }
    for (const note of feedback?.generalNotes || []) {
      for (const shotId of note.shotIds) {
        index.get(shotId)?.push({ kind: "general", record: note });
      }
    }
    for (const note of feedback?.notes || []) {
      for (const shotId of note.shotIds) {
        index.get(shotId)?.push({ kind: "note", record: note });
      }
    }
    for (const note of feedback?.editNotes || []) {
      for (const shotId of note.shotIds) {
        index.get(shotId)?.push({ kind: "edit", record: note });
      }
    }
    return index;
  }, [cuts, feedback]);

  const selectedRecords = recordsByShot.get(selectedShotId) || [];

  const selectedRecord = useMemo(() => {
    return feedbackRecordForKey(feedback, selectedRecordKey);
  }, [feedback, selectedRecordKey]);

  const draggedRecord = useMemo(
    () => feedbackRecordForKey(feedback, draggedRecordKey),
    [draggedRecordKey, feedback],
  );

  const sections = useMemo(
    () => Array.from(new Set(cuts.map((cut) => cut.sectionCode))),
    [cuts],
  );

  const editOrderedCuts = useMemo(
    () => applyEditFeedbackOrder(cuts, feedback?.editNotes || []),
    [cuts, feedback],
  );

  const filteredCuts = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const orderedCuts = feedbackScope === "edit" ? editOrderedCuts : cuts;
    return orderedCuts.filter((cut) => {
      const records = recordsByShot.get(cut.shotId) || [];
      if (section !== "ALL" && cut.sectionCode !== section) return false;
      if (feedbackScope === "notes" && !records.length) return false;
      if (!["all", "notes", "edit"].includes(feedbackScope)) {
        if (
          !records.some((item) =>
            item.kind === "parent"
              ? item.record.id === feedbackScope
              : item.kind !== "edit" &&
                item.record.parentIds.includes(feedbackScope),
          )
        ) {
          return false;
        }
      }
      if (!normalizedQuery) return true;
      const searchable = [
        cut.id,
        cut.sectionCode,
        cut.timecode,
        ...records.flatMap((item) =>
          item.kind === "parent"
            ? [item.record.name, item.record.noteDescription]
            : item.kind === "edit"
              ? [
                  item.record.title,
                  item.record.noteDescription,
                  editStatusLabel(item.record.status),
                  "edit order swap",
                ]
            : [
                item.record.title,
                item.record.noteDescription,
                ...item.record.parentIds.map(
                  (parentId) => parentById.get(parentId)?.name || parentId,
                ),
              ],
        ),
      ]
        .join(" ")
        .toLowerCase();
      return searchable.includes(normalizedQuery);
    });
  }, [
    cuts,
    editOrderedCuts,
    feedbackScope,
    parentById,
    query,
    recordsByShot,
    section,
  ]);

  const selectedCut = cuts.find((cut) => cut.shotId === selectedShotId);
  const cutByShotId = useMemo(
    () => new Map(cuts.map((cut) => [cut.shotId, cut])),
    [cuts],
  );
  const canonicalPositionByShotId = useMemo(
    () => new Map(cuts.map((cut, index) => [cut.shotId, index + 1])),
    [cuts],
  );
  const editPositionByShotId = useMemo(
    () =>
      new Map(editOrderedCuts.map((cut, index) => [cut.shotId, index + 1])),
    [editOrderedCuts],
  );
  const notesIndexCategories = useMemo(() => {
    if (!feedback) return [];
    return feedback.parents.map((parent) => ({
        id: parent.id,
        label: parent.name,
        records: [
          ...(parent.shotIds.length
            ? [({ kind: "parent", record: parent } as FeedbackRecord)]
            : []),
          ...feedback.generalNotes
            .filter((note) => note.parentIds.includes(parent.id))
            .map(
              (record) => ({ kind: "general", record }) as FeedbackRecord,
            ),
          ...feedback.notes
            .filter((note) => note.parentIds.includes(parent.id))
            .map((record) => ({ kind: "note", record }) as FeedbackRecord),
        ],
      }));
  }, [feedback]);
  const assignedShotSet = useMemo(
    () => new Set(draftShotIds),
    [draftShotIds],
  );
  const assignmentCuts = useMemo(() => {
    const normalizedQuery = assignmentQuery.trim().toLowerCase();
    if (!normalizedQuery) return [];
    return cuts
      .filter(
        (cut) =>
          !assignedShotSet.has(cut.shotId) &&
          `${cut.id} ${cut.sectionCode} ${cut.shotName}`
            .toLowerCase()
            .includes(normalizedQuery),
      )
      .slice(0, 24);
  }, [assignedShotSet, assignmentQuery, cuts]);

  const sourceRows = useMemo(() => {
    if (!feedback || !selectedRecord) return [];
    const wanted = new Set(selectedRecord.record.sourceIds);
    return feedback.sourceRows.filter((row) => wanted.has(row.id));
  }, [feedback, selectedRecord]);

  const hasChanges =
    !!selectedRecord &&
    ((selectedRecord.kind !== "parent" &&
      draftTitle !== selectedRecord.record.title) ||
      draftDescription !== selectedRecord.record.noteDescription ||
      draftDependency !== selectedRecord.record.dependency ||
      (selectedRecord.kind === "note" &&
        [...draftParentIds].sort().join("|") !==
          [...selectedRecord.record.parentIds].sort().join("|")) ||
      (selectedRecord.kind === "edit" &&
        draftEditStatus !== selectedRecord.record.status) ||
      [...draftShotIds].sort().join("|") !==
      [...(selectedRecord.record.shotIds || [])].sort().join("|"));

  useEffect(() => {
    const version = ++autoSaveVersionRef.current;
    if (!selectedRecord || !feedback || !hasChanges) return;

    const normalizedTitle =
      selectedRecord.kind !== "parent" ? draftTitle.trim() : "";
    if (selectedRecord.kind !== "parent" && !normalizedTitle) {
      return;
    }
    if (selectedRecord.kind === "note" && !draftParentIds.length) {
      return;
    }

    const activeShotIds = new Set(cuts.map((cut) => cut.shotId));
    const canonicalShotIds = [
      ...draftShotIds.filter((shotId) => !activeShotIds.has(shotId)),
      ...cuts
        .filter((cut) => draftShotIds.includes(cut.shotId))
        .map((cut) => cut.shotId),
    ];
    const snapshot = {
      kind: selectedRecord.kind,
      id: selectedRecord.record.id,
      title:
        selectedRecord.kind !== "parent" ? normalizedTitle : undefined,
      noteDescription: draftDescription,
      dependency: draftDependency,
      parentIds:
        selectedRecord.kind === "note" ? draftParentIds : undefined,
      status:
        selectedRecord.kind === "edit" ? draftEditStatus : undefined,
      shotIds: canonicalShotIds,
    };

    const timer = window.setTimeout(() => {
      autoSaveQueueRef.current = autoSaveQueueRef.current
        .catch(() => undefined)
        .then(async () => {
          if (version !== autoSaveVersionRef.current) return;
          setSaveState("saving");
          setSaveMessage("");
          try {
            const response = await fetch(`${apiBase}/api/feedback/update`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(snapshot),
            });
            const result = (await response.json()) as {
              feedback?: FeedbackData;
              error?: string;
            };
            if (!response.ok || !result.feedback) {
              throw new Error(result.error || "Unable to save feedback.");
            }
            if (version !== autoSaveVersionRef.current) return;
            setFeedback(result.feedback);
            if (selectedRecord.kind !== "parent") {
              setDraftTitle(normalizedTitle);
            }
            setDraftShotIds(canonicalShotIds);
            setSaveState("saved");
            setSaveMessage("Saved automatically");
          } catch (error) {
            if (version !== autoSaveVersionRef.current) return;
            setSaveState("error");
            setSaveMessage(
              error instanceof Error ? error.message : "Unable to save.",
            );
          }
        });
    }, 500);

    return () => window.clearTimeout(timer);
  }, [
    apiBase,
    cuts,
    draftDependency,
    draftDescription,
    draftEditStatus,
    draftParentIds,
    draftShotIds,
    draftTitle,
    feedback,
    hasChanges,
    selectedRecord,
  ]);

  function selectFeedbackRecord(item: FeedbackRecord | null) {
    setSelectedRecordKey(item ? recordKey(item) : "");
    setDraftTitle(item ? recordTitle(item) : "");
    setDraftDescription(item?.record.noteDescription || "");
    setDraftDependency(item?.record.dependency || "");
    setDraftParentIds(item?.kind === "note" ? item.record.parentIds : []);
    setDraftShotIds(item?.record.shotIds || []);
    setDraftEditStatus(
      item?.kind === "edit" ? item.record.status : "to-incorporate",
    );
    setAssignmentQuery("");
    setSaveState("idle");
    setSaveMessage("");
    setFeedbackActionMessage("");
  }

  function openCut(shotId: string) {
    setSelectedShotId(shotId);
    setInspectorScrub(null);
    setInspectorScrubReadyShotId("");
    const first = recordsByShot.get(shotId)?.[0];
    selectFeedbackRecord(first || null);
    setInspectorOpen(true);
  }

  function toggleCutNotes(shotId: string, hasNotes: boolean) {
    setFeedbackNavPinned(false);
    setSelectedShotId(shotId);
    setInspectorScrub(null);
    setInspectorScrubReadyShotId("");
    const first = recordsByShot.get(shotId)?.[0];
    selectFeedbackRecord(first || null);
    setExpandedNotesShotId((current) =>
      hasNotes && current !== shotId ? shotId : "",
    );
  }

  function openGeneralNote(note: FeedbackGeneralNote) {
    selectFeedbackRecord({ kind: "general", record: note });
    setInspectorOpen(true);
  }

  function scrollToFeedbackShot(shotId: string) {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        const frame = document.querySelector<HTMLElement>(
          `[data-shot-id="${shotId}"] .feedback-cut-frame`,
        );
        if (!frame) return;
        const nav =
          document.querySelector<HTMLElement>(".feedback-sticky-nav");
        const stickyBottom = nav?.classList.contains("pinned")
          ? nav.getBoundingClientRect().bottom
          : 64;
        const frameTop = frame.getBoundingClientRect().top;
        window.scrollTo({
          top: Math.max(0, window.scrollY + frameTop - stickyBottom - 12),
          behavior: "smooth",
        });
      });
    });
  }

  function openIndexedRecord(item: FeedbackRecord, shotId?: string) {
    setQuery("");
    setSection("ALL");
    setInspectorOpen(true);
    if (!shotId) {
      setFeedbackNavPinned(false);
      if (item.kind === "general") openGeneralNote(item.record);
      else selectFeedbackRecord(item);
      return;
    }

    setFeedbackNavPinned(true);
    openCut(shotId);
    selectFeedbackRecord(item);
    setExpandedNotesShotId(shotId);
    scrollToFeedbackShot(shotId);
  }

  function toggleShotAssignment(shotId: string) {
    setDraftShotIds((current) =>
      current.includes(shotId)
        ? current.filter((item) => item !== shotId)
        : [...current, shotId],
    );
    setSaveState("idle");
  }

  function openAppliedShot(shotId: string) {
    if (!cutByShotId.has(shotId)) return;
    setFeedbackNavPinned(false);
    setSelectedShotId(shotId);
    setExpandedNotesShotId(shotId);
    setInspectorScrub(null);
    setInspectorScrubReadyShotId("");
    setInspectorOpen(true);
    scrollToFeedbackShot(shotId);
  }

  function updateScrub(
    event: ReactPointerEvent<HTMLButtonElement>,
    cut: FeedbackCut,
  ) {
    if (cut.isGap) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const fraction = Math.max(
      0,
      Math.min(1, (event.clientX - bounds.left) / bounds.width),
    );
    const scrubStart = cut.scrubStart ?? cut.start;
    const scrubEnd = cut.scrubEnd ?? cut.end;
    const lastFrame = Math.max(scrubStart, scrubEnd - 1 / fps);
    setScrub({
      shotId: cut.shotId,
      fraction,
      time: scrubStart + fraction * (lastFrame - scrubStart),
    });
  }

  function updateInspectorScrub(
    event: ReactPointerEvent<HTMLDivElement>,
    cut: FeedbackCut,
  ) {
    if (cut.isGap) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const fraction = Math.max(
      0,
      Math.min(1, (event.clientX - bounds.left) / bounds.width),
    );
    const scrubStart = cut.scrubStart ?? cut.start;
    const scrubEnd = cut.scrubEnd ?? cut.end;
    const lastFrame = Math.max(scrubStart, scrubEnd - 1 / fps);
    setInspectorScrub({
      shotId: cut.shotId,
      fraction,
      time: scrubStart + fraction * (lastFrame - scrubStart),
    });
  }

  function startRecordDrag(
    event: ReactDragEvent<HTMLElement>,
    item: FeedbackRecord,
  ) {
    if (item.kind === "edit") {
      event.preventDefault();
      setFeedbackActionMessage(
        "Edit-order notes stay attached to their complete operation.",
      );
      return;
    }
    const key = recordKey(item);
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setData("application/x-paracosm-feedback-record", key);
    event.dataTransfer.setData("text/plain", key);
    setDraggedRecordKey(key);
    setDragOverShotId("");
    setFeedbackActionMessage("");
  }

  function endRecordDrag() {
    setDraggedRecordKey("");
    setDragOverShotId("");
  }

  async function dropRecordOnCut(
    event: ReactDragEvent<HTMLElement>,
    shotId: string,
  ) {
    event.preventDefault();
    event.stopPropagation();
    const key =
      event.dataTransfer.getData("application/x-paracosm-feedback-record") ||
      draggedRecordKey;
    const item = feedbackRecordForKey(feedback, key);
    setDragOverShotId("");
    if (!item) return;

    const title = recordTitle(item);
    const targetCut = cuts.find((cut) => cut.shotId === shotId);
    if (item.record.shotIds.includes(shotId)) {
      setFeedbackActionMessage(
        `${title} is already applied to ${targetCut?.id || "this shot"}.`,
      );
      setDraggedRecordKey("");
      return;
    }

    const nextShotIds = [
      ...item.record.shotIds,
      shotId,
    ].filter((value, index, values) => values.indexOf(value) === index);
    setDropSavingShotId(shotId);
    try {
      const response = await fetch(`${apiBase}/api/feedback/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: item.kind,
          id: item.record.id,
          noteDescription: item.record.noteDescription,
          dependency: item.record.dependency,
          shotIds: nextShotIds,
        }),
      });
      const result = (await response.json()) as {
        feedback?: FeedbackData;
        error?: string;
      };
      if (!response.ok || !result.feedback) {
        throw new Error(result.error || "Unable to apply this note.");
      }
      setFeedback(result.feedback);
      if (selectedRecordKey === key) setDraftShotIds(nextShotIds);
      setFeedbackActionMessage(
        `${title} also applied to ${targetCut?.id || "the shot"}.`,
      );
    } catch (error) {
      setFeedbackActionMessage(
        error instanceof Error ? error.message : "Unable to apply this note.",
      );
    } finally {
      setDraggedRecordKey("");
      setDragOverShotId("");
      setDropSavingShotId("");
    }
  }

  async function detachRecordFromCut(item: FeedbackRecord) {
    if (!feedback || !selectedShotId) return;
    if (item.kind === "edit") {
      setFeedbackActionMessage(
        "Edit-order notes cannot be detached from only one side of a swap.",
      );
      return;
    }
    const key = recordKey(item);
    const title = recordTitle(item);
    const nextShotIds = (item.record.shotIds || []).filter(
      (shotId) => shotId !== selectedShotId,
    );
    setDetachingRecordKey(key);
    setFeedbackActionMessage("");
    try {
      const response = await fetch(`${apiBase}/api/feedback/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: item.kind,
          id: item.record.id,
          noteDescription: item.record.noteDescription,
          dependency: item.record.dependency,
          shotIds: nextShotIds,
        }),
      });
      const result = (await response.json()) as {
        feedback?: FeedbackData;
        error?: string;
      };
      if (!response.ok || !result.feedback) {
        throw new Error(result.error || "Unable to remove this shot assignment.");
      }

      setFeedback(result.feedback);
      if (selectedRecordKey === key) {
        const nextParent = result.feedback.parents.find(
          (parent) =>
            parent.id !== item.record.id &&
            parent.shotIds.includes(selectedShotId),
        );
        const nextNote = result.feedback.notes.find(
          (note) =>
            note.id !== item.record.id &&
            note.shotIds.includes(selectedShotId),
        );
        const nextGeneral = result.feedback.generalNotes.find(
          (note) =>
            note.id !== item.record.id &&
            note.shotIds.includes(selectedShotId),
        );
        const nextRecord = nextParent
          ? ({ kind: "parent", record: nextParent } as FeedbackRecord)
          : nextGeneral
            ? ({ kind: "general", record: nextGeneral } as FeedbackRecord)
            : nextNote
              ? ({ kind: "note", record: nextNote } as FeedbackRecord)
              : null;
        selectFeedbackRecord(nextRecord);
      }
      setFeedbackActionMessage(
        `${title} removed from ${selectedCut?.id || "the shot"}.`,
      );
    } catch (error) {
      setFeedbackActionMessage(
        error instanceof Error ? error.message : "Unable to remove this note.",
      );
    } finally {
      setDetachingRecordKey("");
    }
  }

  if (!feedback) {
    return (
      <section className="feedback-loading">
        <p className="eyebrow">FEEDBACK TRACKER</p>
        <h2>{loadError || "Reading the working sheet…"}</h2>
        {loadError && (
          <button className="primary-button" onClick={() => window.location.reload()}>
            Retry
          </button>
        )}
      </section>
    );
  }

  const expandedIndexCategory =
    feedbackScope === "edit"
      ? {
          id: "edit",
          label: "Edit",
          records: feedback.editNotes.map(
            (record) => ({ kind: "edit", record }) as FeedbackRecord,
          ),
        }
      : feedbackScope === "notes"
      ? {
          id: "notes",
          label: "Notes",
          records: [
            ...feedback.generalNotes.map(
              (record) => ({ kind: "general", record }) as FeedbackRecord,
            ),
            ...feedback.parents
              .filter((parent) => parent.shotIds.length)
              .map(
                (record) => ({ kind: "parent", record }) as FeedbackRecord,
              ),
            ...feedback.notes.map(
              (record) => ({ kind: "note", record }) as FeedbackRecord,
            ),
          ],
        }
      : notesIndexCategories.find(
          (category) => category.id === feedbackScope,
        );
  const filteredShotIds = new Set(filteredCuts.map((cut) => cut.shotId));
  const filteredPositionByShotId = new Map(
    filteredCuts.map((cut, index) => [cut.shotId, index]),
  );
  const normalizedIndexQuery = query.trim().toLowerCase();
  const visibleIndexRows: Array<{
    item: FeedbackRecord;
    cut: FeedbackCut | null;
  }> = expandedIndexCategory
    ? expandedIndexCategory.records.flatMap<{
        item: FeedbackRecord;
        cut: FeedbackCut | null;
      }>((item) => {
        const activeCuts = item.record.shotIds
          .map((shotId) => cutByShotId.get(shotId))
          .filter(
            (cut): cut is FeedbackCut =>
              !!cut && filteredShotIds.has(cut.shotId),
          )
          .sort(
            (first, second) =>
              (filteredPositionByShotId.get(first.shotId) ?? Infinity) -
              (filteredPositionByShotId.get(second.shotId) ?? Infinity),
          );
        if (activeCuts.length) {
          return activeCuts.map((cut) => ({ item, cut }));
        }
        if (
          item.record.shotIds.length ||
          (section !== "ALL" && item.kind !== "general")
        ) {
          return [];
        }
        if (normalizedIndexQuery) {
          const searchable =
            item.kind === "parent"
              ? `${item.record.name} ${item.record.noteDescription} ${item.record.dependency}`
              : `${item.record.title} ${item.record.noteDescription} ${item.record.dependency}`;
          if (!searchable.toLowerCase().includes(normalizedIndexQuery)) return [];
        }
        return [{ item, cut: null }];
      })
    : [];
  const inspectingGeneral =
    selectedRecord?.kind === "general" &&
    !selectedRecord.record.shotIds.includes(selectedShotId);
  const selectedRecordCategory = !selectedRecord
    ? ""
    : selectedRecord.kind === "parent"
        ? "Parent"
        : selectedRecord.kind === "edit"
          ? "Edit"
        : selectedRecord.record.parentIds
            .map((parentId) => parentById.get(parentId)?.name || parentId)
            .join(" + ") || "Uncategorized";
  const effectiveDraftParentIds =
    draftParentIds.length || selectedRecord?.kind !== "note"
      ? draftParentIds
      : selectedRecord.record.parentIds;
  const draftParentValue =
    effectiveDraftParentIds.length === 1
      ? effectiveDraftParentIds[0]
      : effectiveDraftParentIds.join("|");
  const draftParentLabel = effectiveDraftParentIds
    .map((parentId) => parentById.get(parentId)?.name || parentId)
    .join(" + ");
  const activeEditNotes = feedback.editNotes.filter(
    (note) => note.status === "to-incorporate",
  );

  return (
    <div
      className={`feedback-workspace ${inspectorOpen ? "feedback-inspector-open" : ""}`}
    >
      <section className="feedback-main">
        <div
          className={`feedback-sticky-nav ${
            feedbackNavPinned ? "pinned" : ""
          }`}
        >
          <div className="feedback-notes-index-bar">
            <div className="feedback-scope-tabs">
              <button
                className={feedbackScope === "all" ? "active" : ""}
                onClick={() => {
                  setFeedbackNavPinned(false);
                  setFeedbackNavExpanded(false);
                  setFeedbackScope("all");
                }}
                aria-pressed={feedbackScope === "all"}
              >
                All
                {feedbackScope === "all" && (
                  <b className="feedback-nav-count">{filteredCuts.length}</b>
                )}
              </button>
              <button
                className={feedbackScope === "notes" ? "active" : ""}
                onClick={() => {
                  setFeedbackNavPinned(false);
                  setFeedbackScope("notes");
                }}
                aria-pressed={feedbackScope === "notes"}
                aria-expanded={
                  feedbackScope === "notes" && feedbackNavExpanded
                }
                aria-controls="feedback-notes-index-contents"
              >
                Notes
                {feedbackScope === "notes" && (
                  <b className="feedback-nav-count">{filteredCuts.length}</b>
                )}
              </button>
              <button
                className={feedbackScope === "edit" ? "active" : ""}
                onClick={() => {
                  setFeedbackNavPinned(false);
                  setFeedbackNavExpanded(true);
                  setFeedbackScope("edit");
                }}
                aria-pressed={feedbackScope === "edit"}
                aria-expanded={
                  feedbackScope === "edit" && feedbackNavExpanded
                }
                aria-controls="feedback-notes-index-contents"
              >
                Edit
                {!!activeEditNotes.length && (
                  <b className="feedback-nav-count">
                    {activeEditNotes.length}
                  </b>
                )}
              </button>
            </div>
            <div className="feedback-notes-index-tabs">
              {notesIndexCategories.map((category) => (
                <button
                  className={feedbackScope === category.id ? "active" : ""}
                  key={category.id}
                  onClick={() => {
                    setFeedbackNavPinned(false);
                    setFeedbackScope(category.id);
                  }}
                  aria-expanded={
                    feedbackScope === category.id && feedbackNavExpanded
                  }
                  aria-controls="feedback-notes-index-contents"
                >
                  {category.label}
                  {feedbackScope === category.id && (
                    <b className="feedback-nav-count">
                      {filteredCuts.length}
                    </b>
                  )}
                </button>
              ))}
            </div>
            <label className="feedback-search feedback-top-search">
              <input
                value={query}
                onChange={(event) => {
                  setFeedbackNavPinned(false);
                  setQuery(event.target.value);
                }}
                placeholder="Search"
                aria-label="Search"
              />
            </label>
            <label className="feedback-section-filter feedback-top-chapter">
              <select
                value={section}
                onChange={(event) => {
                  setFeedbackNavPinned(false);
                  setSection(event.target.value);
                }}
                aria-label="Chapter"
              >
                <option value="ALL">Chapter</option>
                {sections.map((sectionCode) => (
                  <option value={sectionCode} key={sectionCode}>
                    {sectionCode}
                  </option>
                ))}
              </select>
            </label>
            {expandedIndexCategory && (
              <button
                type="button"
                className="feedback-nav-collapse"
                onClick={() => {
                  setFeedbackNavPinned(false);
                  setFeedbackNavExpanded((current) => !current);
                }}
                aria-expanded={feedbackNavExpanded}
                aria-controls="feedback-notes-index-contents"
                aria-label={
                  feedbackNavExpanded
                    ? "Collapse feedback navigation"
                    : "Expand feedback navigation"
                }
                title={
                  feedbackNavExpanded
                    ? "Collapse note index"
                    : "Expand note index"
                }
              >
                {feedbackNavExpanded ? "⌃" : "⌄"}
              </button>
            )}
          </div>

          {feedbackNavExpanded && expandedIndexCategory && (
            <section className="feedback-notes-index">
              <div
                className="feedback-notes-index-contents"
                id="feedback-notes-index-contents"
              >
                <div className="feedback-notes-index-list">
                  {visibleIndexRows.map(({ item, cut }) => {
                    const shot = cut
                      ? splitShotName(cut.shotName)
                      : { code: "", name: "" };
                    return (
                      <div
                        className={`feedback-notes-index-row ${
                          selectedRecordKey === recordKey(item) &&
                          (!cut || selectedShotId === cut.shotId)
                            ? "active"
                            : ""
                        } ${
                          draggedRecordKey === recordKey(item) ? "dragging" : ""
                        }`}
                        key={`${recordKey(item)}:${cut?.shotId || "unassigned"}`}
                        draggable
                        onDragStart={(event) => startRecordDrag(event, item)}
                        onDragEnd={endRecordDrag}
                        title={`Drag ${recordTitle(item)} onto a shot`}
                      >
                        <button
                          draggable={false}
                          onClick={() => openIndexedRecord(item, cut?.shotId)}
                        >
                          <b>{cut ? cut.sectionCode : "-"}</b>
                          <em>{shot.code}</em>
                          <span>{shot.name}</span>
                          <strong>{recordTitle(item)}</strong>
                          <i>{recordBadge(item)}</i>
                          <small>
                            {cut ? `${cut.duration.toFixed(1)}s` : "—"}
                          </small>
                        </button>
                      </div>
                    );
                  })}
                  {!visibleIndexRows.length && (
                    <p>No notes or assigned shots match this view.</p>
                  )}
                </div>
              </div>
            </section>
          )}
        </div>

        {feedbackScope === "edit" && (
          <section className="feedback-edit-preview" aria-label="Edit preview">
            <div>
              <span>EDIT PREVIEW</span>
              <strong>Working order only</strong>
              <p>
                Canonical cut IDs, timecodes, thumbnails, and provenance remain
                unchanged.
              </p>
            </div>
            <div className="feedback-edit-preview-changes">
              {activeEditNotes.map((note) => {
                const first = cutByShotId.get(note.shotIds[0]);
                const second = cutByShotId.get(note.shotIds[1]);
                return (
                  <button
                    type="button"
                    key={note.id}
                    onClick={() =>
                      openIndexedRecord(
                        { kind: "edit", record: note },
                        editOrderedCuts.find((cut) =>
                          note.shotIds.includes(cut.shotId),
                        )?.shotId,
                      )
                    }
                  >
                    <b>{editStatusLabel(note.status)}</b>
                    <span>
                      {first?.id || "First shot"} ↔{" "}
                      {second?.id || "Second shot"}
                    </span>
                    <small>{note.title}</small>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        <div className="feedback-cut-grid">
          {filteredCuts.map((cut) => {
            const records = recordsByShot.get(cut.shotId) || [];
            const canonicalPosition =
              canonicalPositionByShotId.get(cut.shotId) || 0;
            const editPosition = editPositionByShotId.get(cut.shotId) || 0;
            const editOrderChanged =
              feedbackScope === "edit" &&
              canonicalPosition > 0 &&
              editPosition > 0 &&
              canonicalPosition !== editPosition;
            const hasEditNote = records.some((item) => item.kind === "edit");
            const parentIds = Array.from(
              new Set(
                records.flatMap((item) =>
                  item.kind === "parent"
                    ? [item.record.id]
                    : item.kind === "edit"
                      ? []
                    : item.record.parentIds,
                ),
              ),
            );
            return (
              <article
                className={`feedback-cut-card ${
                  selectedShotId === cut.shotId ? "selected" : ""
                } ${records.length ? "has-feedback" : "no-feedback"} ${
                  dragOverShotId === cut.shotId ? "drop-target" : ""
                } ${
                  dropSavingShotId === cut.shotId ? "drop-saving" : ""
                } ${
                  draggedRecord?.record.shotIds.includes(cut.shotId)
                    ? "already-assigned"
                    : ""
                } ${editOrderChanged ? "edit-order-changed" : ""}`}
                key={cut.shotId}
                data-cut-id={cut.id}
                data-shot-id={cut.shotId}
                data-canonical-position={canonicalPosition || undefined}
                data-edit-position={editPosition || undefined}
                aria-current={
                  selectedShotId === cut.shotId ? "true" : undefined
                }
                onDragEnter={(event) => {
                  if (!draggedRecordKey) return;
                  event.preventDefault();
                  setDragOverShotId(cut.shotId);
                }}
                onDragOver={(event) => {
                  if (!draggedRecordKey) return;
                  event.preventDefault();
                  event.dataTransfer.dropEffect = "copy";
                }}
                onDragLeave={(event) => {
                  if (
                    event.relatedTarget instanceof Node &&
                    event.currentTarget.contains(event.relatedTarget)
                  ) {
                    return;
                  }
                  setDragOverShotId((current) =>
                    current === cut.shotId ? "" : current,
                  );
                }}
                onDrop={(event) => void dropRecordOnCut(event, cut.shotId)}
              >
                <button
                  className={`feedback-cut-frame ${
                    cut.isGap ? "" : "scrubbable"
                  }`}
                  onClick={() => toggleCutNotes(cut.shotId, !!records.length)}
                  onPointerEnter={(event) => {
                    setScrubReadyShotId("");
                    updateScrub(event, cut);
                  }}
                  onPointerMove={(event) => updateScrub(event, cut)}
                  onPointerLeave={() => {
                    setScrub(null);
                    setScrubReadyShotId("");
                  }}
                  title={
                    cut.isGap ? undefined : "Move left to right to scrub this cut"
                  }
                  aria-label={
                    records.length
                      ? `${expandedNotesShotId === cut.shotId ? "Hide" : "Show"} notes for ${cut.id}`
                      : `Select ${cut.id}`
                  }
                  aria-expanded={
                    records.length
                      ? expandedNotesShotId === cut.shotId
                      : undefined
                  }
                  aria-controls={
                    records.length ? `feedback-card-notes-${cut.shotId}` : undefined
                  }
                >
                  {cut.isGap ? (
                    <i>EDITORIAL GAP</i>
                  ) : (
                    <>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={cut.thumbnail} alt="" />
                      {scrub?.shotId === cut.shotId && (
                        <video
                          ref={scrubVideoRef}
                          className={`cut-scrub-video ${
                            scrubReadyShotId === cut.shotId ? "ready" : ""
                          }`}
                          src={
                            cut.scrubProxy ||
                            hoverProxy ||
                            "/archive/reference/paracosm-hover.mp4"
                          }
                          poster={cut.thumbnail}
                          muted
                          playsInline
                          preload="auto"
                          aria-hidden="true"
                          onSeeked={() => setScrubReadyShotId(cut.shotId)}
                        />
                      )}
                      <span className="feedback-scrub-track" aria-hidden="true">
                        <i
                          style={{
                            width: `${
                              scrub?.shotId === cut.shotId
                                ? scrub.fraction * 100
                                : 0
                            }%`,
                          }}
                        />
                      </span>
                    </>
                  )}
                </button>
                <button
                  className="feedback-cut-body"
                  onClick={() => toggleCutNotes(cut.shotId, !!records.length)}
                  aria-label={
                    records.length
                      ? `${expandedNotesShotId === cut.shotId ? "Hide" : "Show"} notes for ${cut.id}`
                      : `Select ${cut.id}`
                  }
                  aria-expanded={
                    records.length
                      ? expandedNotesShotId === cut.shotId
                      : undefined
                  }
                  aria-controls={
                    records.length ? `feedback-card-notes-${cut.shotId}` : undefined
                  }
                >
                  <ShotCardDetails
                    chapter={cut.sectionCode}
                    name={cut.shotName}
                    duration={cut.duration}
                    cutNumber={cut.id}
                    timecode={cut.timecode}
                    description={cut.description}
                    tags={
                      <>
                        {!!records.length && (
                          <i className="note-total">
                            {records.length} {records.length === 1 ? "note" : "notes"}
                          </i>
                        )}
                        {!!records.length && (
                          <span className="feedback-card-categories">
                            {editOrderChanged && (
                              <i className="feedback-edit-position">
                                Edit position {editPosition}
                              </i>
                            )}
                            {hasEditNote && (
                              <i className="tone-edit">Edit</i>
                            )}
                            {parentIds.map((parentId) => (
                              <i
                                className={`tone-${parentTone[parentId]}`}
                                key={parentId}
                              >
                                {parentById.get(parentId)?.name || parentId}
                              </i>
                            ))}
                            {!parentIds.length && !hasEditNote && (
                              <i>Shot note</i>
                            )}
                          </span>
                        )}
                      </>
                    }
                  />
                </button>
                {SHOW_FEEDBACK_SOURCE_APPLICATION_TAGS && (
                  <SourceApplicationLinks
                    cut={cut}
                    apiBase={apiBase}
                    onMessage={setFeedbackActionMessage}
                  />
                )}
                {expandedNotesShotId === cut.shotId && !!records.length && (
                  <div
                    className="feedback-card-note-drawer"
                    id={`feedback-card-notes-${cut.shotId}`}
                  >
                    {records.map((item) => (
                      <button
                        className="feedback-card-note"
                        key={recordKey(item)}
                        onClick={() => {
                          openCut(cut.shotId);
                          selectFeedbackRecord(item);
                        }}
                      >
                        <span>{recordTitle(item)}</span>
                        <i>{recordBadge(item)}</i>
                      </button>
                    ))}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <RightInspectorPanel
        open={inspectorOpen}
        onOpenChange={setInspectorOpen}
        label="Feedback"
        panelClassName="feedback-inspector"
        contentClassName="feedback-inspector-content"
        contentId="feedback-inspector-content"
      >
          {inspectingGeneral && selectedRecord?.kind === "general" && (
            <section className="feedback-general-inspector-head">
              <div>
                <p className="eyebrow">
                  {selectedRecordCategory.toUpperCase()}
                </p>
                <h2>{selectedRecord.record.title}</h2>
                <span>Film-wide direction · not attached to a selected shot</span>
              </div>
              <b>Tier {selectedRecord.record.tier}</b>
            </section>
          )}

          {!inspectingGeneral && selectedCut && (
            <section className="feedback-cut-inspector-head">
              <div
                className={`feedback-inspector-frame ${
                  selectedCut.isGap ? "" : "scrubbable"
                }`}
                onPointerEnter={(event) => {
                  setInspectorScrubReadyShotId("");
                  updateInspectorScrub(event, selectedCut);
                }}
                onPointerMove={(event) =>
                  updateInspectorScrub(event, selectedCut)
                }
                onPointerLeave={() => {
                  setInspectorScrub(null);
                  setInspectorScrubReadyShotId("");
                }}
                title={
                  selectedCut.isGap
                    ? undefined
                    : "Move left to right to scrub this cut"
                }
                aria-label={
                  selectedCut.isGap
                    ? `${selectedCut.id} editorial gap`
                    : `Scrub ${selectedCut.id}`
                }
              >
                {selectedCut.isGap ? (
                  <i>EDITORIAL GAP</i>
                ) : (
                  <>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={selectedCut.thumbnail} alt="" />
                    {inspectorScrub?.shotId === selectedCut.shotId && (
                      <video
                        ref={inspectorScrubVideoRef}
                        className={`cut-scrub-video ${
                          inspectorScrubReadyShotId === selectedCut.shotId
                            ? "ready"
                            : ""
                        }`}
                        src={
                          selectedCut.scrubProxy ||
                          hoverProxy ||
                          "/archive/reference/paracosm-hover.mp4"
                        }
                        poster={selectedCut.thumbnail}
                        muted
                        playsInline
                        preload="auto"
                        aria-hidden="true"
                        onSeeked={() =>
                          setInspectorScrubReadyShotId(selectedCut.shotId)
                        }
                      />
                    )}
                    <span className="feedback-scrub-track" aria-hidden="true">
                      <i
                        style={{
                          width: `${
                            inspectorScrub?.shotId === selectedCut.shotId
                              ? inspectorScrub.fraction * 100
                              : 0
                          }%`,
                        }}
                      />
                    </span>
                  </>
                )}
              </div>
              <ShotCardDetails
                chapter={selectedCut.sectionCode}
                name={selectedCut.shotName}
                duration={selectedCut.duration}
                cutNumber={selectedCut.id}
                timecode={selectedCut.timecode}
                description={selectedCut.description}
              />
            </section>
          )}

          {!inspectingGeneral && !!selectedRecords.length && (
            <section className="feedback-record-list">
              <div className="feedback-inspector-heading">
                <span>Notes</span>
                <b>{selectedRecords.length}</b>
              </div>
              {selectedRecords.map((item) => {
                const title = recordTitle(item);
                return (
                  <div
                    className={`feedback-record-row ${
                      selectedRecordKey === recordKey(item) ? "active" : ""
                    } ${
                      draggedRecordKey === recordKey(item) ? "dragging" : ""
                    } ${item.kind === "edit" ? "edit-record" : ""}`}
                    key={recordKey(item)}
                    data-feedback-record-key={recordKey(item)}
                    draggable={item.kind !== "edit"}
                    onDragStart={(event) => startRecordDrag(event, item)}
                    onDragEnd={endRecordDrag}
                    title={
                      item.kind === "edit"
                        ? "Edit-order operations stay attached to both shots"
                        : `Drag ${title} onto another cut`
                    }
                  >
                    <button
                      className="feedback-record-select"
                      draggable={false}
                      onClick={() => selectFeedbackRecord(item)}
                    >
                      <span>{title}</span>
                      <i>{recordBadge(item)}</i>
                    </button>
                    {item.kind !== "edit" && (
                      <button
                        className="feedback-record-detach"
                        draggable={false}
                        onClick={() => void detachRecordFromCut(item)}
                        disabled={detachingRecordKey === recordKey(item)}
                        aria-label={`Remove ${title} from ${selectedCut?.id || "this shot"}`}
                        title={`Remove from ${selectedCut?.id || "this shot"}`}
                      >
                        ×
                      </button>
                    )}
                  </div>
                );
              })}
            </section>
          )}

          {!inspectingGeneral && !selectedRecords.length && selectedCut && (
            <section className="feedback-empty-cut">
              <span>0</span>
              <h3>No notes on {selectedCut.id}</h3>
              <p>
                Open a parent note from the top of the page, or select a note on
                another cut and add this shot to its assignments.
              </p>
            </section>
          )}

          {feedbackActionMessage && (
            <p className="feedback-action-message">{feedbackActionMessage}</p>
          )}

          {selectedRecord && (
            <>
              <section className="feedback-editor">
                <div className="feedback-note-editor-head">
                  <span>Note :</span>
                  {selectedRecord.kind !== "parent" ? (
                    <textarea
                      value={draftTitle}
                      onChange={(event) => {
                        const nextTitle = event.target.value.replace(
                          /[\r\n]+/g,
                          " ",
                        );
                        setDraftTitle(nextTitle);
                        setSaveState(nextTitle.trim() ? "idle" : "error");
                        setSaveMessage(
                          nextTitle.trim() ? "" : "Note name cannot be empty.",
                        );
                      }}
                      rows={1}
                      wrap="soft"
                      maxLength={300}
                      placeholder="Name this note"
                      aria-label="Note headline"
                    />
                  ) : (
                    <strong>{recordTitle(selectedRecord)}</strong>
                  )}
                  {selectedRecord.kind === "note" ? (
                    <label className="feedback-note-parent">
                      <select
                        value={draftParentValue}
                        onChange={(event) => {
                          setDraftParentIds([event.target.value]);
                          setSaveState("idle");
                        }}
                        aria-label="Parent"
                      >
                        {effectiveDraftParentIds.length > 1 && (
                          <option value={draftParentValue}>
                            {draftParentLabel}
                          </option>
                        )}
                        {feedback?.parents.map((parent) => (
                          <option value={parent.id} key={parent.id}>
                            {parent.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : (
                    <i>{selectedRecordCategory}</i>
                  )}
                  <b>{recordBadge(selectedRecord)}</b>
                  {saveState === "error" && (
                    <em
                      className="feedback-note-save-state error"
                      title={saveMessage || selectedRecord.record.id}
                    >
                      {saveMessage || "Save failed"}
                    </em>
                  )}
                </div>

                {selectedRecord.kind === "edit" && (
                  <label className="feedback-edit-status">
                    <span>Edit status</span>
                    <select
                      value={draftEditStatus}
                      onChange={(event) => {
                        setDraftEditStatus(
                          event.target.value as EditFeedbackStatus,
                        );
                        setSaveState("idle");
                      }}
                      aria-label="Edit status"
                    >
                      <option value="to-incorporate">To incorporate</option>
                      <option value="incorporated">Incorporated</option>
                      <option value="superseded">Superseded</option>
                    </select>
                  </label>
                )}

                <label className="feedback-edit-field">
                  <span>Note Description</span>
                  <textarea
                    value={draftDescription}
                    onChange={(event) => {
                      setDraftDescription(event.target.value);
                      setSaveState("idle");
                    }}
                    rows={2}
                  />
                </label>

                <label className="feedback-edit-field">
                  <span>Dependency</span>
                  <textarea
                    value={draftDependency}
                    onChange={(event) => {
                      setDraftDependency(event.target.value);
                      setSaveState("idle");
                    }}
                    rows={2}
                    placeholder="No dependency recorded"
                  />
                </label>

                {selectedRecord.kind === "edit" ? (
                  <section className="feedback-order-operation">
                    <div>
                      <span>Order change</span>
                      <b>Swap</b>
                    </div>
                    <div className="feedback-order-operation-shots">
                      {draftShotIds.map((shotId, index) => {
                        const cut = cutByShotId.get(shotId);
                        return (
                          <span key={shotId}>
                            {index > 0 && <i aria-hidden="true">↔</i>}
                            <button
                              type="button"
                              disabled={!cut}
                              onClick={() => openAppliedShot(shotId)}
                            >
                              {cut?.id || "Retired shot"}
                            </button>
                          </span>
                        );
                      })}
                    </div>
                    <p>
                      This changes only the Feedback edit preview. Canonical
                      cut IDs, timecodes, and provenance stay untouched until
                      the edit is incorporated upstream.
                    </p>
                  </section>
                ) : (
                <section className="feedback-assignment">
                  <div className="feedback-assignment-head">
                    <div>
                      <span>Applied shots</span>
                      <b>{draftShotIds.length}</b>
                    </div>
                  </div>
                  <div className="feedback-assigned-chips">
                    {draftShotIds.map((shotId) => {
                      const cut = cutByShotId.get(shotId);
                      return (
                        <span
                          className={cut ? "" : "retired"}
                          key={shotId}
                        >
                          {cut ? (
                            <button
                              type="button"
                              className="feedback-assigned-shot-open"
                              onClick={() => openAppliedShot(shotId)}
                              title={`Open ${cut.id}`}
                            >
                              {cut.id}
                            </button>
                          ) : (
                            <i>Retired shot</i>
                          )}
                          <button
                            type="button"
                            className="feedback-assigned-shot-remove"
                            title={`Remove ${cut ? cut.id : shotId}`}
                            aria-label={`Remove ${cut ? cut.id : shotId}`}
                            onClick={() => toggleShotAssignment(shotId)}
                          >
                            ×
                          </button>
                        </span>
                      );
                    })}
                    {!draftShotIds.length && (
                      <span className="empty">
                        {selectedRecord.kind === "general"
                          ? "Not attached to any shots"
                          : "No shot assignments"}
                      </span>
                    )}
                  </div>
                  <div className="feedback-assignment-add">
                    <input
                      value={assignmentQuery}
                      onChange={(event) => setAssignmentQuery(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key !== "Enter" || !assignmentCuts[0]) return;
                        event.preventDefault();
                        toggleShotAssignment(assignmentCuts[0].shotId);
                        setAssignmentQuery("");
                      }}
                      placeholder="Search shots"
                      aria-label="Search shots to apply this note"
                    />
                    <button
                      type="button"
                      disabled={!assignmentCuts[0]}
                      onClick={() => {
                        if (!assignmentCuts[0]) return;
                        toggleShotAssignment(assignmentCuts[0].shotId);
                        setAssignmentQuery("");
                      }}
                      aria-label={
                        assignmentCuts[0]
                          ? `Apply to ${assignmentCuts[0].id}`
                          : "Search for a shot to apply"
                      }
                    >
                      +
                    </button>
                  </div>
                  {!!assignmentQuery.trim() && (
                    <div className="feedback-assignment-picker">
                      <div>
                        {assignmentCuts.map((cut) => (
                          <button
                            type="button"
                            key={cut.shotId}
                            onClick={() => {
                              toggleShotAssignment(cut.shotId);
                              setAssignmentQuery("");
                            }}
                          >
                            <img
                              src={cut.thumbnail}
                              alt=""
                              loading="lazy"
                            />
                            <span>
                              <b>{cut.sectionCode}</b>
                              <strong>{cut.shotName}</strong>
                            </span>
                            <small>{cut.id}</small>
                            <i aria-hidden="true">+</i>
                          </button>
                        ))}
                        {!assignmentCuts.length && (
                          <p>No unassigned shots match.</p>
                        )}
                      </div>
                    </div>
                  )}
                </section>
                )}
              </section>

              {!!sourceRows.length && (
                <section className="feedback-source-context">
                  {sourceRows.map((row, rowIndex) => (
                    <details key={row.id} open={rowIndex === 0}>
                      <summary>Source note {row.id}</summary>
                      <dl>
                        {feedback.sourceColumns.map((column) => (
                          <div key={column}>
                            <dt>{column}</dt>
                            <dd>{sourceValue(row.values[column])}</dd>
                          </div>
                        ))}
                      </dl>
                    </details>
                  ))}
                </section>
              )}
            </>
          )}
      </RightInspectorPanel>
    </div>
  );
}
