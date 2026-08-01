"use client";

import { useEffect, useMemo, useState } from "react";
import avatarGuideData from "../data/abby-avatar-guide.json";
import avatarHead3DData from "../data/abby-head-3d-versions.json";
import avatarUnrealData from "../data/abby-unreal-myslate.json";
import {
  ModelTurntable,
  type Object3DVersion,
} from "./object-asset-inspector";
import {
  copyProductionPath,
  isLocalProductionBrowser,
  runtimeApiBase,
} from "./runtime-api";

type AvatarRender = {
  id: string;
  label: string;
  application: string;
  image: string;
  video?: string;
  width: number;
  height: number;
  animationDurationSeconds?: number;
  view: string;
  renderType: string;
  description: string;
  sourcePath: string;
  sourceFile: string;
  archivePath?: string;
  sourceUrl?: string;
  sourceUrlLabel?: string;
  fidelity: string;
  primaryVersionId?: string;
  versions?: AvatarRenderVersion[];
};

type AvatarRenderVersion = {
  id: string;
  label: string;
  image: string;
  video?: string;
  poster?: string;
  mediaType?: "image" | "video";
  width: number;
  height: number;
  note: string;
};

type RigGuideItem = {
  id: string;
  label: string;
  status: "present" | "missing";
  application: string;
  fileName: string;
  path: string;
  purpose: string;
  rules: string[];
};

type AvatarHead3DVersion = Object3DVersion & {
  inputSheet: string;
  reviewSheet: string;
};

type UnrealProofStatus =
  | "approved"
  | "candidate"
  | "diagnostic"
  | "rejected"
  | "superseded";

type UnrealProofVersion = {
  id: string;
  label: string;
  image: string;
  mediaType?: "image" | "video";
  poster?: string;
  width: number;
  height: number;
  status: UnrealProofStatus;
  note: string;
};

type UnrealProofArtifact = {
  label: string;
  kind: string;
  url: string;
  download?: boolean;
};

type UnrealProof = {
  id: string;
  label: string;
  version: string;
  status: UnrealProofStatus;
  statusLabel: string;
  interval: string;
  sourceFrames?: string;
  solveOffsets?: string;
  processedFrames?: string;
  summary: string;
  verdict: string;
  sourcePath: string;
  sourceFile: string;
  archivePath?: string;
  identity?: string;
  captureNoteLabel?: string;
  depthDiagnostic: string;
  lineage: string[];
  observations: string[];
  primaryVersionId: string;
  versions: UnrealProofVersion[];
  artifacts: UnrealProofArtifact[];
  engine?: string;
};

export type AvatarGuideSelection =
  | { kind: "head" }
  | { kind: "render"; id: string }
  | { kind: "unreal"; id: string };

const guide = avatarGuideData as {
  character: {
    id: string;
    name: string;
    sourceRoot: string;
    avatarRoot: string;
    guidePdf: string;
    identityRule: string;
  };
  summary: {
    renderCount: number;
    canonicalSystems: number;
    highestRenderLongEdge: number;
    highestSkinTextureEdge: number;
    missingExpectedPackages: number;
  };
  renders: AvatarRender[];
  identityMarkers: Array<{ label: string; description: string }>;
  rigGuide: RigGuideItem[];
  retargetSteps: Array<{
    step: number;
    label: string;
    description: string;
  }>;
};

const head3DGuide = avatarHead3DData as {
  subjectId: string;
  primaryVersionId: string;
  versions: AvatarHead3DVersion[];
};

const unrealGuide = avatarUnrealData as {
  pipeline: {
    id: string;
    label: string;
    application: string;
    capturedAt: string;
    processedAt: string;
    archiveVersion: string;
    registryVersion: string;
    archiveRoot: string;
    capture: {
      duration: string;
      rgb: string;
      depth: string;
      device: string;
      identity: string;
      rawFrames: number;
      unrealAssets: number;
    };
    gate: {
      label: string;
      status: string;
      detail: string;
    };
  };
  proofs: UnrealProof[];
};

