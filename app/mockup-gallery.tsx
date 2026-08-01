"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import mockupPassData from "../data/mockup-passes.json";
import { RightInspectorPanel } from "./right-inspector-panel";
import { ShotCardDetails } from "./shot-card-details";

type SourceFrameKind = "canonical" | "first" | "last";

type MockupPass = {
  id: string;
  styleId: string;
  title: string;
  passNumber: number;
  chapter: string;
  createdAt: string;
  description: string;
  scrubMode: "original-shot";
  items: Array<{
    cutId: string;
    image: string;
    mockupName?: string;
    mockupDescription?: string;
    sourceFrame?: SourceFrameKind;
    sourceImage?: string;
    sourceTime?: number;
  }>;
};

type MockupPassManifest = {
  schemaVersion: number;
  passes: MockupPass[];
};

type MockupLook = {
  id: string;
  title: string;
  passes: MockupPass[];
};

export type MockupCut = {
  id: string;
  shotId: string;
  shotName: string;
  description: string;
  sectionCode: string;
  thumbnail: string;
  scrubProxy?: string | null;
  scrubStart?: number;
  scrubEnd?: number;
  start: number;
  end: number;
  duration: number;
  timecode: string;
  isGap?: boolean;
};

type MockupGalleryProps = {
  cuts: MockupCut[];
  fps: number;
  hoverProxy: string;
};

type MockupRow = {
  item: MockupPass["items"][number] | null;
  cut: MockupCut;
  pass: MockupPass | null;
  mockupKey: string;
};

type MockupVersion = {
  id: string;
  kind: "mockup" | "source";
  label: string;
  detail: string;
  image: string;
  pass: MockupPass | null;
  ordinal: number | null;
  threadId: string;
  mockupName?: string;
  mockupDescription?: string;
  sourceImage?: string;
  sourceTime?: number;
};

type ThumbnailFrame = {
  image: string;
  time: number;
  frame: number;
  threadId: string;
};

type FrameThread = {
  id: string;
  sourceKind: SourceFrameKind | "custom";
  sourceTime: number;
  sourceImage: string;
  sourceDetail: string;
  mockups: MockupVersion[];
};

type FrameScrub = {
  frame: number;
  fraction: number;
  time: number;
};

type OriginalFrameCardProps = {
  cut: MockupCut;
  fps: number;
  hoverProxy: string;
  thread: FrameThread;
  threadIndex: number;
  current: boolean;
  expanded: boolean;
  onActivate: () => void;
  onCancel: () => void;
  onCapture: (
    threadId: string,
    time: number,
    video: HTMLVideoElement,
  ) => void;
};

const manifest = mockupPassData as MockupPassManifest;
const MOCKUP_THUMBNAIL_SELECTION_STORAGE_KEY =
  "paracosm:mockup-thumbnail-selections:v1";

function readMockupThumbnailSelections() {
  if (typeof window === "undefined") return {};
  try {
    const parsed = JSON.parse(
      window.localStorage.getItem(
        MOCKUP_THUMBNAIL_SELECTION_STORAGE_KEY,
      ) || "{}",
    );
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    return Object.fromEntries(
      Object.entries(parsed).filter(
        ([cutId, versionId]) =>
          cutId.length > 0 && typeof versionId === "string",
      ),
    ) as Record<string, string>;
  } catch {
    return {};
  }
}

function persistMockupThumbnailSelection(cutId: string, versionId: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      MOCKUP_THUMBNAIL_SELECTION_STORAGE_KEY,
      JSON.stringify({
        ...readMockupThumbnailSelections(),
        [cutId]: versionId,
      }),
    );
  } catch {
    return;
  }
}

