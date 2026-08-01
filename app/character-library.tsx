"use client";

import {
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import characterLibraryData from "../data/abby-expression-library.json";
import avatarMockupVersionData from "../data/abby-avatar-mockup-versions.json";
import performanceFacialData from "../data/abby-performance-facial-cues.json";
import {
  AvatarGuide,
  AvatarGuideInspector,
  type AvatarGuideSelection,
} from "./avatar-guide";
import { RightInspectorPanel } from "./right-inspector-panel";
import {
  copyProductionPath,
  isLocalProductionBrowser,
  runtimeApiBase,
} from "./runtime-api";

type CharacterSource = {
  id: string;
  label: string;
  fileName: string;
  collection: string;
  originalPath: string;
  proxy: string;
  durationSeconds: number;
  visibleScope: "face" | "full_body" | "hands";
};

type CharacterCue = {
  id: string;
  sourceId: string;
  label: string;
  kind:
    | "facial_expression"
    | "head_direction"
    | "eye_direction"
    | "performance_beat"
    | "hand_performance";
  family: string;
  start: number;
  end: number;
  peak: number;
  description: string;
  confidence: "high" | "medium";
  tags: string[];
  poster: string;
};

type CharacterLibraryData = {
  character: {
    id: string;
    name: string;
    description: string;
    identityMotion: string;
    identityContactSheet: string;
  };
  summary: {
    sourceCount: number;
    facialExpressionCount: number;
    performanceBeatCount: number;
    durationSeconds: number;
  };
  sources: CharacterSource[];
  cues: CharacterCue[];
};

type AvatarMockupVersion = {
  id: string;
  label: string;
  detail: string;
  image: string;
  ordinal: number;
};

type AvatarMockupVersionManifest = {
  updatedAt: string;
  cues: Record<
    string,
    Array<Omit<AvatarMockupVersion, "ordinal">>
  >;
};

const baseLibrary = characterLibraryData as CharacterLibraryData;
const avatarMockupVersionManifest =
  avatarMockupVersionData as AvatarMockupVersionManifest;
const performanceFacialCues = (
  performanceFacialData as { cues: CharacterCue[] }
).cues;
const combinedCues = [...baseLibrary.cues, ...performanceFacialCues];
const library: CharacterLibraryData = {
  ...baseLibrary,
  summary: {
    ...baseLibrary.summary,
    facialExpressionCount: combinedCues.filter((cue) =>
      isFacialCueKind(cue.kind),
    ).length,
  },
  cues: combinedCues,
};

const API = runtimeApiBase();
const CLOSEUP_PREVIEW_ROOT =
  "/archive/character-reference/abby/expression-library/previews";
const AVATAR_MOCKUP_ROOT =
  "/archive/character-reference/abby/mockup-performance-library/2026-07-29";
const CHARACTER_THUMBNAIL_SELECTION_STORAGE_KEY =
  "paracosm:character-cue-thumbnail-selections:v1";
const CHARACTER_CUE_PREFERENCES_STORAGE_KEY =
  "paracosm:character-cue-preferences:v1";
const CHARACTER_MOCKUP_VERSION_SELECTION_STORAGE_KEY =
  "paracosm:character-mockup-version-selections:v1";
const CHARACTER_SCRUB_FPS = 24;

type CharacterCuePreferences = {
  customCueNames: Record<string, string>;
  favoriteCueIds: Set<string>;
  hiddenCueIds: Set<string>;
};

function isFacialCueKind(kind: CharacterCue["kind"]) {
  return kind !== "performance_beat" && kind !== "hand_performance";
}

function readCharacterThumbnailSelections() {
  if (typeof window === "undefined") return {};
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(
        CHARACTER_THUMBNAIL_SELECTION_STORAGE_KEY,
      ) || "{}",
    );
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    return Object.fromEntries(
      Object.entries(parsed).filter(
        ([cueId, time]) =>
          cueId.length > 0 &&
          typeof time === "number" &&
          Number.isFinite(time),
      ),
    ) as Record<string, number>;
  } catch {
    return {};
  }
}

function readCharacterMockupVersionSelections() {
  if (typeof window === "undefined") return {};
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(
        CHARACTER_MOCKUP_VERSION_SELECTION_STORAGE_KEY,
      ) || "{}",
    );
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    return Object.fromEntries(
      Object.entries(parsed).filter(
        ([cueId, versionId]) =>
          cueId.length > 0 &&
          typeof versionId === "string" &&
          versionId.length > 0,
      ),
    ) as Record<string, string>;
  } catch {
    return {};
  }
}

function persistCharacterMockupVersionSelection(
  cueId: string,
  versionId: string,
) {
  if (typeof window === "undefined") return;
  const selections = readCharacterMockupVersionSelections();
  selections[cueId] = versionId;
  window.localStorage.setItem(
    CHARACTER_MOCKUP_VERSION_SELECTION_STORAGE_KEY,
    JSON.stringify(selections),
  );
}