const API = runtimeApiBase();

function formatResolution(render: AvatarRender) {
  return `${render.width.toLocaleString()} × ${render.height.toLocaleString()}`;
}

function formatVersionResolution(
  version: Pick<AvatarRenderVersion, "width" | "height">,
) {
  return `${version.width.toLocaleString()} × ${version.height.toLocaleString()}`;
}

function useSourceReveal() {
  const [sourceMessage, setSourceMessage] = useState("");

  async function revealPath(path: string, label: string) {
    setSourceMessage("");
    if (!isLocalProductionBrowser()) {
      try {
        await copyProductionPath(path);
        setSourceMessage(`Copied ${label} · open on the production Mac`);
      } catch {
        setSourceMessage("Finder actions are available in the local production app.");
      }
      return;
    }
    try {
      const response = await fetch(`${API}/api/reveal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, copyPath: true }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || "Unable to reveal source.");
      }
      setSourceMessage(`Opened in Finder · copied ${label}`);
    } catch (error) {
      setSourceMessage(
        error instanceof Error ? error.message : "Unable to reveal source.",
      );
    }
  }

  return { revealPath, sourceMessage };
}

export function AvatarGuide({
  identityMotion,
  selectedItem,
  onOpenItem,
}: {
  identityMotion: string;
  selectedItem: AvatarGuideSelection | null;
  onOpenItem: (selection: AvatarGuideSelection) => void;
}) {
  const { revealPath } = useSourceReveal();
  const presentSystems = useMemo(
    () => guide.rigGuide.filter((item) => item.status === "present"),
    [],
  );
  const missingSystems = useMemo(
    () => guide.rigGuide.filter((item) => item.status === "missing"),
    [],
  );

  return (
    <div className="avatar-guide">
      <header className="avatar-guide-hero">
        <div>
          <p className="character-kicker">CANONICAL ZK AVATAR · ABBY</p>
          <h2>Avatar guide</h2>
          <p>
            A face-first identity and production map for Abby—connected to the
            exact Blender, Cinema 4D, Unreal, texture, clothes, hair and mocap
            sources that actually exist.
          </p>
          <div className="avatar-guide-scope">
            <strong>Record Cover boundary</strong>
            <span>
              Excluded from identity evidence except the explicitly approved
              Button avatar.
            </span>
          </div>
        </div>
        <div className="avatar-guide-summary">
          <dl className="avatar-guide-metrics">
            <div>
              <dt>Face studies</dt>
              <dd>{guide.summary.renderCount}</dd>
            </div>
            <div>
              <dt>Largest render</dt>
              <dd>{guide.summary.highestRenderLongEdge / 1000}K</dd>
            </div>
            <div>
              <dt>Skin source</dt>
              <dd>{guide.summary.highestSkinTextureEdge / 1024}K</dd>
            </div>
            <div>
              <dt>Systems present</dt>
              <dd>{guide.summary.canonicalSystems}</dd>
            </div>
          </dl>
        </div>
      </header>

      <section className="avatar-render-browser">
        <header className="character-section-heading">
          <div>
            <p>CURATED FACE SOURCES</p>
            <h3>Face and identity studies</h3>
          </div>
          <small>
            User-approved front, Final Avatar deck and archived Redshift studies
            define the visual authority; rejected diagnostic close-ups stay
            excluded.
          </small>
        </header>
        <div className="avatar-render-grid">
          {head3DGuide.versions.length > 0 ? (
            <button
              type="button"
              className={selectedItem?.kind === "head" ? "active" : ""}
              onClick={() => onOpenItem({ kind: "head" })}
            >
              <span>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={
                    head3DGuide.versions.find(
                      (version) =>
                        version.id === head3DGuide.primaryVersionId,
                    )?.thumbnail || head3DGuide.versions[0].thumbnail
                  }
                  alt=""
                />
                <b>3D HEAD</b>
              </span>
              <strong>3D head model</strong>
              <small>
                {head3DGuide.versions.length} versions · interactive
              </small>
            </button>
          ) : null}
          {guide.renders.map((render) => (
            <button
              type="button"
              key={render.id}
              className={
                selectedItem?.kind === "render" &&
                render.id === selectedItem.id
                  ? "active"
                  : ""
              }
              onClick={() =>
                onOpenItem({ kind: "render", id: render.id })
              }
            >
              <span>
                {render.video ? (
                  <video
                    src={render.video}
                    poster={render.image}
                    aria-hidden="true"
                    muted
                    loop
                    playsInline
                    preload="metadata"
                    onMouseEnter={(event) => {
                      void event.currentTarget.play();
                    }}
                    onMouseLeave={(event) => {
                      event.currentTarget.pause();
                      event.currentTarget.currentTime = 0;
                    }}
                  />
                ) : (
                  <>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={render.image} alt="" />
                  </>
                )}
                <b>{render.application}</b>
              </span>
              <strong>{render.label}</strong>
              <small>
                {render.view} · {formatResolution(render)}
              </small>
            </button>
          ))}
        </div>
      </section>

      <section className="avatar-unreal-browser">
        <header className="character-section-heading">
          <div>
            <p>UNREAL · PERFORMANCE CAPTURE</p>
            <h3>Face, body and combined-performance proofs</h3>
          </div>
          <small>
            Complete source lineage, immutable proof versions and honest
            accept/candidate/diagnostic decisions. Native UE assets and source
            footage remain in the verified archive.
          </small>
        </header>
        <div className="avatar-unreal-status">
          <div>
            <span>FULL-TAKE GATE</span>
            <strong>{unrealGuide.pipeline.gate.label}</strong>
            <small>{unrealGuide.pipeline.gate.detail}</small>
          </div>
          <dl>
            <div>
              <dt>Capture</dt>
              <dd>{unrealGuide.pipeline.capture.duration}</dd>
            </div>
            <div>
              <dt>Proofs</dt>
              <dd>{unrealGuide.proofs.length}</dd>
            </div>
            <div>
              <dt>Native UE assets</dt>
              <dd>{unrealGuide.pipeline.capture.unrealAssets}</dd>
            </div>
            <div>
              <dt>Raw frames</dt>
              <dd>{unrealGuide.pipeline.capture.rawFrames.toLocaleString()}</dd>
            </div>
          </dl>
        </div>
        <div className="avatar-render-grid avatar-unreal-grid">
          {unrealGuide.proofs.map((proof) => {
            const primaryVersion =
              proof.versions.find(
                (version) => version.id === proof.primaryVersionId,
              ) || proof.versions[0];
            return (
              <button
                type="button"
                key={proof.id}
                className={
                  selectedItem?.kind === "unreal" &&
                  proof.id === selectedItem.id
                    ? "active"
                    : ""
                }
                onClick={() => onOpenItem({ kind: "unreal", id: proof.id })}
              >
                <span>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={primaryVersion.poster || primaryVersion.image}
                    alt=""
                    loading="lazy"
                  />
                  <b>UE · {proof.version}</b>
                  <em className={`avatar-unreal-tone ${proof.status}`}>
                    {proof.statusLabel}
                  </em>
                </span>
                <strong>{proof.label}</strong>
                <small>
                  {proof.interval} · {proof.versions.length}{" "}
                  {proof.versions.length === 1 ? "view" : "versions"}
                </small>
              </button>
            );
          })}
        </div>
      </section>

      <section className="avatar-motion-anchor" aria-label="Abby identity anchor">
        <div className="avatar-motion-anchor-media">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={identityMotion}
            alt="Abby final avatar identity motion study"
          />
          <span>IDENTITY ANCHOR</span>
        </div>
        <div className="avatar-motion-anchor-copy">
          <p>FINAL AVATAR MOTION STUDY</p>
          <h3>Identity in motion</h3>
          <span>
            Use this movement reference for face proportions, silhouette and
            identity consistency after reviewing the higher-resolution still
            renders above.
          </span>
        </div>
      </section>

      <section className="avatar-identity">
        <header className="character-section-heading">
          <div>
            <p>IDENTITY CHECK</p>
            <h3>Visible Abby markers</h3>
          </div>
          <small>
            Appearance evidence only—not personality, story or expression canon.
          </small>
        </header>
        <div className="avatar-identity-grid">
          {guide.identityMarkers.map((marker, index) => (
            <article key={marker.label}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <h4>{marker.label}</h4>
              <p>{marker.description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="avatar-rig-map">
        <header className="character-section-heading">
          <div>
            <p>PRODUCTION SOURCES</p>
            <h3>Which Abby file to use</h3>
          </div>
          <button
            type="button"
            onClick={() =>
              void revealPath(
                guide.character.guidePdf,
                "Retargeting and rigging Metahuman Abby.pdf",
              )
            }
          >
            Open PDF guide ↗
          </button>
        </header>
        <div className="avatar-rig-grid">
          {presentSystems.map((item) => (
            <article key={item.id}>
              <header>
                <div>
                  <span>{item.application}</span>
                  <h4>{item.label}</h4>
                </div>
                <b>Present</b>
              </header>
              <p>{item.purpose}</p>
              <ul>
                {item.rules.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
              <button
                type="button"
                onClick={() => void revealPath(item.path, item.fileName)}
              >
                <span>{item.fileName}</span>
                <b>Reveal + copy ↗</b>
              </button>
            </article>
          ))}
        </div>
        <aside className="avatar-missing-assets">
          <div>
            <span>EXPECTED BY PDF · NOT FOUND LOCALLY</span>
            <strong>
              {guide.summary.missingExpectedPackages} Wonder Studio previz
              packages
            </strong>
          </div>
          {missingSystems.map((item) => (
            <button
              type="button"
              key={item.id}
              onClick={() => void revealPath(item.path, item.fileName)}
            >
              <span>
                <strong>{item.label}</strong>
                <small>{item.purpose}</small>
              </span>
              <b>Missing</b>
            </button>
          ))}
        </aside>
      </section>

      <section className="avatar-retarget-workflow">
        <header className="character-section-heading">
          <div>
            <p>PDF GUIDE · CONDENSED</p>
            <h3>Retargeting sequence</h3>
          </div>
          <small>
            Wonder Studio supplies body motion; Unreal remains the preferred
            facial-capture route.
          </small>
        </header>
        <ol>
          {guide.retargetSteps.map((item) => (
            <li key={item.step}>
              <span>{String(item.step).padStart(2, "0")}</span>
              <div>
                <strong>{item.label}</strong>
                <p>{item.description}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="avatar-workflow-warning">
          <strong>Do not retarget onto the Quick Rig file.</strong>
          <span>
            Retarget into the dedicated Abby master first, then attach Quick
            Rig with the UE MetaHuman preset and Preserve enabled for cleanup.
          </span>
        </div>
      </section>

      <section className="avatar-root-source">
        <div>
          <p>AUTHORITATIVE ROOT</p>
          <h3>0_Abby_Avatar</h3>
          <span>{guide.character.avatarRoot}</span>
        </div>
        <button
          type="button"
          onClick={() =>
            void revealPath(guide.character.avatarRoot, "0_Abby_Avatar")
          }
        >
          Reveal folder + copy path ↗
        </button>
      </section>
    </div>
  );
}

function headVersionName(version: AvatarHead3DVersion) {
  return version.label.replace(/^Meshy v\d+\s*·\s*/i, "");
}

export function AvatarGuideInspector({
  selection,
}: {
  selection: AvatarGuideSelection | null;
}) {
  const [selectedHeadVersionId, setSelectedHeadVersionId] = useState(
    head3DGuide.primaryVersionId,
  );
  const [selectedRenderVersionId, setSelectedRenderVersionId] = useState("");
  const [selectedUnrealVersionId, setSelectedUnrealVersionId] = useState("");
  const { revealPath, sourceMessage } = useSourceReveal();
  const selectedRender =
    selection?.kind === "render"
      ? guide.renders.find((render) => render.id === selection.id) || null
      : null;
  const selectedUnrealProof =
    selection?.kind === "unreal"
      ? unrealGuide.proofs.find((proof) => proof.id === selection.id) || null
      : null;
  const selectedUnrealVersion =
    selectedUnrealProof?.versions.find(
      (version) => version.id === selectedUnrealVersionId,
    ) ||
    selectedUnrealProof?.versions.find(
      (version) => version.id === selectedUnrealProof.primaryVersionId,
    ) ||
    selectedUnrealProof?.versions[0] ||
    null;
  const selectedRenderVersion =
    selectedRender?.versions?.find(
      (version) => version.id === selectedRenderVersionId,
    ) ||
    selectedRender?.versions?.find(
      (version) => version.id === selectedRender.primaryVersionId,
    ) ||
    selectedRender?.versions?.[0] ||
    null;
  const selectedRenderVideo = selectedRenderVersion
    ? selectedRenderVersion.video
    : selectedRender?.video;
  const selectedRenderPoster =
    selectedRenderVersion?.poster ||
    selectedRenderVersion?.image ||
    selectedRender?.image;
  const selectedHeadVersion =
    head3DGuide.versions.find(
      (version) => version.id === selectedHeadVersionId,
    ) ||
    head3DGuide.versions.find(
      (version) => version.id === head3DGuide.primaryVersionId,
    ) ||
    head3DGuide.versions[0] ||
    null;

  useEffect(() => {
    setSelectedRenderVersionId(selectedRender?.primaryVersionId || "");
  }, [selectedRender?.id, selectedRender?.primaryVersionId]);

  useEffect(() => {
    setSelectedUnrealVersionId(
      selectedUnrealProof?.primaryVersionId || "",
    );
  }, [selectedUnrealProof?.id, selectedUnrealProof?.primaryVersionId]);

  if (!selection) {
    return (
      <p className="mockup-no-results">
        Choose a Character card to see its images and versions.
      </p>
    );
  }

  if (selection.kind === "head" && selectedHeadVersion) {
    const selectedIndex = head3DGuide.versions.findIndex(
      (version) => version.id === selectedHeadVersion.id,
    );
    return (
      <>
        <header className="mockup-version-panel-header">
          <small>
            3D head · {head3DGuide.versions.length}{" "}
            {head3DGuide.versions.length === 1 ? "version" : "versions"}
          </small>
          <h2>3D head model</h2>
        </header>
        <p className="mockup-version-current">
          Current pick
          <b>
            Version {selectedIndex + 1} ·{" "}
            {headVersionName(selectedHeadVersion)}
          </b>
        </p>
        <section className="avatar-head-panel-preview">
          <div className="avatar-head-panel-viewer">
            <ModelTurntable
              key={selectedHeadVersion.model}
              className="three-d-inspector-viewer avatar-head-model-viewer"
              src={selectedHeadVersion.model}
              poster={selectedHeadVersion.thumbnail}
              alt="Interactive 3D model of Abby's head"
              interactive
              motion={false}
              exposure={0.92}
              shadowIntensity={0.72}
              toneMapping="linear"
            />
            <span>Drag to rotate · scroll to zoom</span>
          </div>
          <dl className="avatar-head-3d-stats">
            <div>
              <dt>Faces</dt>
              <dd>{selectedHeadVersion.faces.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Vertices</dt>
              <dd>{selectedHeadVersion.vertices.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                {selectedHeadVersion.status === "needs-fix"
                  ? "Needs fix"
                  : "Review"}
              </dd>
            </div>
          </dl>
          <p className="avatar-head-3d-note">{selectedHeadVersion.note}</p>
          <div className="avatar-head-3d-actions">
            <a href={selectedHeadVersion.model} download>
              Download GLB
            </a>
            <a
              href={selectedHeadVersion.inputSheet}
              target="_blank"
              rel="noreferrer"
            >
              Input angles
            </a>
            <a
              href={selectedHeadVersion.reviewSheet}
              target="_blank"
              rel="noreferrer"
            >
              Model review
            </a>
          </div>
        </section>
        <div
          className="mockup-version-list avatar-head-version-list"
          role="listbox"
          aria-label="3D head versions"
        >
          {head3DGuide.versions.map((version, index) => {
            const selected = version.id === selectedHeadVersion.id;
            return (
              <button
                type="button"
                role="option"
                aria-selected={selected}
                className={`mockup-version-card avatar-head-version-card ${
                  selected ? "selected" : ""
                }`}
                key={version.id}
                onClick={() => setSelectedHeadVersionId(version.id)}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={version.thumbnail}
                  alt={`Version ${index + 1} of Abby's 3D head`}
                  loading="lazy"
                />
                <span>
                  <span>
                    <b>Version {index + 1}</b>
                    <small>{headVersionName(version)}</small>
                  </span>
                  <i aria-hidden="true">
                    {selected ? "✓ Selected" : "Select"}
                  </i>
                </span>
              </button>
            );
          })}
        </div>
      </>
    );
  }

  if (
    selection.kind === "unreal" &&
    selectedUnrealProof &&
    selectedUnrealVersion
  ) {
    const selectedIndex = selectedUnrealProof.versions.findIndex(
      (version) => version.id === selectedUnrealVersion.id,
    );
    return (
      <>
        <header className="mockup-version-panel-header">
          <small>
            {selectedUnrealProof.engine || unrealGuide.pipeline.application} ·{" "}
            {selectedUnrealProof.versions.length}{" "}
            {selectedUnrealProof.versions.length === 1 ? "view" : "versions"}
          </small>
          <h2>{selectedUnrealProof.label}</h2>
        </header>
        <p className="mockup-version-current">
          Current view
          <b>
            Version {selectedIndex + 1} · {selectedUnrealVersion.label}
          </b>
        </p>
        <div
          className="avatar-guide-panel-media avatar-unreal-panel-media"
          style={
            selectedUnrealVersion.mediaType === "video"
              ? {
                  aspectRatio: `${selectedUnrealVersion.width} / ${selectedUnrealVersion.height}`,
                }
              : undefined
          }
        >
          {selectedUnrealVersion.mediaType === "video" ? (
            <video
              key={selectedUnrealVersion.image}
              src={selectedUnrealVersion.image}
              poster={selectedUnrealVersion.poster}
              aria-label={`${selectedUnrealProof.label} · ${selectedUnrealVersion.label}`}
              autoPlay
              muted
              loop
              playsInline
              controls
              preload="metadata"
            />
          ) : (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={selectedUnrealVersion.image}
              alt={`${selectedUnrealProof.label} · ${selectedUnrealVersion.label}`}
            />
          )}
          <span>
            {formatVersionResolution(selectedUnrealVersion)} ·{" "}
            {selectedUnrealVersion.status}
          </span>
        </div>
        <div
          className="mockup-version-list avatar-render-version-list avatar-unreal-version-list"
          role="listbox"
          aria-label={`${selectedUnrealProof.label} evidence versions`}
        >
          {selectedUnrealProof.versions.map((version, index) => {
            const selected = version.id === selectedUnrealVersion.id;
            return (
              <button
                type="button"
                role="option"
                aria-selected={selected}
                className={`mockup-version-card avatar-render-version-card ${
                  selected ? "selected" : ""
                }`}
                key={version.id}
                onClick={() => setSelectedUnrealVersionId(version.id)}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={version.poster || version.image}
                  alt={`Version ${index + 1} · ${version.label}`}
                  loading="lazy"
                />
                <span>
                  <span>
                    <b>Version {index + 1}</b>
                    <small>{version.label}</small>
                  </span>
                  <i aria-hidden="true">
                    {selected ? "✓ Selected" : "Select"}
                  </i>
                </span>
              </button>
            );
          })}
        </div>
        <section className="avatar-guide-panel-copy avatar-unreal-panel-copy">
          <div className="avatar-unreal-panel-status">
            <span className={`avatar-unreal-tone ${selectedUnrealProof.status}`}>
              {selectedUnrealProof.statusLabel}
            </span>
            <small>{selectedUnrealProof.version}</small>
          </div>
          <strong>{selectedUnrealProof.interval}</strong>
          <p>{selectedUnrealProof.summary}</p>
          <blockquote>{selectedUnrealProof.verdict}</blockquote>
          <dl>
            {selectedUnrealProof.sourceFrames ? (
              <div>
                <dt>Source frames</dt>
                <dd>{selectedUnrealProof.sourceFrames}</dd>
              </div>
            ) : null}
            {selectedUnrealProof.solveOffsets ? (
              <div>
                <dt>Solve offsets</dt>
                <dd>{selectedUnrealProof.solveOffsets}</dd>
              </div>
            ) : null}
            {selectedUnrealProof.processedFrames ? (
              <div>
                <dt>Processed</dt>
                <dd>{selectedUnrealProof.processedFrames}</dd>
              </div>
            ) : null}
            <div>
              <dt>Identity</dt>
              <dd>
                {selectedUnrealProof.identity ||
                  unrealGuide.pipeline.capture.identity}
              </dd>
            </div>
            <div>
              <dt>{selectedUnrealProof.captureNoteLabel || "Depth note"}</dt>
              <dd>{selectedUnrealProof.depthDiagnostic}</dd>
            </div>
          </dl>
          <div className="avatar-unreal-notes">
            <span>OBSERVATIONS</span>
            <ul>
              {selectedUnrealProof.observations.map((observation) => (
                <li key={observation}>{observation}</li>
              ))}
            </ul>
          </div>
          <div className="avatar-unreal-lineage">
            <span>LINEAGE</span>
            <div>
              {selectedUnrealProof.lineage.map((item) => (
                <small key={item}>{item}</small>
              ))}
            </div>
          </div>
          {selectedUnrealProof.artifacts.length > 0 ? (
            <div className="avatar-unreal-artifacts">
              <span>FILES + REPORTS</span>
              <div>
                {selectedUnrealProof.artifacts.map((artifact) => (
                  <a
                    key={artifact.url}
                    href={artifact.url}
                    target="_blank"
                    rel="noreferrer"
                    download={artifact.download || undefined}
                  >
                    <small>{artifact.kind}</small>
                    <b>{artifact.label}</b>
                  </a>
                ))}
              </div>
            </div>
          ) : null}
          <div className="avatar-render-actions avatar-unreal-actions">
            <a
              href={selectedUnrealVersion.image}
              target="_blank"
              rel="noreferrer"
            >
              Open current evidence
            </a>
            <button
              type="button"
              onClick={() =>
                void revealPath(
                  selectedUnrealProof.sourcePath,
                  selectedUnrealProof.sourceFile,
                )
              }
            >
              Reveal + copy source
            </button>
            <button
              type="button"
              onClick={() =>
                void revealPath(
                  selectedUnrealProof.archivePath ||
                    unrealGuide.pipeline.archiveRoot,
                  selectedUnrealProof.archivePath
                    ? "MySlate body-rig archive v012"
                    : `MySlate archive ${unrealGuide.pipeline.archiveVersion}`,
                )
              }
            >
              Open immutable archive
            </button>
          </div>
          {sourceMessage ? (
            <p className="character-source-message">{sourceMessage}</p>
          ) : null}
        </section>
      </>
    );
  }

  if (!selectedRender) {
    return (
      <p className="mockup-no-results">
        This Character reference is no longer available.
      </p>
    );
  }

  return (
    <>
      <header className="mockup-version-panel-header">
        <small>
          {selectedRender.versions?.length
            ? `Cinema 4D render · ${selectedRender.versions.length} versions`
            : `${selectedRender.application} · ${selectedRender.view}`}
        </small>
        <h2>{selectedRender.label}</h2>
      </header>
      {selectedRenderVersion && selectedRender.versions ? (
        <p className="mockup-version-current">
          Current pick
          <b>
            Version{" "}
            {selectedRender.versions.findIndex(
              (version) => version.id === selectedRenderVersion.id,
            ) + 1}{" "}
            · {selectedRenderVersion.label}
          </b>
        </p>
      ) : null}
      <div className="avatar-guide-panel-media">
        {selectedRenderVideo ? (
          <video
            src={selectedRenderVideo}
            poster={selectedRenderPoster}
            aria-label={selectedRender.label}
            autoPlay
            muted
            loop
            playsInline
            controls
          />
        ) : (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={selectedRenderVersion?.image || selectedRender.image}
            alt={
              selectedRenderVersion
                ? `${selectedRender.label} · ${selectedRenderVersion.label}`
                : selectedRender.label
            }
          />
        )}
        <span>
          {selectedRenderVersion
            ? formatVersionResolution(selectedRenderVersion)
            : formatResolution(selectedRender)}
        </span>
      </div>
      {selectedRenderVersion && selectedRender.versions ? (
        <div
          className="mockup-version-list avatar-render-version-list"
          role="listbox"
          aria-label={`${selectedRender.label} versions`}
        >
          {selectedRender.versions.map((version, index) => {
            const selected = version.id === selectedRenderVersion.id;
            return (
              <button
                type="button"
                role="option"
                aria-selected={selected}
                className={`mockup-version-card avatar-render-version-card ${
                  selected ? "selected" : ""
                }`}
                key={version.id}
                onClick={() => setSelectedRenderVersionId(version.id)}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={version.poster || version.image}
                  alt={`Version ${index + 1} · ${version.label}`}
                  loading="lazy"
                />
                <span>
                  <span>
                    <b>Version {index + 1}</b>
                    <small>{version.label}</small>
                  </span>
                  <i aria-hidden="true">
                    {selected ? "✓ Selected" : "Select"}
                  </i>
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
      <section className="avatar-guide-panel-copy">
        <strong>{selectedRender.renderType}</strong>
        <p>{selectedRender.description}</p>
        <small>{selectedRender.fidelity}</small>
        <dl>
          <div>
            <dt>Native resolution</dt>
            <dd>
              {selectedRenderVersion
                ? formatVersionResolution(selectedRenderVersion)
                : formatResolution(selectedRender)}
            </dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{selectedRender.sourceFile}</dd>
          </div>
        </dl>
        <div className="avatar-render-actions">
          <a
            href={
              selectedRenderVideo ||
              selectedRenderVersion?.image ||
              selectedRender.image
            }
            target="_blank"
            rel="noreferrer"
          >
            {selectedRenderVideo ? "Open animation" : "Open full resolution"}
          </a>
          {selectedRender.sourceUrl ? (
            <a
              href={selectedRender.sourceUrl}
              target="_blank"
              rel="noreferrer"
            >
              {selectedRender.sourceUrlLabel || "Open source"}
            </a>
          ) : null}
          <button
            type="button"
            onClick={() =>
              void revealPath(
                selectedRender.sourcePath,
                selectedRender.sourceFile,
              )
            }
          >
            Reveal + copy source
          </button>
        </div>
        {sourceMessage ? (
          <p className="character-source-message">{sourceMessage}</p>
        ) : null}
      </section>
    </>
  );
}