function lookTitle(styleId: string) {
  if (styleId === "nth-wardrobe") return "NTH Wardrobe";
  return styleId
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

const mockupLooks: MockupLook[] = Array.from(
  new Set(manifest.passes.map((pass) => pass.styleId)),
).map((styleId) => ({
  id: styleId,
  title: lookTitle(styleId),
  passes: manifest.passes.filter((pass) => pass.styleId === styleId),
}));

function passLabel(pass: MockupPass) {
  return `Pass ${String(pass.passNumber).padStart(2, "0")}`;
}

function frameWindow(cut: MockupCut, fps: number) {
  const scrubStart = cut.scrubStart ?? cut.start;
  const scrubEnd = cut.scrubEnd ?? cut.end;
  const startFrame = Math.round(scrubStart * fps);
  const endFrame = Math.max(startFrame + 1, Math.round(scrubEnd * fps));
  const firstTime = (startFrame + 0.5) / fps;
  const lastTime = (endFrame - 0.5) / fps;
  return {
    startFrame,
    endFrame,
    frameCount: endFrame - startFrame,
    firstTime,
    lastTime,
  };
}

function scrubAtFraction(
  cut: MockupCut,
  fps: number,
  requestedFraction: number,
): FrameScrub {
  const window = frameWindow(cut, fps);
  const fraction = Math.max(0, Math.min(1, requestedFraction));
  const frameOffset = Math.min(
    window.frameCount - 1,
    Math.floor(fraction * window.frameCount),
  );
  const frame = window.startFrame + frameOffset;
  return {
    frame,
    fraction:
      window.frameCount > 1 ? frameOffset / (window.frameCount - 1) : 0,
    time: (frame + 0.5) / fps,
  };
}

function scrubAtTime(cut: MockupCut, fps: number, requestedTime: number) {
  const window = frameWindow(cut, fps);
  const frame = Math.max(
    window.startFrame,
    Math.min(
      window.endFrame - 1,
      Math.floor(Math.max(0, requestedTime) * fps),
    ),
  );
  const frameOffset = frame - window.startFrame;
  return {
    frame,
    fraction:
      window.frameCount > 1 ? frameOffset / (window.frameCount - 1) : 0,
    time: (frame + 0.5) / fps,
  };
}

function sourceTimeForKind(
  cut: MockupCut,
  fps: number,
  kind: SourceFrameKind,
) {
  const window = frameWindow(cut, fps);
  if (kind === "first") return window.firstTime;
  if (kind === "last") return window.lastTime;
  const midpointFrame =
    window.startFrame + Math.floor((window.frameCount - 1) / 2);
  return (midpointFrame + 0.5) / fps;
}

function frameOffsetLabel(cut: MockupCut, fps: number, time: number) {
  const offset = Math.max(0, time - frameWindow(cut, fps).firstTime);
  return `+${offset.toFixed(2)}s`;
}

function sourceDetailForKind(kind: FrameThread["sourceKind"]) {
  if (kind === "first") return "First frame";
  if (kind === "last") return "Last frame";
  if (kind === "custom") return "Saved thumbnail frame";
  return "Canonical thumbnail frame";
}

function OriginalFrameCard({
  cut,
  fps,
  hoverProxy,
  thread,
  threadIndex,
  current,
  expanded,
  onActivate,
  onCancel,
  onCapture,
}: OriginalFrameCardProps) {
  const initialScrub = useMemo(
    () => scrubAtTime(cut, fps, thread.sourceTime),
    [cut, fps, thread.sourceTime],
  );
  const [scrub, setScrub] = useState<FrameScrub>(initialScrub);
  const [ready, setReady] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const pendingCaptureRef = useRef(false);
  const captureOpenRef = useRef(expanded);

  useEffect(() => {
    captureOpenRef.current = expanded;
  }, [expanded]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
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
  }, [fps, scrub.time]);

  function updateScrub(event: ReactPointerEvent<HTMLDivElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const fraction =
      bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 0;
    setPreviewing(true);
    setScrub(scrubAtFraction(cut, fps, fraction));
  }

  function startScrub(event: ReactPointerEvent<HTMLDivElement>) {
    setReady(false);
    updateScrub(event);
  }

  function resetPreview() {
    pendingCaptureRef.current = false;
    setPreviewing(false);
    setReady(false);
    setScrub(initialScrub);
  }

  function handleRegionLeave() {
    if (captureOpenRef.current) return;
    resetPreview();
  }

  function beginCapture() {
    captureOpenRef.current = true;
    setPreviewing(true);
    onActivate();
  }

  function cancelCapture() {
    captureOpenRef.current = false;
    resetPreview();
    onCancel();
  }

  function nudgeScrub(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      return;
    }
    event.preventDefault();
    const window = frameWindow(cut, fps);
    let nextFrame = scrub.frame;
    if (event.key === "ArrowLeft") nextFrame -= 1;
    if (event.key === "ArrowRight") nextFrame += 1;
    if (event.key === "Home") nextFrame = window.startFrame;
    if (event.key === "End") nextFrame = window.endFrame - 1;
    nextFrame = Math.max(
      window.startFrame,
      Math.min(window.endFrame - 1, nextFrame),
    );
    setReady(false);
    setScrub(scrubAtTime(cut, fps, (nextFrame + 0.5) / fps));
  }

  function requestCapture() {
    const video = videoRef.current;
    if (!video) return;
    setPreviewing(false);
    pendingCaptureRef.current = true;
    if (
      video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
      Math.abs(video.currentTime - scrub.time) <= 0.5 / fps
    ) {
      pendingCaptureRef.current = false;
      onCapture(thread.id, scrub.time, video);
      return;
    }
    video.pause();
    video.currentTime = scrub.time;
  }

  function handleSeeked(video: HTMLVideoElement) {
    setReady(true);
    if (!pendingCaptureRef.current) return;
    if (Math.abs(video.currentTime - scrub.time) > 0.5 / fps) {
      video.currentTime = scrub.time;
      return;
    }
    pendingCaptureRef.current = false;
    onCapture(thread.id, scrub.time, video);
  }

  return (
    <article
      className={`mockup-thread-source ${
        expanded ? "capture-open" : ""
      } ${previewing ? "scrub-previewing" : ""} ${
        current ? "current-thread" : ""
      }`}
    >
      <button
        type="button"
        role="option"
        aria-selected={current}
        data-testid={`source-frame-${cut.id}-${thread.id}`}
        className="mockup-thread-source-select"
        onClick={beginCapture}
        onKeyDown={nudgeScrub}
      >
        <div
          data-testid={`source-frame-region-${cut.id}-${thread.id}`}
          className="mockup-thread-source-media"
          onPointerEnter={startScrub}
          onPointerMove={updateScrub}
          onPointerLeave={handleRegionLeave}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={thread.sourceImage}
            alt={`Original frame ${threadIndex + 1} for ${cut.id}`}
          />
          <video
            ref={videoRef}
            className={ready && (previewing || expanded) ? "ready" : ""}
            src={cut.scrubProxy || hoverProxy}
            poster={cut.thumbnail}
            muted
            playsInline
            preload="auto"
            aria-hidden="true"
            onLoadedData={(event) => {
              event.currentTarget.pause();
              if (
                Math.abs(event.currentTarget.currentTime - scrub.time) >
                0.25 / fps
              ) {
                event.currentTarget.currentTime = scrub.time;
              } else {
                setReady(true);
              }
            }}
            onSeeked={(event) => handleSeeked(event.currentTarget)}
          />
          <span className="mockup-thread-scrub-track" aria-hidden="true">
            <i style={{ width: `${scrub.fraction * 100}%` }} />
          </span>
        </div>
        <span className="mockup-thread-source-copy">
          <span>
            <b>Original frame</b>
            <small>
              {thread.sourceDetail} · {frameOffsetLabel(cut, fps, scrub.time)}
            </small>
          </span>
          <i aria-hidden="true">
            {current ? "Current thread" : expanded ? "Choose frame" : "Open"}
          </i>
        </span>
      </button>
      {expanded && (
        <div
          className="mockup-thread-capture-overlay"
          role="group"
          aria-label="Make thumbnail?"
        >
          <span>
            Make thumbnail?
            <small>
              Frame {scrub.frame} · {frameOffsetLabel(cut, fps, scrub.time)}
            </small>
          </span>
          <span>
            <button
              type="button"
              aria-label="Confirm make thumbnail"
              title="Make thumbnail"
              onClick={requestCapture}
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
      )}
    </article>
  );
}

