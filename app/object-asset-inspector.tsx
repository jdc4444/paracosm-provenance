"use client";

import {
  createElement,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import pianoPerformanceData from "../data/piano-performance-vid5.json";
import {
  productionNoteKindLabel,
  productionNotesForObject,
  productionNoteStatusLabel,
} from "./object-production-metadata";
import {
  reconstructionAssembliesForObject,
  reconstructionModeLabel,
  reconstructionPriorityLabel,
  reconstructionStrategyForObject,
} from "./object-reconstruction-metadata";
import { RightInspectorPanel } from "./right-inspector-panel";

export type ObjectItem = {
  id: string;
  name: string;
  category: string;
  image: string;
  sourceFiles: string[];
  alternateImages?: Array<{
    id: string;
    label: string;
    image: string;
    description?: string;
  }>;
};

export type Object3DVersion = {
  id: string;
  label: string;
  provider: string;
  model: string;
  thumbnail: string;
  createdAt: string;
  taskId: string;
  faces: number;
  vertices: number;
  status: "ready" | "review" | "needs-fix";
  note: string;
};

export type Object3DRecord = {
  objectId: string;
  primaryVersionId?: string;
  versions: Object3DVersion[];
  clothProofs?: Array<{
    id: string;
    label: string;
    solver: string;
    image: string;
    closeupImage?: string;
    scene: string;
    model?: string;
    createdAt: string;
    collisionObject: string;
    proofFrame: number;
    resolution: string;
    status: "promising" | "needs-prep";
    license?: string;
    note: string;
  }>;
  simulations?: Array<{
    id: string;
    label: string;
    solver: string;
    video: string;
    poster: string;
    settledModel: string;
    scene: string;
    createdAt: string;
    collisionObject: string;
    settledFrame: number;
    note: string;
  }>;
};

export function primaryObject3DVersion(record: Object3DRecord | null) {
  if (!record) return null;
  return (
    record.versions.find(
      (version) => version.id === record.primaryVersionId,
    ) ||
    record.versions.at(-1) ||
    null
  );
}

type ModelTurntableProps = {
  src: string;
  poster: string;
  alt: string;
  className?: string;
  interactive?: boolean;
  motion?: boolean;
  motionSeed?: number;
  animationName?: string;
  environmentImage?: string;
  exposure?: number;
  shadowIntensity?: number;
  toneMapping?:
    | "auto"
    | "aces"
    | "agx"
    | "reinhard"
    | "cineon"
    | "linear"
    | "none";
  onViewerChange?: (viewer: ModelViewerPlaybackElement | null) => void;
};

type PianoChordTuple = [
  name: string,
  start: number,
  end: number,
  velocity: number,
  midiNotes: number[],
];

type PianoPerformanceManifest = {
  label: string;
  durationSeconds: number;
  summary: {
    chordEvents: number;
    distinctKeys: number;
    harmonicCenter: string;
    primaryChords: string[];
  };
  chords: PianoChordTuple[];
};

type ModelViewerPlaybackElement = HTMLElement & {
  loaded?: boolean;
  availableAnimations: string[];
  animationName?: string;
  currentTime: number;
  duration: number;
  paused: boolean;
  play: (options?: { repetitions: number; pingpong: boolean }) => void;
  pause: () => void;
};

type WindowWithWebkitAudio = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };

const pianoPerformance = pianoPerformanceData as PianoPerformanceManifest;
const PIANO_ANIMATION_NAME = "VID_5 Performance";

function sourceImagePath(sourceFile: string) {
  const stem = sourceFile.replace(/\.[^.]+$/, "");
  return `/archive/objects/sources/${stem}.jpg`;
}