function persistCharacterThumbnailSelection(cueId: string, time: number) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      CHARACTER_THUMBNAIL_SELECTION_STORAGE_KEY,
      JSON.stringify({
        ...readCharacterThumbnailSelections(),
        [cueId]: time,
      }),
    );
  } catch {
    return;
  }
}

function readCharacterCuePreferences(): CharacterCuePreferences {
  const emptyPreferences = {
    customCueNames: {},
    favoriteCueIds: new Set<string>(),
    hiddenCueIds: new Set<string>(),
  };
  if (typeof window === "undefined") return emptyPreferences;
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(CHARACTER_CUE_PREFERENCES_STORAGE_KEY) ||
        "{}",
    );
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return emptyPreferences;
    }
    const favoriteCueIds = Array.isArray(parsed.favoriteCueIds)
      ? parsed.favoriteCueIds.filter(
          (cueId: unknown): cueId is string => typeof cueId === "string",
        )
      : [];
    const hiddenCueIds = Array.isArray(parsed.hiddenCueIds)
      ? parsed.hiddenCueIds.filter(
          (cueId: unknown): cueId is string => typeof cueId === "string",
        )
      : [];
    const customCueNames =
      parsed.customCueNames &&
      typeof parsed.customCueNames === "object" &&
      !Array.isArray(parsed.customCueNames)
        ? Object.fromEntries(
            Object.entries(parsed.customCueNames).filter(
              ([cueId, name]) =>
                cueId.length > 0 &&
                typeof name === "string" &&
                name.trim().length > 0,
            ),
          )
        : {};
    return {
      customCueNames,
      favoriteCueIds: new Set(favoriteCueIds),
      hiddenCueIds: new Set(hiddenCueIds),
    };
  } catch {
    return emptyPreferences;
  }
}

function persistCharacterCuePreferences(
  preferences: CharacterCuePreferences,
) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      CHARACTER_CUE_PREFERENCES_STORAGE_KEY,
      JSON.stringify({
        customCueNames: preferences.customCueNames,
        favoriteCueIds: Array.from(preferences.favoriteCueIds),
        hiddenCueIds: Array.from(preferences.hiddenCueIds),
      }),
    );
  } catch {
    return;
  }
}

function clampCueTime(time: number, start: number, end: number) {
  const lastFrame = Math.max(start, end - 0.5 / CHARACTER_SCRUB_FPS);
  return Math.max(start, Math.min(lastFrame, time));
}

function cueTimeAtFraction(
  fraction: number,
  start: number,
  end: number,
) {
  const boundedFraction = Math.max(0, Math.min(1, fraction));
  const frameCount = Math.max(
    1,
    Math.round((end - start) * CHARACTER_SCRUB_FPS),
  );
  const frameOffset = Math.min(
    frameCount - 1,
    Math.floor(boundedFraction * frameCount),
  );
  return clampCueTime(
    start + (frameOffset + 0.5) / CHARACTER_SCRUB_FPS,
    start,
    end,
  );
}

function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds - minutes * 60;
  return `${String(minutes).padStart(2, "0")}:${remaining
    .toFixed(1)
    .padStart(4, "0")}`;
}

function formatLibraryDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds - minutes * 60);
  return `${minutes}m ${String(remaining).padStart(2, "0")}s`;
}

function cueKindLabel(kind: CharacterCue["kind"]) {
  if (kind === "facial_expression") return "Expression";
  if (kind === "eye_direction") return "Eye direction";
  if (kind === "head_direction") return "Head direction";
  if (kind === "hand_performance") return "Hand performance";
  return "Performance beat";
}