export function MockupGallery({
  cuts,
  fps,
  hoverProxy,
}: MockupGalleryProps) {
  const [mockupScope, setMockupScope] = useState("all");
  const [query, setQuery] = useState("");
  const [section, setSection] = useState("ALL");
  const [versionPanelOpen, setVersionPanelOpen] = useState(false);
  const [versionCutId, setVersionCutId] = useState(cuts[0]?.id || "");
  const [selectedVersionByCutId, setSelectedVersionByCutId] = useState<
    Record<string, string>
  >({});
  const selectionStorageHydratedRef = useRef(false);
  const [sessionFramesByCutId, setSessionFramesByCutId] = useState<
    Record<string, Record<string, ThumbnailFrame>>
  >({});
  const [expandedSourceByCutId, setExpandedSourceByCutId] = useState<
    Record<string, string>
  >({});
  const [currentThreadByCutId, setCurrentThreadByCutId] = useState<
    Record<string, string>
  >({});
  const [cardScrub, setCardScrub] = useState<
    (FrameScrub & { shotId: string }) | null
  >(null);
  const [cardScrubReadyShotId, setCardScrubReadyShotId] = useState("");
  const cardScrubVideoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const video = cardScrubVideoRef.current;
    if (!video || !cardScrub) return;
    const seek = () => {
      video.pause();
      if (Math.abs(video.currentTime - cardScrub.time) > 0.015) {
        video.currentTime = cardScrub.time;
      }
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      seek();
      return;
    }
    video.addEventListener("loadedmetadata", seek, { once: true });
    return () => video.removeEventListener("loadedmetadata", seek);
  }, [cardScrub]);

  const cutsById = useMemo(
    () => new Map(cuts.map((cut) => [cut.id, cut])),
    [cuts],
  );
  const allMockups = useMemo<MockupRow[]>(
    () =>
      manifest.passes.flatMap((pass) =>
        pass.items.flatMap((item) => {
          const cut = cutsById.get(item.cutId);
          return cut
            ? [
                {
                  item,
                  cut,
                  pass,
                  mockupKey: `${pass.id}:${cut.shotId}`,
                },
              ]
            : [];
        }),
      ),
    [cutsById],
  );
  const latestMockupByCutId = useMemo(() => {
    const byCutId = new Map<string, MockupRow>();
    for (const mockup of allMockups) {
      byCutId.set(mockup.cut.id, mockup);
    }
    return byCutId;
  }, [allMockups]);
  const mockupVersionsByCutId = useMemo(() => {
    const byCutId = new Map<string, MockupVersion[]>();
    for (const mockup of allMockups) {
      const versions = byCutId.get(mockup.cut.id) || [];
      const sourceKind = mockup.item?.sourceFrame || "canonical";
      const sourceTime = mockup.item?.sourceTime;
      versions.push({
        id: mockup.pass?.id || mockup.mockupKey,
        kind: "mockup",
        label: mockup.pass?.title || "Mockup",
        detail: mockup.pass?.description || "Mockup",
        image: mockup.item?.image || mockup.cut.thumbnail,
        pass: mockup.pass,
        ordinal: versions.length + 1,
        mockupName: mockup.item?.mockupName,
        mockupDescription: mockup.item?.mockupDescription,
        threadId:
          typeof sourceTime === "number"
            ? `frame-${Math.floor(sourceTime * fps)}`
            : sourceKind,
        sourceImage: mockup.item?.sourceImage,
        sourceTime,
      });
      byCutId.set(mockup.cut.id, versions);
    }
    return byCutId;
  }, [allMockups, fps]);

  useEffect(() => {
    if (selectionStorageHydratedRef.current) return;
    const storedSelections = Object.fromEntries(
      Object.entries(readMockupThumbnailSelections()).filter(
        ([cutId, versionId]) =>
          mockupVersionsByCutId
            .get(cutId)
            ?.some((version) => version.id === versionId) === true,
      ),
    );
    setSelectedVersionByCutId((current) => ({
      ...storedSelections,
      ...current,
    }));
    selectionStorageHydratedRef.current = true;
  }, [mockupVersionsByCutId]);
  const threadsByCutId = useMemo(() => {
    const byCutId = new Map<string, FrameThread[]>();
    for (const cut of cuts) {
      const mockupVersions = mockupVersionsByCutId.get(cut.id) || [];
      const threadKinds: Array<SourceFrameKind | "custom"> = [];
      for (const version of mockupVersions) {
        const kind = version.threadId as SourceFrameKind;
        if (!threadKinds.includes(kind)) threadKinds.push(kind);
      }
      if (threadKinds.length === 0) threadKinds.push("canonical");
      const sessionFrames = sessionFramesByCutId[cut.id] || {};
      for (const threadId of Object.keys(sessionFrames)) {
        if (!threadKinds.includes(threadId as SourceFrameKind | "custom")) {
          threadKinds.push(threadId as SourceFrameKind | "custom");
        }
      }
      byCutId.set(
        cut.id,
        threadKinds.map((kind) => {
          const threadId = String(kind);
          const sessionFrame = sessionFrames[threadId];
          const persistedFrame = mockupVersions.find(
            (version) =>
              version.threadId === threadId &&
              typeof version.sourceTime === "number",
          );
          const sourceKind =
            kind === "canonical" || kind === "first" || kind === "last"
              ? kind
              : "custom";
          const sourceTime =
            sessionFrame?.time ??
            persistedFrame?.sourceTime ??
            sourceTimeForKind(
              cut,
              fps,
              sourceKind === "custom" ? "canonical" : sourceKind,
            );
          return {
            id: threadId,
            sourceKind,
            sourceTime,
            sourceImage:
              sessionFrame?.image ||
              persistedFrame?.sourceImage ||
              cut.thumbnail,
            sourceDetail: sourceDetailForKind(sourceKind),
            mockups: mockupVersions.filter(
              (version) => version.threadId === threadId,
            ),
          };
        }),
      );
    }
    return byCutId;
  }, [cuts, fps, mockupVersionsByCutId, sessionFramesByCutId]);
  const versionsByCutId = useMemo(() => {
    const byCutId = new Map<string, MockupVersion[]>();
    for (const cut of cuts) {
      const versions: MockupVersion[] = [];
      for (const thread of threadsByCutId.get(cut.id) || []) {
        versions.push({
          id: `source:${thread.id}`,
          kind: "source",
          label: "Original frame",
          detail: thread.sourceDetail,
          image: thread.sourceImage,
          pass: null,
          ordinal: null,
          threadId: thread.id,
        });
        versions.push(...thread.mockups);
      }
      byCutId.set(cut.id, versions);
    }
    return byCutId;
  }, [cuts, threadsByCutId]);
  const sections = useMemo(
    () => Array.from(new Set(cuts.map((cut) => cut.sectionCode))),
    [cuts],
  );
  const mockups = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const scopedRows =
      mockupScope === "all"
        ? cuts.map((cut): MockupRow => {
            const mockup = latestMockupByCutId.get(cut.id);
            return {
              item: mockup?.item || null,
              cut,
              pass: mockup?.pass || null,
              mockupKey: `all:${cut.shotId}`,
            };
          })
        : cuts.flatMap((cut): MockupRow[] => {
            const mockup = allMockups
              .filter(
                (candidate) =>
                  candidate.cut.id === cut.id &&
                  candidate.pass?.styleId === mockupScope,
              )
              .at(-1);
            return mockup
              ? [
                  {
                    ...mockup,
                    mockupKey: `${mockupScope}:${cut.shotId}`,
                  },
                ]
              : [];
          });
    return scopedRows.filter(({ cut, pass }) => {
      if (section !== "ALL" && cut.sectionCode !== section) return false;
      if (!normalizedQuery) return true;
      return [
        cut.id,
        cut.shotName,
        cut.description,
        cut.sectionCode,
        pass?.title,
        pass ? passLabel(pass) : "",
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    });
  }, [
    allMockups,
    cuts,
    latestMockupByCutId,
    mockupScope,
    query,
    section,
  ]);

  const versionPanelCut = cutsById.get(versionCutId) || cuts[0];
  const versionPanelThreads = versionPanelCut
    ? threadsByCutId.get(versionPanelCut.id) || []
    : [];
  const versionPanelVersions = versionPanelCut
    ? versionsByCutId.get(versionPanelCut.id) || []
    : [];
  const scopedPanelMockup =
    mockupScope === "all"
      ? undefined
      : [...versionPanelVersions]
          .reverse()
          .find(
            (version) =>
              version.kind === "mockup" &&
              version.pass?.styleId === mockupScope,
          );
  const scopedPanelVersionId =
    scopedPanelMockup?.id ||
    latestMockupByCutId.get(versionPanelCut?.id || "")?.pass?.id ||
    "source:canonical";
  const versionPanelSelected =
    versionPanelVersions.find(
      (version) =>
        version.id ===
        (selectedVersionByCutId[versionPanelCut?.id || ""] ||
          scopedPanelVersionId),
    ) ||
    versionPanelVersions.find(
      (version) => version.id === scopedPanelVersionId,
    ) ||
    versionPanelVersions[0];
  const versionPanelMockupCount =
    mockupVersionsByCutId.get(versionPanelCut?.id || "")?.length || 0;

  function updateCardScrub(
    event: ReactPointerEvent<HTMLDivElement>,
    cut: MockupCut,
  ) {
    if (cut.isGap) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const fraction =
      bounds.width > 0 ? (event.clientX - bounds.left) / bounds.width : 0;
    setCardScrub({
      shotId: cut.shotId,
      ...scrubAtFraction(cut, fps, fraction),
    });
  }

  function captureThumbnail(
    cut: MockupCut,
    baseThreadId: string,
    requestedTime: number,
    video: HTMLVideoElement,
  ) {
    if (!video.videoWidth || !video.videoHeight) return;
    try {
      const snapped = scrubAtTime(cut, fps, requestedTime);
      const baseThread = (threadsByCutId.get(cut.id) || []).find(
        (thread) => thread.id === baseThreadId,
      );
      const sameSourceFrame =
        baseThread &&
        scrubAtTime(cut, fps, baseThread.sourceTime).frame === snapped.frame;
      const threadId = sameSourceFrame
        ? baseThreadId
        : `frame-${snapped.frame}`;
      const scale = Math.min(1, 1280 / video.videoWidth);
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Canvas is unavailable.");
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const frame: ThumbnailFrame = {
        image: canvas.toDataURL("image/jpeg", 0.9),
        time: snapped.time,
        frame: snapped.frame,
        threadId,
      };
      setSessionFramesByCutId((current) => ({
        ...current,
        [cut.id]: {
          ...(current[cut.id] || {}),
          [threadId]: frame,
        },
      }));
      setSelectedVersionByCutId((current) => ({
        ...current,
        [cut.id]: `source:${threadId}`,
      }));
      setCurrentThreadByCutId((current) => ({
        ...current,
        [cut.id]: threadId,
      }));
      setExpandedSourceByCutId((current) => ({
        ...current,
        [cut.id]: "",
      }));
    } catch {
      return;
    }
  }

  return (
    <div
      className={`mockup-workspace ${
        versionPanelOpen ? "right-inspector-open" : ""
      }`}
    >
      <section className="mockup-main">
        <nav
          className="feedback-sticky-nav mockup-sticky-nav"
          aria-label="Mockup library filters"
        >
          <div className="feedback-notes-index-bar mockup-filter-bar">
            <div className="feedback-scope-tabs">
              <button
                className={mockupScope === "all" ? "active" : ""}
                onClick={() => {
                  setMockupScope("all");
                  setVersionPanelOpen(false);
                }}
                aria-pressed={mockupScope === "all"}
              >
                All
                {mockupScope === "all" && (
                  <b className="feedback-nav-count">{mockups.length}</b>
                )}
              </button>
            </div>
            <div className="feedback-notes-index-tabs">
              {mockupLooks.map((look) => (
                <button
                  key={look.id}
                  className={mockupScope === look.id ? "active" : ""}
                  onClick={() => {
                    setMockupScope(look.id);
                    setVersionPanelOpen(false);
                  }}
                  aria-pressed={mockupScope === look.id}
                  title={`${look.title} · ${look.passes.length} ${
                    look.passes.length === 1 ? "revision" : "revisions"
                  }`}
                >
                  {look.title}
                </button>
              ))}
            </div>
            <label className="feedback-search feedback-top-search">
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search"
                aria-label="Search mockups"
              />
            </label>
            <label className="feedback-section-filter feedback-top-chapter">
              <select
                value={section}
                onChange={(event) => setSection(event.target.value)}
                aria-label="Mockup chapter"
              >
                <option value="ALL">Chapter</option>
                {sections.map((sectionCode) => (
                  <option value={sectionCode} key={sectionCode}>
                    {sectionCode}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </nav>

        <div className="mockup-results">
          <div className="mockup-grid">
            {mockups.map(({ item, cut, pass, mockupKey }) => {
              const versions = versionsByCutId.get(cut.id) || [];
              const defaultVersionId = pass?.id || "source:canonical";
              const selectedVersionId =
                selectedVersionByCutId[cut.id] || defaultVersionId;
              const selectedVersion =
                versions.find((version) => version.id === selectedVersionId) ||
                versions.find((version) => version.id === defaultVersionId) ||
                versions[0];
              const selectedPass = selectedVersion?.pass || null;
              const pickerOpen =
                versionPanelOpen && versionCutId === cut.id;
              return (
                <article className="mockup-card" key={mockupKey}>
                  <div
                    className={`mockup-frame ${cut.isGap ? "gap" : ""} ${
                      pickerOpen ? "picker-open" : ""
                    } ${
                      cardScrub?.shotId === cut.shotId
                        ? "scrub-previewing"
                        : ""
                    }`}
                    title={
                      cut.isGap
                        ? "Intentional blank"
                        : selectedVersion?.kind === "mockup"
                          ? "Move left to right to reveal and scrub the original shot; click to open image choices"
                          : "Move left to right to scrub the original shot; click to open image choices"
                    }
                    onPointerEnter={(event) => {
                      setCardScrubReadyShotId("");
                      updateCardScrub(event, cut);
                    }}
                    onPointerMove={(event) => updateCardScrub(event, cut)}
                    onPointerLeave={() => {
                      setCardScrub(null);
                      setCardScrubReadyShotId("");
                    }}
                  >
                    {cut.isGap && !item ? (
                      <i>INTENTIONAL BLANK</i>
                    ) : (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={selectedVersion?.image || cut.thumbnail}
                        alt={
                          selectedVersion?.kind === "mockup"
                            ? `Mockup ${selectedVersion.ordinal} for ${cut.id}`
                            : `Reference frame for ${cut.id}`
                        }
                        loading="lazy"
                      />
                    )}
                    {!cut.isGap &&
                      cardScrub?.shotId === cut.shotId && (
                        <video
                          ref={cardScrubVideoRef}
                          className={
                            cardScrubReadyShotId === cut.shotId
                              ? "ready"
                              : ""
                          }
                          src={cut.scrubProxy || hoverProxy}
                          poster={cut.thumbnail}
                          muted
                          playsInline
                          preload="auto"
                          aria-hidden="true"
                          onSeeked={() =>
                            setCardScrubReadyShotId(cut.shotId)
                          }
                        />
                      )}
                    {!cut.isGap && (
                      <span
                        className="mockup-card-scrub-track"
                        aria-hidden="true"
                      >
                        <i
                          style={{
                            width: `${
                              cardScrub?.shotId === cut.shotId
                                ? cardScrub.fraction * 100
                                : 0
                            }%`,
                          }}
                        />
                      </span>
                    )}
                    {selectedVersion?.kind === "mockup" && (
                      <span className="mockup-kind">
                        Mockup {selectedVersion.ordinal}
                      </span>
                    )}
                    {!cut.isGap && (
                      <button
                        type="button"
                        className="mockup-version-trigger"
                        aria-label={`Open image choices for ${cut.id}. Current: ${
                          selectedVersion?.kind === "mockup"
                            ? `Mockup ${selectedVersion.ordinal}`
                            : "source frame"
                        }`}
                        aria-haspopup="listbox"
                        aria-expanded={pickerOpen}
                        aria-controls="mockup-version-panel-content"
                        onClick={() => {
                          if (pickerOpen) {
                            setVersionPanelOpen(false);
                            return;
                          }
                          setVersionCutId(cut.id);
                          setVersionPanelOpen(true);
                        }}
                      />
                    )}
                  </div>
                  <ShotCardDetails
                    chapter={cut.sectionCode}
                    name={cut.shotName}
                    duration={cut.duration}
                    cutNumber={cut.id}
                    timecode={cut.timecode}
                    description={cut.description}
                    tags={
                      selectedPass ? (
                        <>
                          <span>{lookTitle(selectedPass.styleId)}</span>
                          <span>Mockup {selectedVersion?.ordinal}</span>
                        </>
                      ) : undefined
                    }
                  />
                  {selectedVersion?.kind === "mockup" &&
                    (selectedVersion.mockupName ||
                      selectedVersion.mockupDescription) && (
                      <div className="mockup-card-caption">
                        <b>
                          {selectedVersion.mockupName ||
                            selectedVersion.label}
                        </b>
                        {selectedVersion.mockupDescription ? (
                          <p>{selectedVersion.mockupDescription}</p>
                        ) : null}
                      </div>
                    )}
                </article>
              );
            })}
          </div>
          {!mockups.length && (
            <p className="mockup-no-results">No mockups match this view.</p>
          )}
        </div>
      </section>
      <RightInspectorPanel
        open={versionPanelOpen}
        onOpenChange={setVersionPanelOpen}
        label="Versions"
        panelClassName="mockup-version-inspector"
        contentClassName="mockup-version-panel-content"
        contentId="mockup-version-panel-content"
      >
        {versionPanelCut && versionPanelSelected ? (
          <>
            <header className="mockup-version-panel-header">
              <small>
                {versionPanelCut.id} · {versionPanelMockupCount} mockups ·{" "}
                {versionPanelThreads.length}{" "}
                {versionPanelThreads.length === 1 ? "frame" : "frames"}
              </small>
              <h2>{versionPanelCut.shotName}</h2>
            </header>
            <p className="mockup-version-current">
              Current pick
              <b>
                {versionPanelSelected.kind === "mockup"
                  ? `Mockup ${versionPanelSelected.ordinal} · ${versionPanelSelected.label}`
                  : versionPanelSelected.label}
              </b>
            </p>
            <div
              className="mockup-version-list"
              role="listbox"
              aria-label={`Image choices for ${versionPanelCut.id}`}
            >
              {versionPanelThreads.map((thread, threadIndex) => {
                const expanded =
                  expandedSourceByCutId[versionPanelCut.id] === thread.id;
                const current =
                  currentThreadByCutId[versionPanelCut.id] === thread.id;
                return (
                  <section
                    className="mockup-frame-thread"
                    role="group"
                    aria-label={`Frame thread ${threadIndex + 1}`}
                    key={`${versionPanelCut.id}:${thread.id}`}
                  >
                    <header className="mockup-frame-thread-header">
                      <b>Frame thread {threadIndex + 1}</b>
                      <span>
                        {thread.mockups.length}{" "}
                        {thread.mockups.length === 1 ? "mockup" : "mockups"}
                      </span>
                    </header>
                    <OriginalFrameCard
                      cut={versionPanelCut}
                      fps={fps}
                      hoverProxy={hoverProxy}
                      thread={thread}
                      threadIndex={threadIndex}
                      current={current}
                      expanded={expanded}
                      onActivate={() => {
                        setExpandedSourceByCutId((currentExpanded) => ({
                          ...currentExpanded,
                          [versionPanelCut.id]: thread.id,
                        }));
                      }}
                      onCancel={() => {
                        setExpandedSourceByCutId((currentExpanded) => ({
                          ...currentExpanded,
                          [versionPanelCut.id]: "",
                        }));
                      }}
                      onCapture={(threadId, time, video) =>
                        captureThumbnail(
                          versionPanelCut,
                          threadId,
                          time,
                          video,
                        )
                      }
                    />
                    {thread.mockups.map((version) => {
                      const selected =
                        version.id === versionPanelSelected.id;
                      return (
                        <button
                          type="button"
                          role="option"
                          aria-selected={selected}
                          className={`mockup-version-card ${
                            selected ? "selected" : ""
                          }`}
                          key={version.id}
                          onClick={() => {
                            setSelectedVersionByCutId((currentSelected) => ({
                              ...currentSelected,
                              [versionPanelCut.id]: version.id,
                            }));
                            persistMockupThumbnailSelection(
                              versionPanelCut.id,
                              version.id,
                            );
                            setCurrentThreadByCutId((currentThreads) => ({
                              ...currentThreads,
                              [versionPanelCut.id]: version.threadId,
                            }));
                          }}
                        >
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={version.image}
                            alt={`Mockup ${version.ordinal} for ${versionPanelCut.id}`}
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
                        </button>
                      );
                    })}
                  </section>
                );
              })}
            </div>
          </>
        ) : (
          <p className="mockup-no-results">
            Choose a shot to see its images.
          </p>
        )}
      </RightInspectorPanel>
    </div>
  );
}