function objectIdLabel(objectId: string) {
  return objectId
    .split("-")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

export function ModelTurntable({
  src,
  poster,
  alt,
  className = "",
  interactive = false,
  motion = true,
  motionSeed = 0,
  animationName,
  environmentImage = "neutral",
  exposure = 1,
  shadowIntensity = 0.9,
  toneMapping = "auto",
  onViewerChange,
}: ModelTurntableProps) {
  const turntableRef = useRef<HTMLDivElement | null>(null);
  const [viewerReady, setViewerReady] = useState(false);
  const [modelLoaded, setModelLoaded] = useState(false);

  useEffect(() => {
    let active = true;
    void import("@google/model-viewer").then(() => {
      if (active) setViewerReady(true);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!viewerReady) return;
    const viewer =
      turntableRef.current?.querySelector<ModelViewerPlaybackElement>(
        "model-viewer",
      );
    if (!viewer) return;

    const revealModel = () => setModelLoaded(true);
    viewer.addEventListener("load", revealModel);
    if ("loaded" in viewer && viewer.loaded === true) revealModel();
    return () => viewer.removeEventListener("load", revealModel);
  }, [src, viewerReady]);

  useEffect(() => {
    if (!viewerReady) {
      onViewerChange?.(null);
      return;
    }
    const viewer =
      turntableRef.current?.querySelector<ModelViewerPlaybackElement>(
        "model-viewer",
      ) || null;
    onViewerChange?.(viewer);
    return () => onViewerChange?.(null);
  }, [onViewerChange, src, viewerReady]);

  useEffect(() => {
    if (!viewerReady || !modelLoaded || !motion) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let animationFrame = 0;
    const phase = motionSeed * 0.83;
    const animate = (time: number) => {
      const viewer =
        turntableRef.current?.querySelector<HTMLElement>("model-viewer");
      if (viewer) {
        const yaw = Math.sin(time / 3100 + phase) * 11;
        viewer.setAttribute("camera-orbit", `${yaw.toFixed(2)}deg 75deg auto`);
      }
      animationFrame = window.requestAnimationFrame(animate);
    };
    animationFrame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [modelLoaded, motion, motionSeed, viewerReady]);

  return (
    <div
      ref={turntableRef}
      className={`object-model-turntable ${
        modelLoaded ? "model-loaded" : ""
      } ${interactive ? "interactive" : ""} ${className}`.trim()}
      role="img"
      aria-label={alt}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="object-model-poster" src={poster} alt="" />
      {viewerReady &&
        createElement("model-viewer", {
          src,
          poster,
          alt: "",
          class: "object-model-element",
          reveal: "auto",
          loading: "lazy",
          "camera-controls": interactive,
          "camera-orbit": "0deg 75deg auto",
          "animation-name": animationName,
          exposure,
          "tone-mapping": toneMapping,
          "shadow-intensity": shadowIntensity,
          "shadow-softness": "0.8",
          "environment-image": environmentImage,
          "interaction-prompt": "none",
          "touch-action": interactive ? "pan-y" : "none",
          tabIndex: interactive ? 0 : -1,
        })}
    </div>
  );
}

function formatPerformanceTime(seconds: number) {
  const safeSeconds = Math.max(0, Math.round(seconds));
  return `${Math.floor(safeSeconds / 60)}:${String(safeSeconds % 60).padStart(
    2,
    "0",
  )}`;
}

function PianoPerformancePlayer({
  src,
  poster,
  alt,
}: {
  src: string;
  poster: string;
  alt: string;
}) {
  const viewerRef = useRef<ModelViewerPlaybackElement | null>(null);
  const viewerLoadCleanupRef = useRef<(() => void) | null>(null);
  const [animationReady, setAnimationReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const audioContextRef = useRef<AudioContext | null>(null);
  const activeOscillatorsRef = useRef(new Set<OscillatorNode>());
  const previousTimeRef = useRef(0);

  const stopConfirmationTones = useCallback(() => {
    for (const oscillator of activeOscillatorsRef.current) {
      try {
        oscillator.stop();
      } catch {
        // The short confirmation tone may already have ended.
      }
    }
    activeOscillatorsRef.current.clear();
  }, []);

  const ensureAudioContext = useCallback(async () => {
    if (!audioContextRef.current) {
      const AudioContextConstructor =
        window.AudioContext ||
        (window as WindowWithWebkitAudio).webkitAudioContext;
      if (!AudioContextConstructor) return null;
      audioContextRef.current = new AudioContextConstructor();
    }
    if (audioContextRef.current.state === "suspended") {
      await audioContextRef.current.resume();
    }
    return audioContextRef.current;
  }, []);

  const soundMidi = useCallback(
    async (
      midi: number,
      start: number,
      end: number,
      velocity: number,
    ) => {
      const context = await ensureAudioContext();
      if (!context) return;
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const now = context.currentTime;
      const audibleLength = Math.min(1.15, Math.max(0.12, end - start));
      const peak = 0.018 + (velocity / 127) * 0.025;
      oscillator.type = "triangle";
      oscillator.frequency.setValueAtTime(
        440 * 2 ** ((midi - 69) / 12),
        now,
      );
      gain.gain.setValueAtTime(0.0001, now);
      gain.gain.exponentialRampToValueAtTime(peak, now + 0.008);
      gain.gain.exponentialRampToValueAtTime(
        Math.max(0.004, peak * 0.34),
        now + Math.min(0.16, audibleLength * 0.5),
      );
      gain.gain.exponentialRampToValueAtTime(
        0.0001,
        now + audibleLength + 0.18,
      );
      oscillator.connect(gain).connect(context.destination);
      oscillator.addEventListener("ended", () => {
        activeOscillatorsRef.current.delete(oscillator);
        oscillator.disconnect();
        gain.disconnect();
      });
      activeOscillatorsRef.current.add(oscillator);
      oscillator.start(now);
      oscillator.stop(now + audibleLength + 0.2);
    },
    [ensureAudioContext],
  );

  const handleViewerChange = useCallback(
    (nextViewer: ModelViewerPlaybackElement | null) => {
      viewerLoadCleanupRef.current?.();
      viewerLoadCleanupRef.current = null;
      viewerRef.current = nextViewer;
      if (!nextViewer) {
        setAnimationReady(false);
        return;
      }
      const checkAnimation = () => {
        const ready =
          nextViewer.availableAnimations.includes(PIANO_ANIMATION_NAME);
        setAnimationReady(ready);
        if (ready) nextViewer.animationName = PIANO_ANIMATION_NAME;
      };
      nextViewer.addEventListener("load", checkAnimation);
      viewerLoadCleanupRef.current = () =>
        nextViewer.removeEventListener("load", checkAnimation);
      if (nextViewer.loaded) checkAnimation();
    },
    [],
  );

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !playing) return;
    let animationFrame = 0;
    const tick = () => {
      const nextTime = Math.min(
        viewer.currentTime,
        pianoPerformance.durationSeconds,
      );
      const previousTime =
        nextTime < previousTimeRef.current ? 0 : previousTimeRef.current;
      if (soundEnabled) {
        for (const chord of pianoPerformance.chords) {
          if (chord[1] > previousTime && chord[1] <= nextTime + 0.008) {
            for (const midi of chord[4]) {
              void soundMidi(midi, chord[1], chord[2], chord[3]);
            }
          }
        }
      }
      previousTimeRef.current = nextTime;
      setCurrentTime(nextTime);
      if (
        viewer.paused ||
        nextTime >= pianoPerformance.durationSeconds - 0.01
      ) {
        setPlaying(false);
        stopConfirmationTones();
        return;
      }
      animationFrame = window.requestAnimationFrame(tick);
    };
    animationFrame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [playing, soundEnabled, soundMidi, stopConfirmationTones]);

  useEffect(
    () => () => {
      viewerLoadCleanupRef.current?.();
      viewerRef.current?.pause();
      stopConfirmationTones();
      void audioContextRef.current?.close();
    },
    [stopConfirmationTones],
  );

  const togglePlayback = async () => {
    const viewer = viewerRef.current;
    if (!viewer || !animationReady) return;
    if (playing) {
      viewer.pause();
      setPlaying(false);
      stopConfirmationTones();
      return;
    }
    if (currentTime >= pianoPerformance.durationSeconds - 0.05) {
      viewer.currentTime = 0;
      previousTimeRef.current = 0;
      setCurrentTime(0);
    } else {
      previousTimeRef.current = viewer.currentTime;
    }
    if (soundEnabled) await ensureAudioContext();
    viewer.animationName = PIANO_ANIMATION_NAME;
    viewer.play({ repetitions: 1, pingpong: false });
    setPlaying(true);
  };

  const restart = () => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.pause();
    viewer.currentTime = 0;
    previousTimeRef.current = 0;
    setCurrentTime(0);
    setPlaying(false);
    stopConfirmationTones();
  };

  const seek = (nextTime: number) => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    viewer.currentTime = nextTime;
    previousTimeRef.current = nextTime;
    setCurrentTime(nextTime);
    stopConfirmationTones();
  };

  return (
    <div className="piano-performance-player">
      <ModelTurntable
        className="three-d-inspector-viewer"
        src={src}
        poster={poster}
        alt={alt}
        interactive
        motion={false}
        animationName={PIANO_ANIMATION_NAME}
        onViewerChange={handleViewerChange}
      />
      <div className="piano-performance-controls">
        <div className="piano-performance-actions">
          <button
            type="button"
            className="piano-performance-play"
            onClick={() => void togglePlayback()}
            disabled={!animationReady}
          >
            {playing ? "Pause" : "Play performance"}
          </button>
          <button type="button" onClick={restart} disabled={!animationReady}>
            Restart
          </button>
          <button
            type="button"
            className={soundEnabled ? "sound-on" : ""}
            aria-pressed={soundEnabled}
            onClick={() => {
              const next = !soundEnabled;
              setSoundEnabled(next);
              if (next) void ensureAudioContext();
              else stopConfirmationTones();
            }}
          >
            MIDI sound {soundEnabled ? "on" : "off"}
          </button>
        </div>
        <label className="piano-performance-scrubber">
          <span className="sr-only">Performance position</span>
          <input
            type="range"
            min="0"
            max={pianoPerformance.durationSeconds}
            step="0.01"
            value={currentTime}
            onChange={(event) => seek(Number(event.target.value))}
            disabled={!animationReady}
          />
          <b>
            {formatPerformanceTime(currentTime)} /{" "}
            {formatPerformanceTime(pianoPerformance.durationSeconds)}
          </b>
        </label>
        <div className="piano-performance-summary">
          <span>{pianoPerformance.summary.harmonicCenter}</span>
          <span>{pianoPerformance.summary.primaryChords.join(" · ")}</span>
          <span>{pianoPerformance.summary.chordEvents} chords</span>
          <span>{pianoPerformance.summary.distinctKeys} keys</span>
        </div>
        <p>
          Eight waveform attacks checked against the performance frames. Sound
          is an optional confirmation synth; every chord moves once and
          sustains.
        </p>
      </div>
    </div>
  );
}