function CharacterCueCard({
  cue,
  source,
  index,
  displayLabel,
  isFavorite,
  mediaMode,
  mockupVersion,
  mockupVersionCount,
  versionsOpen,
  onOpenVersions,
  onRemove,
  onRename,
  onToggleFavorite,
}: {
  cue: CharacterCue;
  source: CharacterSource;
  index: number;
  displayLabel: string;
  isFavorite: boolean;
  mediaMode: "mockup" | "source";
  mockupVersion: AvatarMockupVersion;
  mockupVersionCount: number;
  versionsOpen: boolean;
  onOpenVersions: () => void;
  onRemove: () => void;
  onRename: (label: string) => void;
  onToggleFavorite: () => void;
}) {
  const [previewing, setPreviewing] = useState(false);
  const [previewReady, setPreviewReady] = useState(false);
  const [captureOpen, setCaptureOpen] = useState(false);
  const [selectedFrameTime, setSelectedFrameTime] = useState<number | null>(
    null,
  );
  const previewVideoRef = useRef<HTMLVideoElement | null>(null);
  const captureOpenRef = useRef(false);
  const scrubAnimationFrameRef = useRef<number | null>(null);
  const duration = Math.max(0.05, cue.end - cue.start);
  const usesCloseupPreview = isFacialCueKind(cue.kind);
  const previewStart = usesCloseupPreview ? 0 : cue.start;
  const previewEnd = usesCloseupPreview ? duration : cue.end;
  const defaultPreviewTime = clampCueTime(
    usesCloseupPreview ? cue.peak - cue.start : cue.peak,
    previewStart,
    previewEnd,
  );
  const pendingScrubTimeRef = useRef(defaultPreviewTime);
  const [scrubTime, setScrubTime] = useState(defaultPreviewTime);
  const previewSource = usesCloseupPreview
    ? `${CLOSEUP_PREVIEW_ROOT}/${cue.id}.mp4`
    : source.proxy;
  const showsMockup = mediaMode === "mockup";
  const displayTime =
    previewing || captureOpen
      ? scrubTime
      : selectedFrameTime ?? defaultPreviewTime;
  const previewProgress =
    previewEnd > previewStart
      ? Math.max(
          0,
          Math.min(1, (scrubTime - previewStart) / (previewEnd - previewStart)),
        )
      : 0;
  const selectedOffset =
    selectedFrameTime === null
      ? null
      : usesCloseupPreview
        ? selectedFrameTime
        : selectedFrameTime - cue.start;

  useEffect(() => {
    captureOpenRef.current = captureOpen;
  }, [captureOpen]);

  useEffect(
    () => () => {
      if (scrubAnimationFrameRef.current !== null) {
        window.cancelAnimationFrame(scrubAnimationFrameRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    const storedTime = readCharacterThumbnailSelections()[cue.id];
    if (typeof storedTime !== "number") return;
    const selectedTime = clampCueTime(
      storedTime,
      previewStart,
      previewEnd,
    );
    const hydrationFrame = window.requestAnimationFrame(() => {
      setSelectedFrameTime(selectedTime);
      setScrubTime(selectedTime);
    });
    return () => window.cancelAnimationFrame(hydrationFrame);
  }, [cue.id, previewEnd, previewStart]);

  useEffect(() => {
    const video = previewVideoRef.current;
    if (!video) return;
    const seek = () => {
      video.pause();
      if (Math.abs(video.currentTime - displayTime) > 0.015) {
        video.currentTime = displayTime;
      } else {
        setPreviewReady(true);
      }
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      seek();
      return;
    }
    video.addEventListener("loadedmetadata", seek, { once: true });
    return () => video.removeEventListener("loadedmetadata", seek);
  }, [displayTime]);

  function updateScrub(event: ReactPointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const fraction =
      bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 0;
    pendingScrubTimeRef.current = cueTimeAtFraction(
      fraction,
      previewStart,
      previewEnd,
    );
    setPreviewing(true);
    if (scrubAnimationFrameRef.current !== null) return;
    scrubAnimationFrameRef.current = window.requestAnimationFrame(() => {
      scrubAnimationFrameRef.current = null;
      const nextTime = pendingScrubTimeRef.current;
      setScrubTime((currentTime) =>
        Math.abs(currentTime - nextTime) <
        0.5 / CHARACTER_SCRUB_FPS
          ? currentTime
          : nextTime,
      );
    });
  }

  function startScrub(event: ReactPointerEvent<HTMLDivElement>) {
    updateScrub(event);
  }

  function resetPreview() {
    if (scrubAnimationFrameRef.current !== null) {
      window.cancelAnimationFrame(scrubAnimationFrameRef.current);
      scrubAnimationFrameRef.current = null;
    }
    const resetTime = selectedFrameTime ?? defaultPreviewTime;
    pendingScrubTimeRef.current = resetTime;
    setPreviewing(false);
    setScrubTime(resetTime);
  }

  function handleRegionLeave() {
    if (captureOpenRef.current) return;
    resetPreview();
  }

  function beginCapture() {
    captureOpenRef.current = true;
    setCaptureOpen(true);
    setPreviewing(true);
  }

  function cancelCapture() {
    captureOpenRef.current = false;
    setCaptureOpen(false);
    resetPreview();
  }

  function confirmCapture() {
    persistCharacterThumbnailSelection(cue.id, scrubTime);
    setSelectedFrameTime(scrubTime);
    captureOpenRef.current = false;
    setCaptureOpen(false);
    setPreviewing(false);
    setPreviewReady(true);
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      beginCapture();
      return;
    }
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    let nextTime = scrubTime;
    if (event.key === "ArrowLeft") nextTime -= 1 / CHARACTER_SCRUB_FPS;
    if (event.key === "ArrowRight") nextTime += 1 / CHARACTER_SCRUB_FPS;
    if (event.key === "Home") nextTime = previewStart;
    if (event.key === "End") nextTime = previewEnd;
    setPreviewing(true);
    setScrubTime(clampCueTime(nextTime, previewStart, previewEnd));
  }

  function handleMediaKeyDown(
    event: ReactKeyboardEvent<HTMLDivElement>,
  ) {
    if (
      showsMockup &&
      (event.key === "Enter" || event.key === " ")
    ) {
      event.preventDefault();
      onOpenVersions();
      return;
    }
    handleKeyDown(event);
  }

  return (
    <article
      className={`character-expression-card ${
        captureOpen ? "capture-open" : ""
      } ${previewing ? "scrub-previewing" : ""} ${
        selectedFrameTime !== null ? "has-selected-frame" : ""
      } ${isFavorite ? "is-favorite" : ""} ${
        showsMockup ? "is-avatar-mockup" : ""
      } ${versionsOpen ? "active" : ""}`}
    >
      <div
        className="character-expression-media-shell"
      >
        <div
          className="character-expression-image"
          role="button"
          tabIndex={0}
          title={
            showsMockup
              ? "Move left to right to reveal and scrub the source; click to open mockup versions"
              : "Move left to right to scrub; click to select this frame"
          }
          aria-label={
            showsMockup
              ? `${displayLabel}. Mockup ${mockupVersion.ordinal} of ${mockupVersionCount}. Move left to right to reveal and scrub the source; click to open mockup versions.`
              : `${displayLabel}. Move left to right to scrub ${formatTime(
                  cue.start,
                )} through ${formatTime(
                  cue.end,
                )}; click to select a thumbnail frame.`
          }
          onClick={showsMockup ? onOpenVersions : beginCapture}
          onKeyDown={handleMediaKeyDown}
          onPointerEnter={startScrub}
          onPointerMove={updateScrub}
          onPointerLeave={handleRegionLeave}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={showsMockup ? mockupVersion.image : cue.poster}
            alt={showsMockup ? `${displayLabel} rendered on Abby` : ""}
          />
          <video
            ref={previewVideoRef}
            className={`character-cue-hover-video ${
              previewReady && (!showsMockup || previewing || captureOpen)
                ? "ready"
                : ""
            }`}
            src={previewSource}
            poster={cue.poster}
            muted
            playsInline
            preload="auto"
            aria-hidden="true"
            onLoadedData={(event) => {
              event.currentTarget.pause();
              if (
                Math.abs(event.currentTarget.currentTime - displayTime) >
                0.015
              ) {
                event.currentTarget.currentTime = displayTime;
              } else {
                setPreviewReady(true);
              }
            }}
            onSeeked={() => setPreviewReady(true)}
          />
          <b>{String(index + 1).padStart(2, "0")}</b>
          <small>
            {showsMockup && !previewing && !captureOpen
              ? `Mockup ${mockupVersion.ordinal}`
              : `${(cue.end - cue.start).toFixed(1)}s`}
          </small>
          <span
            className="character-cue-card-controls"
            onPointerMove={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className={isFavorite ? "active" : ""}
              aria-label={`${
                isFavorite ? "Remove" : "Add"
              } ${displayLabel} ${isFavorite ? "from" : "to"} favorites`}
              aria-pressed={isFavorite}
              title={isFavorite ? "Remove favorite" : "Mark favorite"}
              onClick={(event) => {
                event.stopPropagation();
                onToggleFavorite();
              }}
              onKeyDown={(event) => event.stopPropagation()}
            >
              ★
            </button>
            <button
              type="button"
              aria-label={`Remove ${displayLabel} from this gallery`}
              title="Remove from gallery"
              onClick={(event) => {
                event.stopPropagation();
                onRemove();
              }}
              onKeyDown={(event) => event.stopPropagation()}
            >
              ×
            </button>
          </span>
          {selectedOffset !== null ? (
            <em className="character-selected-frame-badge">
              Thumbnail +{selectedOffset.toFixed(2)}s
            </em>
          ) : null}
          <i className="character-cue-hover-track" aria-hidden="true">
            <span style={{ width: `${previewProgress * 100}%` }} />
          </i>
        </div>
        {captureOpen ? (
          <div
            className="character-cue-capture-overlay"
            role="group"
            aria-label="Make thumbnail?"
          >
            <span>
              Make thumbnail?
              <small>
                +{(
                  usesCloseupPreview
                    ? scrubTime
                    : scrubTime - cue.start
                ).toFixed(2)}
                s
              </small>
            </span>
            <span>
              <button
                type="button"
                aria-label="Confirm make thumbnail"
                title="Make thumbnail"
                onClick={confirmCapture}
              >
                ✓
              </button>
              <button
                type="button"
                aria-label="Cancel thumbnail"
                title="Cancel"
                onClick={cancelCapture}
              >
                ×
              </button>
            </span>
          </div>
        ) : null}
      </div>
      <div className="character-expression-copy">
        <div className="character-expression-title">
          <input
            key={displayLabel}
            type="text"
            defaultValue={displayLabel}
            maxLength={80}
            aria-label={`Rename ${displayLabel}`}
            title="Click to rename"
            onBlur={(event) => {
              const nextLabel = event.currentTarget.value.trim();
              if (!nextLabel) {
                event.currentTarget.value = displayLabel;
                return;
              }
              event.currentTarget.value = nextLabel;
              onRename(nextLabel);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                event.currentTarget.blur();
              }
              if (event.key === "Escape") {
                event.preventDefault();
                event.currentTarget.value = displayLabel;
                event.currentTarget.blur();
              }
            }}
          />
        </div>
        <small>
          {cueKindLabel(cue.kind)} · {cue.family}
        </small>
        <span className="character-expression-description">
          {cue.description}
        </span>
        <em>{source.label}</em>
      </div>
    </article>
  );
}

export function CharacterLibrary() {
  const facialCues = useMemo(
    () => library.cues.filter((cue) => isFacialCueKind(cue.kind)),
    [],
  );
  const performanceCues = useMemo(
    () => library.cues.filter((cue) => !isFacialCueKind(cue.kind)),
    [],
  );
  const sourceById = useMemo(
    () => new Map(library.sources.map((source) => [source.id, source])),
    [],
  );
  const [mode, setMode] = useState<
    "expressions" | "performance" | "avatar"
  >(
    "expressions",
  );
  const [mediaMode, setMediaMode] = useState<"mockup" | "source">("mockup");
  const [facialFamily, setFacialFamily] = useState("All");
  const [performanceFamily, setPerformanceFamily] = useState("All");
  const [sourceMessage, setSourceMessage] = useState("");
  const [versionPanelOpen, setVersionPanelOpen] = useState(false);
  const [versionCueId, setVersionCueId] = useState(
    facialCues[0]?.id || "",
  );
  const [avatarSelection, setAvatarSelection] =
    useState<AvatarGuideSelection | null>(null);
  const [selectedMockupVersionByCueId, setSelectedMockupVersionByCueId] =
    useState<Record<string, string>>({});
  const [cuePreferences, setCuePreferences] =
    useState<CharacterCuePreferences>({
      customCueNames: {},
      favoriteCueIds: new Set(),
      hiddenCueIds: new Set(),
    });
  const avatarVersionsByCueId = useMemo(() => {
    const versions = new Map<string, AvatarMockupVersion[]>();
    for (const cue of library.cues) {
      const revisions = avatarMockupVersionManifest.cues[cue.id] || [];
      versions.set(cue.id, [
        {
          id: "v1-original",
          label: "Original mockup",
          detail: "First approved avatar mockup, preserved unchanged.",
          image: `${AVATAR_MOCKUP_ROOT}/${cue.id}.png`,
          ordinal: 1,
        },
        ...revisions.map((revision, index) => ({
          ...revision,
          ordinal: index + 2,
        })),
      ]);
    }
    return versions;
  }, []);

  const facialFamilies = useMemo(
    () => ["All", ...Array.from(new Set(facialCues.map((cue) => cue.family)))],
    [facialCues],
  );
  const availableFacialCues = useMemo(
    () =>
      facialCues.filter((cue) => !cuePreferences.hiddenCueIds.has(cue.id)),
    [cuePreferences.hiddenCueIds, facialCues],
  );
  const visibleFacialCues = useMemo(
    () =>
      facialFamily === "All"
        ? availableFacialCues
        : availableFacialCues.filter((cue) => cue.family === facialFamily),
    [availableFacialCues, facialFamily],
  );
  const performanceFamilies = useMemo(
    () =>
      ["All", ...Array.from(new Set(performanceCues.map((cue) => cue.family)))],
    [performanceCues],
  );
  const availablePerformanceCues = useMemo(
    () =>
      performanceCues.filter(
        (cue) => !cuePreferences.hiddenCueIds.has(cue.id),
      ),
    [cuePreferences.hiddenCueIds, performanceCues],
  );
  const visiblePerformanceCues = useMemo(
    () =>
      performanceFamily === "All"
        ? availablePerformanceCues
        : availablePerformanceCues.filter(
            (cue) => cue.family === performanceFamily,
          ),
    [availablePerformanceCues, performanceFamily],
  );
  const removedFacialCueCount =
    facialCues.length - availableFacialCues.length;
  const removedPerformanceCueCount =
    performanceCues.length - availablePerformanceCues.length;

  useEffect(() => {
    const hydrationFrame = window.requestAnimationFrame(() => {
      setCuePreferences(readCharacterCuePreferences());
      const storedSelections = Object.fromEntries(
        Object.entries(readCharacterMockupVersionSelections()).filter(
          ([cueId, versionId]) =>
            avatarVersionsByCueId
              .get(cueId)
              ?.some((version) => version.id === versionId) === true,
        ),
      );
      setSelectedMockupVersionByCueId(storedSelections);
    });
    return () => window.cancelAnimationFrame(hydrationFrame);
  }, [avatarVersionsByCueId]);

  function selectedMockupVersion(cueId: string) {
    const versions = avatarVersionsByCueId.get(cueId) || [];
    const selectedId = selectedMockupVersionByCueId[cueId];
    return (
      versions.find((version) => version.id === selectedId) ||
      versions.at(-1) || {
        id: "v1-original",
        label: "Original mockup",
        detail: "First approved avatar mockup, preserved unchanged.",
        image: `${AVATAR_MOCKUP_ROOT}/${cueId}.png`,
        ordinal: 1,
      }
    );
  }

  function openMockupVersions(cueId: string) {
    setVersionCueId(cueId);
    setVersionPanelOpen(true);
  }

  function openAvatarItem(selection: AvatarGuideSelection) {
    setAvatarSelection(selection);
    setVersionPanelOpen(true);
  }

  function selectMockupVersion(cueId: string, versionId: string) {
    setSelectedMockupVersionByCueId((current) => ({
      ...current,
      [cueId]: versionId,
    }));
    persistCharacterMockupVersionSelection(cueId, versionId);
  }

  function updateCuePreferences(
    update: (preferences: CharacterCuePreferences) => void,
  ) {
    setCuePreferences((currentPreferences) => {
      const nextPreferences = {
        customCueNames: { ...currentPreferences.customCueNames },
        favoriteCueIds: new Set(currentPreferences.favoriteCueIds),
        hiddenCueIds: new Set(currentPreferences.hiddenCueIds),
      };
      update(nextPreferences);
      persistCharacterCuePreferences(nextPreferences);
      return nextPreferences;
    });
  }

  function toggleFavorite(cueId: string) {
    updateCuePreferences((preferences) => {
      if (preferences.favoriteCueIds.has(cueId)) {
        preferences.favoriteCueIds.delete(cueId);
      } else {
        preferences.favoriteCueIds.add(cueId);
      }
    });
  }

  function removeCue(cueId: string) {
    updateCuePreferences((preferences) => {
      preferences.hiddenCueIds.add(cueId);
    });
  }

  function renameCue(cue: CharacterCue, label: string) {
    updateCuePreferences((preferences) => {
      const nextLabel = label.trim();
      if (nextLabel === cue.label) {
        delete preferences.customCueNames[cue.id];
      } else {
        preferences.customCueNames[cue.id] = nextLabel;
      }
    });
  }

  function restoreRemovedCues(cues: CharacterCue[]) {
    updateCuePreferences((preferences) => {
      cues.forEach((cue) => preferences.hiddenCueIds.delete(cue.id));
    });
  }

  async function revealSource(source: CharacterSource) {
    setSourceMessage("");
    if (!isLocalProductionBrowser()) {
      try {
        await copyProductionPath(source.originalPath);
        setSourceMessage(`Copied ${source.fileName} · open on the production Mac`);
      } catch {
        setSourceMessage("Finder actions are available in the local production app.");
      }
      return;
    }
    try {
      const response = await fetch(`${API}/api/reveal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: source.originalPath,
          copyPath: true,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || "Unable to reveal source.");
      }
      setSourceMessage(`Opened in Finder · copied ${source.fileName}`);
    } catch (error) {
      setSourceMessage(
        error instanceof Error ? error.message : "Unable to reveal source.",
      );
    }
  }

  const versionPanelCue =
    library.cues.find((cue) => cue.id === versionCueId) ||
    facialCues[0];
  const versionPanelVersions = versionPanelCue
    ? avatarVersionsByCueId.get(versionPanelCue.id) || []
    : [];
  const versionPanelSelected = versionPanelCue
    ? selectedMockupVersion(versionPanelCue.id)
    : undefined;
  const versionPanelLabel = versionPanelCue
    ? cuePreferences.customCueNames[versionPanelCue.id] ??
      versionPanelCue.label
    : "Mockup versions";

  return (
    <section className="character-library">
      <div
        className={`character-workspace ${
          versionPanelOpen ? "right-inspector-open" : ""
        }`}
      >
        <div className="character-content">
      <nav className="character-sticky-nav" aria-label="Character library views">
        <div className="character-view-tabs">
          <button
            type="button"
            className={mode === "expressions" ? "active" : ""}
            onClick={() => {
              setMode("expressions");
              setFacialFamily("All");
              setVersionPanelOpen(false);
            }}
          >
            Facial expressions
            <span>{availableFacialCues.length}</span>
          </button>
          <button
            type="button"
            className={mode === "performance" ? "active" : ""}
            onClick={() => {
              setMode("performance");
              setPerformanceFamily("All");
              setVersionPanelOpen(false);
            }}
          >
            Performance beats
            <span>{availablePerformanceCues.length}</span>
          </button>
          <button
            type="button"
            className={mode === "avatar" ? "active" : ""}
            onClick={() => {
              setMode("avatar");
              setVersionPanelOpen(false);
            }}
          >
            Avatar guide
            <span>4K</span>
          </button>
        </div>
        <p>
          {mode === "avatar"
            ? "Identity, rig and source roles follow the exact ZK files."
            : "Labels describe visible performance, not character canon."}
        </p>
      </nav>

      <div className="character-main">
        {mode === "avatar" ? (
          <AvatarGuide
            identityMotion={library.character.identityMotion}
            selectedItem={avatarSelection}
            onOpenItem={openAvatarItem}
          />
        ) : (
          <>
        <header className="character-hero">
          <div className="character-hero-copy">
            <p className="character-kicker">CHARACTER 01 · ABBY</p>
            <h2>
              {mode === "performance"
                ? "Performance library"
                : "Expression library"}
            </h2>
            <p>
              {mode === "performance"
                ? "Every distinct movement, gesture, reaction and task beat—broken into scrubbable clips and kept connected to its exact original."
                : "Every distinct facial expression and eyeline—broken into scrubbable clips and kept connected to its exact original."}
            </p>
            <dl className="character-metrics">
              <div>
                <dt>Source reels</dt>
                <dd>{library.summary.sourceCount}</dd>
              </div>
              <div>
                <dt>Facial cues</dt>
                <dd>{library.summary.facialExpressionCount}</dd>
              </div>
              <div>
                <dt>Body / gesture cues</dt>
                <dd>{library.summary.performanceBeatCount}</dd>
              </div>
              <div>
                <dt>Reviewed footage</dt>
                <dd>{formatLibraryDuration(library.summary.durationSeconds)}</dd>
              </div>
            </dl>
          </div>
        </header>

        {mode === "expressions" ? (
          <section className="character-expression-browser">
            <header className="character-section-heading">
              <div>
                <p>FACIAL SLATE + PERFORMANCE SOURCES · SOURCE ORDER</p>
                <h3>{availableFacialCues.length} independent facial cues</h3>
              </div>
              <div className="character-section-controls">
                <div
                  className="character-media-tabs"
                  aria-label="Expression media"
                >
                  <button
                    type="button"
                    className={mediaMode === "mockup" ? "active" : ""}
                    onClick={() => setMediaMode("mockup")}
                  >
                    Avatar mockups
                  </button>
                  <button
                    type="button"
                    className={mediaMode === "source" ? "active" : ""}
                    onClick={() => setMediaMode("source")}
                  >
                    Live source
                  </button>
                </div>
                <div
                  className="character-family-tabs"
                  aria-label="Expression families"
                >
                  {facialFamilies.map((item) => (
                    <button
                      type="button"
                      key={item}
                      className={facialFamily === item ? "active" : ""}
                      onClick={() => setFacialFamily(item)}
                    >
                      {item}
                    </button>
                  ))}
                  {removedFacialCueCount > 0 ? (
                    <button
                      type="button"
                      className="character-restore-cues"
                      onClick={() => restoreRemovedCues(facialCues)}
                    >
                      Restore removed ({removedFacialCueCount})
                    </button>
                  ) : null}
                </div>
              </div>
            </header>
            <div className="character-expression-grid">
              {visibleFacialCues.map((cue) => {
                const source = sourceById.get(cue.sourceId);
                if (!source) return null;
                const mockupVersions =
                  avatarVersionsByCueId.get(cue.id) || [];
                const mockupVersion = selectedMockupVersion(cue.id);
                return (
                  <CharacterCueCard
                    cue={cue}
                    displayLabel={
                      cuePreferences.customCueNames[cue.id] ?? cue.label
                    }
                    index={facialCues.indexOf(cue)}
                    key={cue.id}
                    source={source}
                    isFavorite={cuePreferences.favoriteCueIds.has(cue.id)}
                    mediaMode={mediaMode}
                    mockupVersion={mockupVersion}
                    mockupVersionCount={mockupVersions.length}
                    versionsOpen={
                      versionPanelOpen && versionCueId === cue.id
                    }
                    onOpenVersions={() => openMockupVersions(cue.id)}
                    onRemove={() => removeCue(cue.id)}
                    onRename={(label) => renameCue(cue, label)}
                    onToggleFavorite={() => toggleFavorite(cue.id)}
                  />
                );
              })}
            </div>
          </section>
        ) : (
          <section className="character-performance-browser">
            <header className="character-section-heading">
              <div>
                <p>MOVEMENT + PERFORMANCE · SOURCE ORDER</p>
                <h3>
                  {availablePerformanceCues.length} independent body and gesture
                  cues
                </h3>
              </div>
              <div className="character-section-controls">
                <div
                  className="character-media-tabs"
                  aria-label="Performance media"
                >
                  <button
                    type="button"
                    className={mediaMode === "mockup" ? "active" : ""}
                    onClick={() => setMediaMode("mockup")}
                  >
                    Avatar mockups
                  </button>
                  <button
                    type="button"
                    className={mediaMode === "source" ? "active" : ""}
                    onClick={() => setMediaMode("source")}
                  >
                    Live source
                  </button>
                </div>
                <div
                  className="character-family-tabs"
                  aria-label="Performance families"
                >
                  {performanceFamilies.map((item) => (
                    <button
                      type="button"
                      key={item}
                      className={performanceFamily === item ? "active" : ""}
                      onClick={() => setPerformanceFamily(item)}
                    >
                      {item}
                    </button>
                  ))}
                  {removedPerformanceCueCount > 0 ? (
                    <button
                      type="button"
                      className="character-restore-cues"
                      onClick={() => restoreRemovedCues(performanceCues)}
                    >
                      Restore removed ({removedPerformanceCueCount})
                    </button>
                  ) : null}
                </div>
              </div>
            </header>
            <div className="character-expression-grid">
              {visiblePerformanceCues.map((cue) => {
                const source = sourceById.get(cue.sourceId);
                if (!source) return null;
                const mockupVersions =
                  avatarVersionsByCueId.get(cue.id) || [];
                const mockupVersion = selectedMockupVersion(cue.id);
                return (
                  <CharacterCueCard
                    cue={cue}
                    displayLabel={
                      cuePreferences.customCueNames[cue.id] ?? cue.label
                    }
                    index={performanceCues.indexOf(cue)}
                    key={cue.id}
                    source={source}
                    isFavorite={cuePreferences.favoriteCueIds.has(cue.id)}
                    mediaMode={mediaMode}
                    mockupVersion={mockupVersion}
                    mockupVersionCount={mockupVersions.length}
                    versionsOpen={
                      versionPanelOpen && versionCueId === cue.id
                    }
                    onOpenVersions={() => openMockupVersions(cue.id)}
                    onRemove={() => removeCue(cue.id)}
                    onRename={(label) => renameCue(cue, label)}
                    onToggleFavorite={() => toggleFavorite(cue.id)}
                  />
                );
              })}
            </div>
            <p className="character-performance-note">
              Empty lead-ins and resets without a distinct performance change
              are intentionally omitted.
            </p>
          </section>
        )}

        <section className="character-source-index">
          <header className="character-section-heading">
            <div>
              <p>AUTHORITATIVE ORIGINALS</p>
              <h3>Source index</h3>
            </div>
            <small>
              Browser proxies are review copies. These rows always point to the
              untouched source files.
            </small>
          </header>
          <div>
            {library.sources.map((source) => {
              const cueCount = library.cues.filter(
                (cue) => cue.sourceId === source.id,
              ).length;
              return (
                <button
                  type="button"
                  key={source.id}
                  onClick={() => void revealSource(source)}
                >
                  <span>{source.collection}</span>
                  <strong>{source.fileName}</strong>
                  <small>
                    {cueCount} {cueCount === 1 ? "cue" : "cues"} ·{" "}
                    {formatTime(source.durationSeconds)}
                  </small>
                  <b>Reveal + copy ↗</b>
                </button>
              );
            })}
          </div>
          {sourceMessage ? (
            <p className="character-source-message">{sourceMessage}</p>
          ) : null}
        </section>
          </>
        )}
      </div>
        </div>
        <RightInspectorPanel
          open={versionPanelOpen}
          onOpenChange={setVersionPanelOpen}
          label="Versions"
          panelClassName="mockup-version-inspector character-version-inspector"
          contentClassName="mockup-version-panel-content character-version-panel-content"
          contentId="character-version-panel-content"
        >
          {mode === "avatar" ? (
            <AvatarGuideInspector selection={avatarSelection} />
          ) : versionPanelCue && versionPanelSelected ? (
              <>
                <header className="mockup-version-panel-header">
                  <small>
                    {cueKindLabel(versionPanelCue.kind)} ·{" "}
                    {versionPanelVersions.length}{" "}
                    {versionPanelVersions.length === 1
                      ? "mockup"
                      : "mockups"}
                  </small>
                  <h2>{versionPanelLabel}</h2>
                </header>
                <p className="mockup-version-current">
                  Current pick
                  <b>
                    Mockup {versionPanelSelected.ordinal} ·{" "}
                    {versionPanelSelected.label}
                  </b>
                </p>
                <div
                  className="mockup-version-list character-version-list"
                  role="listbox"
                  aria-label={`Mockup versions for ${versionPanelLabel}`}
                >
                  {versionPanelVersions.map((version) => {
                    const selected =
                      version.id === versionPanelSelected.id;
                    return (
                      <button
                        type="button"
                        role="option"
                        aria-selected={selected}
                        className={`mockup-version-card character-avatar-version-card ${
                          selected ? "selected" : ""
                        }`}
                        key={version.id}
                        onClick={() =>
                          selectMockupVersion(
                            versionPanelCue.id,
                            version.id,
                          )
                        }
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={version.image}
                          alt={`Mockup ${version.ordinal} for ${versionPanelLabel}`}
                          loading="lazy"
                        />
                        <span>
                          <span>
                            <b>Mockup {version.ordinal}</b>
                            <small>{version.label}</small>
                          </span>
                          <i aria-hidden="true">
                            {selected ? "✓ Selected" : "Select"}
                          </i>
                        </span>
                        <p className="character-avatar-version-detail">
                          {version.detail}
                        </p>
                      </button>
                    );
                  })}
                </div>
              </>
          ) : (
            <p className="mockup-no-results">
              Choose a mockup to see its versions.
            </p>
          )}
        </RightInspectorPanel>
      </div>
    </section>
  );
}