function Stat({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <span>
      <small>{label}</small>
      <b>{children}</b>
    </span>
  );
}

export function ObjectAssetInspector({
  open,
  onOpenChange,
  object,
  record,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  object: ObjectItem | null;
  record: Object3DRecord | null;
}) {
  const primaryVersion = primaryObject3DVersion(record);
  const [versionSelection, setVersionSelection] = useState({
    objectId: "",
    versionId: "",
  });
  const selectedVersionId =
    versionSelection.objectId === object?.id
      ? versionSelection.versionId
      : primaryVersion?.id || "";
  const selectedVersion =
    record?.versions.find((version) => version.id === selectedVersionId) ||
    primaryVersion;
  const productionNotes = productionNotesForObject(object?.id);
  const reconstructionStrategy = reconstructionStrategyForObject(object);
  const reconstructionAssemblies = reconstructionAssembliesForObject(
    object?.id,
  );
  const clothProofs = record?.clothProofs || [];
  const simulations = record?.simulations || [];

  return (
    <RightInspectorPanel
      open={open}
      onOpenChange={onOpenChange}
      label="Object"
      panelClassName="mockup-version-inspector object-asset-inspector"
      contentClassName="mockup-version-panel-content object-asset-panel-content"
      contentId="object-asset-panel"
    >
      {object ? (
        <>
          <header className="mockup-version-panel-header">
            <small>
              {object.category} · {object.sourceFiles.length}{" "}
              {object.sourceFiles.length === 1 ? "source" : "sources"} ·{" "}
              {record?.versions.length || 0} 3D
              {simulations.length > 0
                ? ` · ${simulations.length} ${
                    simulations.length === 1 ? "simulation" : "simulations"
                  }`
                : ""}
              {clothProofs.length > 0
                ? ` · ${clothProofs.length} ${
                    clothProofs.length === 1 ? "cloth proof" : "cloth proofs"
                  }`
                : ""}
            </small>
            <h2>{object.name}</h2>
          </header>

          {selectedVersion && (
            <section className="object-asset-section object-primary-3d-section">
              <header>
                <b>3D model</b>
                <label className="object-version-select">
                  <span className="sr-only">
                    3D version for {object.name}
                  </span>
                  <select
                    aria-label={`3D version for ${object.name}`}
                    value={selectedVersion.id}
                    onChange={(event) =>
                      setVersionSelection({
                        objectId: object.id,
                        versionId: event.target.value,
                      })
                    }
                  >
                    {record?.versions.map((version) => (
                      <option key={version.id} value={version.id}>
                        {version.label}
                      </option>
                    ))}
                  </select>
                </label>
              </header>
              {object.id === "piano" &&
              selectedVersion.id === "blender-performance-v4" ? (
                <PianoPerformancePlayer
                  key={selectedVersion.model}
                  src={selectedVersion.model}
                  poster={selectedVersion.thumbnail}
                  alt={`Interactive animated 3D model of ${object.name}`}
                />
              ) : (
                <ModelTurntable
                  key={selectedVersion.model}
                  className="three-d-inspector-viewer"
                  src={selectedVersion.model}
                  poster={selectedVersion.thumbnail}
                  alt={`Interactive 3D model of ${object.name}`}
                  interactive
                  motion={false}
                />
              )}
              <div className="three-d-version-stats">
                <Stat label="Faces">
                  {selectedVersion.faces.toLocaleString()}
                </Stat>
                <Stat label="Vertices">
                  {selectedVersion.vertices.toLocaleString()}
                </Stat>
                <Stat label="Status">
                  {selectedVersion.status === "ready"
                    ? "Ready"
                    : selectedVersion.status === "needs-fix"
                      ? "Needs fix"
                      : "Review"}
                </Stat>
              </div>
              <p className="three-d-version-note">{selectedVersion.note}</p>
            </section>
          )}

          {clothProofs.length > 0 && (
            <section className="object-asset-section object-cloth-proof-section">
              <header>
                <b>Cloth proof</b>
                <span>High-res static · {clothProofs[0].resolution}</span>
              </header>
              <div className="object-cloth-proof-list">
                {clothProofs.map((proof) => (
                  <article className="object-cloth-proof-card" key={proof.id}>
                    <header>
                      <div>
                        <b>{proof.label}</b>
                        <span>{proof.solver}</span>
                      </div>
                      <span
                        className={`object-cloth-proof-status is-${proof.status}`}
                      >
                        {proof.status === "promising"
                          ? "Promising"
                          : "Needs mesh prep"}
                      </span>
                    </header>
                    <div className="object-cloth-proof-image-list">
                      <figure className="object-cloth-proof-image">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={proof.image}
                          alt={`${object.name} — ${proof.label}, medium shot`}
                        />
                        <figcaption>Medium</figcaption>
                      </figure>
                      {proof.closeupImage && (
                        <figure className="object-cloth-proof-image">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={proof.closeupImage}
                            alt={`${object.name} — ${proof.label}, construction closeup`}
                          />
                          <figcaption>Closeup</figcaption>
                        </figure>
                      )}
                    </div>
                    <p>{proof.note}</p>
                    <dl>
                      <div>
                        <dt>Collision</dt>
                        <dd>{proof.collisionObject}</dd>
                      </div>
                      <div>
                        <dt>Proof frame</dt>
                        <dd>{proof.proofFrame}</dd>
                      </div>
                      <div>
                        <dt>Resolution</dt>
                        <dd>{proof.resolution}</dd>
                      </div>
                      {proof.license && (
                        <div>
                          <dt>License</dt>
                          <dd>{proof.license}</dd>
                        </div>
                      )}
                    </dl>
                    <div
                      className={`object-cloth-proof-links ${
                        proof.closeupImage ? "has-closeup" : ""
                      } ${proof.closeupImage && proof.model ? "has-model" : ""}`}
                    >
                      <a href={proof.image} download>
                        Medium
                      </a>
                      {proof.closeupImage && (
                        <a href={proof.closeupImage} download>
                          Closeup
                        </a>
                      )}
                      <a href={proof.scene} download>
                        Scene
                      </a>
                      {proof.model && (
                        <a href={proof.model} download>
                          Geometry
                        </a>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}

          {simulations.length > 0 && (
            <section className="object-asset-section object-simulation-section">
              <header>
                <b>Cloth simulation</b>
                <span>
                  {simulations.length}{" "}
                  {simulations.length === 1 ? "solve" : "solves"}
                </span>
              </header>
              <div className="object-simulation-list">
                {simulations.map((simulation) => (
                  <article className="object-simulation-card" key={simulation.id}>
                    <header>
                      <div>
                        <b>{simulation.label}</b>
                        <span>{simulation.solver}</span>
                      </div>
                      <time dateTime={simulation.createdAt}>
                        {simulation.createdAt}
                      </time>
                    </header>
                    <div className="object-simulation-loop">
                      <video
                        autoPlay
                        loop
                        muted
                        playsInline
                        preload="auto"
                        poster={simulation.poster}
                        disablePictureInPicture
                        aria-label={`${object.name} — ${simulation.label}`}
                      >
                        <source src={simulation.video} type="video/mp4" />
                      </video>
                      <span aria-hidden="true">● Cloth loop</span>
                    </div>
                    <p>{simulation.note}</p>
                    <dl>
                      <div>
                        <dt>Collision</dt>
                        <dd>{simulation.collisionObject}</dd>
                      </div>
                      <div>
                        <dt>Settled frame</dt>
                        <dd>{simulation.settledFrame}</dd>
                      </div>
                    </dl>
                    <div className="object-simulation-links">
                      <a href={simulation.settledModel} download>
                        Settled GLB
                      </a>
                      <a href={simulation.scene} download>
                        Blender scene
                      </a>
                    </div>
                  </article>
                ))}
              </div>
            </section>
          )}

          <section className="object-asset-section object-white-background-section">
            <header>
              <b>White-background images</b>
              <span>
                {1 + (object.alternateImages?.length || 0)}{" "}
                {object.alternateImages?.length ? "studies" : "image"}
              </span>
            </header>
            <div className="object-alternate-image-list">
              <figure>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={object.image} alt={`${object.name} cutout`} />
                <figcaption>
                  <b>Original cutout</b>
                  <span>Primary isolated object reference</span>
                </figcaption>
              </figure>
              {object.alternateImages?.map((alternate) => (
                <figure key={alternate.id}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={alternate.image}
                    alt={`${object.name} — ${alternate.label}`}
                  />
                  <figcaption>
                    <b>{alternate.label}</b>
                    {alternate.description && (
                      <span>{alternate.description}</span>
                    )}
                  </figcaption>
                </figure>
              ))}
            </div>
          </section>

          <section className="object-asset-section object-source-section">
            <header>
              <b>Source image</b>
              <span>
                {object.sourceFiles.length}{" "}
                {object.sourceFiles.length === 1 ? "reference" : "references"}
              </span>
            </header>
            <div className="object-source-list">
              {object.sourceFiles.map((sourceFile) => (
                <figure key={sourceFile}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={sourceImagePath(sourceFile)}
                    alt={`${object.name} source reference`}
                    loading="lazy"
                  />
                  <figcaption>{sourceFile}</figcaption>
                </figure>
              ))}
            </div>
          </section>

          {reconstructionStrategy && (
            <section className="object-asset-section object-reconstruction-section">
              <header>
                <b>3D reconstruction</b>
                <span>
                  {reconstructionModeLabel(reconstructionStrategy.mode)} ·{" "}
                  {reconstructionPriorityLabel(
                    reconstructionStrategy.priority,
                  )}
                </span>
              </header>
              <article className="object-reconstruction-card">
                <div className="object-reconstruction-audit">
                  <b>
                    {reconstructionStrategy.inputSourceFiles.length} source{" "}
                    {reconstructionStrategy.inputSourceFiles.length === 1
                      ? "input"
                      : "inputs"}{" "}
                    mapped
                  </b>
                  <span>ready</span>
                </div>
                <p>{reconstructionStrategy.summary}</p>
                <dl className="object-reconstruction-stats">
                  <div>
                    <dt>Inputs</dt>
                    <dd>{reconstructionStrategy.inputSourceFiles.length}</dd>
                  </div>
                  <div>
                    <dt>Assemblies</dt>
                    <dd>{reconstructionAssemblies.length}</dd>
                  </div>
                  <div>
                    <dt>Related</dt>
                    <dd>{reconstructionStrategy.relatedObjectIds.length}</dd>
                  </div>
                </dl>
                <div className="object-reconstruction-block">
                  <b>Modeling order</b>
                  <ol>
                    {reconstructionStrategy.modelingSteps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                </div>
                {reconstructionStrategy.captureNeeds.length > 0 && (
                  <div className="object-reconstruction-block">
                    <b>Useful next angles</b>
                    <div className="object-reconstruction-chips">
                      {reconstructionStrategy.captureNeeds.map((need) => (
                        <span key={need}>{need}</span>
                      ))}
                    </div>
                  </div>
                )}
                {reconstructionStrategy.cautions.length > 0 && (
                  <div className="object-reconstruction-block object-reconstruction-cautions">
                    <b>Cautions</b>
                    <ul>
                      {reconstructionStrategy.cautions.map((caution) => (
                        <li key={caution}>{caution}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </article>

              {reconstructionAssemblies.map((assembly) => {
                const placement = assembly.placements?.find(
                  (item) => item.objectId === object.id,
                );
                return (
                  <article
                    className="object-assembly-card"
                    key={assembly.id}
                  >
                    <div>
                      <span>Assembly</span>
                      <b>{assembly.name}</b>
                    </div>
                    <p>{assembly.intent}</p>
                    {placement && (
                      <strong className="object-placement-badge">
                        {placement.window} window · {placement.level} · position{" "}
                        {placement.order}
                      </strong>
                    )}
                    {object.id === assembly.id &&
                      assembly.placements?.length && (
                        <strong className="object-placement-badge">
                          {assembly.placements.length} placements mapped
                        </strong>
                      )}
                    <div className="object-reconstruction-block">
                      <b>Parts to preserve</b>
                      <div className="object-reconstruction-chips">
                        {assembly.plannedParts.map((part) => (
                          <span key={part}>{part}</span>
                        ))}
                      </div>
                    </div>
                    <div className="object-reconstruction-block">
                      <b>Relations</b>
                      <ul>
                        {assembly.relations.map((relation) => (
                          <li key={relation}>{relation}</li>
                        ))}
                      </ul>
                    </div>
                  </article>
                );
              })}
            </section>
          )}

          {productionNotes.length > 0 && (
            <section className="object-asset-section object-production-section">
              <header>
                <b>Production notes</b>
                <span>
                  {productionNotes.length}{" "}
                  {productionNotes.length === 1 ? "tracked note" : "tracked notes"}
                </span>
              </header>
              <div className="object-production-notes">
                {productionNotes.map((note) => (
                  <article
                    className={`object-production-note note-${note.kind}`}
                    key={note.id}
                  >
                    <div>
                      <span>{productionNoteKindLabel(note.kind)}</span>
                      <b>{productionNoteStatusLabel(note.status)}</b>
                    </div>
                    <h3>{note.title}</h3>
                    <p>{note.detail}</p>
                    {note.relatedObjectIds.length > 0 && (
                      <dl>
                        <dt>Related</dt>
                        <dd>
                          {note.relatedObjectIds
                            .map(objectIdLabel)
                            .join(", ")}
                        </dd>
                      </dl>
                    )}
                    {note.proposedParts.length > 0 && (
                      <div className="object-proposed-parts">
                        {note.proposedParts.map((part) => (
                          <span key={part}>{part}</span>
                        ))}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            </section>
          )}

        </>
      ) : (
        <p className="object-asset-empty">
          Choose an object name to inspect its assets.
        </p>
      )}
    </RightInspectorPanel>
  );
}
