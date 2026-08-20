"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { CharacterLibrary } from "./character-library";
import { FeedbackTracker } from "./feedback-tracker";
import { InstagramPalette } from "./instagram-palette";
import { MockupGallery } from "./mockup-gallery";
import { Object3DGallery } from "./object-3d-gallery";
import { ObjectInventory } from "./object-inventory";
import { RightInspectorPanel } from "./right-inspector-panel";
import { ShotCardDetails } from "./shot-card-details";
import { deriveShotDisplayName } from "./shot-card-name";
import {
  copyProductionPath,
  isLocalProductionBrowser,
  runtimeApiBase,
} from "./runtime-api";
import {
  SourceApplicationLinks,
  resolveC4DEvidenceStatus,
  type C4DCameraProofTone,
} from "./source-application-links";

type Evidence =
  | "confirmed"
  | "visually_confirmed"
  | "visually_confirmed_candidate"
  | "strong_inference"
  | "candidate"
  | "missing";

type LineageTag = {
  type: "chapter_edit" | "source_render";
  label: string;
  detail: string;
  evidence: Evidence;
};

type LineageNode = {
  kind: string;
  label: string;
  detail: string;
  path?: string;
  projectPath?: string;
  comparisonImage?: string;
  confirmationMethod?: string;
  proofStatus?: string;
  recoveryProof?: boolean;
  primaryRecoveryProof?: boolean;
  redshiftProof?: boolean;
  fullColorProof?: boolean;
  fullColorRender?: boolean;
  freshAuditRender?: boolean;
  productionSourceReference?: boolean;
  historicalProductionReference?: boolean;
  visualVerificationStatus?: string;
  evidence: Evidence;
  tags?: LineageTag[];
  assetHealth?: {
    status: C4DLinkStatus["status"];
    label: string;
    take: string;
  };
};

type ExportProducer = {
  kind: string;
  label: string;
  projectPath?: string;
  sequence?: string;
  detail?: string;
  evidence: Evidence;
};

type ExportScreenshot = {
  id: string;
  role: string;
  label: string;
  image: string;
  exportPath: string;
  sourceTime: number;
  detail: string;
  evidence: Evidence;
  producers: ExportProducer[];
};

type SourceSegment = {
  id: string;
  sectionCode: string;
  finalStart: number;
  finalEnd: number;
  sourceSystem: string;
  sourceEdit: string;
  sourcePath: string;
  sourceFirstFramePath: string;
  sourceStartFrame?: number | null;
  sourceEndFrame?: number | null;
  sourceFrameRate: number;
  sourceTrack?: number;
  playBackwards: boolean;
  evidence: Evidence;
  role?: "older_than_cut" | "exact_match" | "newer_than_cut";
  finalStartFrame?: number;
  finalEndFrame?: number;
  renderDirectory?: string;
  sourceIn?: number;
  sourceOut?: number;
  sourceInTicks?: number;
  sourceOutTicks?: number;
  sourceInFrameOffset?: number;
  sourceOutFrameOffset?: number;
  selectedFirstFrame?: number | null;
  selectedLastFrame?: number | null;
  premiereLabel?: string;
  premiereLabelIndex?: number | null;
  premiereRoleLabel?: string;
  isNewRecovery?: boolean;
  manualTrimAuthority?: boolean;
  canonical?: boolean;
  sourceMediaHealth?: {
    status: "complete" | "incomplete" | "missing";
    expectedFrames: number;
    availableFrames: number;
    missingFrames: number;
    missingFirstFrame?: number | null;
    missingLastFrame?: number | null;
  };
  visualAlignment?: {
    authority: string;
    evidence: Evidence;
    detail: string;
    originalPremiereStartFrame?: number;
  };
  frameAlignedConform?: {
    authority: string;
    project: string;
    sequence: string;
    adapterPath: string;
    adapterFrameRate: number;
    adapterFrames: number;
    chosenFirstFrame: number;
    chosenLastFrame: number;
    stepHistogram: Record<string, number>;
    similarity: {
      minimum: number;
      median: number;
      mean: number;
      maximum: number;
    };
    verified: boolean;
  };
  verification?: {
    score: number;
    evidence: Evidence;
    finalImage: string;
    sourceImage: string;
    pairImage: string;
  };
};

type ManualConform = {
  authority: "saved_premiere_clip_instance";
  project?: string;
  sequence?: string;
  timelineTrack?: number;
  timelineStartTicks: number;
  timelineEndTicks: number;
  startFrame: number;
  endFrame: number;
  sourceInTicks?: number;
  sourceOutTicks?: number;
  sourceIn?: number;
  sourceOut?: number;
  sourceInFrameOffset?: number;
  sourceOutFrameOffset?: number;
  status:
    | "intentional_blank"
    | "exact_match"
    | "partially_exact"
    | "bracketed_missing_exact"
    | "older_than_cut"
    | "newer_than_cut"
    | "partially_tracked"
    | "untracked";
  coverage?: number;
  exactCoverage?: number;
  sources: string[];
  visualAlignment?: SourceSegment["visualAlignment"];
  frameAlignedConform?: SourceSegment["frameAlignedConform"];
};

type C4DComponent = {
  key: "objects" | "character" | "textures" | "proxies" | "caches";
  label: string;
  status: "linked" | "embedded" | "warning" | "missing" | "not_used";
  summary: string;
  linkedReferences: number;
  linkedFiles: number;
  missingReferences: number;
  missingFiles: number;
  renderCriticalMissingReferences: number;
  renderCriticalMissingFiles: number;
};

type C4DLinkStatus = {
  status:
    | "fully_linked_confirmed"
    | "render_safe_with_warnings"
    | "render_dependencies_missing"
    | "audit_unavailable";
  label: string;
  detail: string;
  projectPath?: string;
  projectName?: string;
  take?: string;
  frame?: number;
  auditedAt?: string;
  method?: string;
  objectCount?: number;
  renderEnabledObjectCount?: number;
  dependencyReferences?: number;
  linkedReferences?: number;
  linkedFiles?: number;
  missingReferences?: number;
  missingFiles?: number;
  renderCriticalMissingReferences?: number;
  renderCriticalMissingFiles?: number;
  renderCriticalExactRecoveries?: number;
  renderCriticalCandidateRecoveries?: number;
  renderCriticalUnresolvedFiles?: number;
  rawRenderCriticalMissingFiles?: number;
  strictDependencyRenderSafe?: boolean;
  manifestPath?: string;
  verificationPath?: string;
  exactCutAudit?: {
    authority?: string;
    rawAuditPath?: string;
    manifestPath?: string;
    verificationPath?: string;
    mappedPaths: number;
    manifestUnresolvedPaths: number;
    postRelinkUnresolvedFiles: number;
    postRelinkUnresolvedReferences: number;
    strictDependencyRenderSafe: boolean;
  };
  dependencyRecovery?: {
    auditedAt?: string;
    method?: string;
    exactPathRecoveries: number;
    candidateRecoveries: number;
    unresolved: number;
    records: Array<{
      requiredPath: string;
      basename: string;
      status:
        | "recovered_exact_path"
        | "candidate_exact_basename"
        | "candidate_normalized_name"
        | "unresolved";
      categories: string[];
      characterRelated: boolean;
      candidates: Array<{
        path: string;
        commonSuffixSegments: number;
        exactRelativeSuffix: boolean;
        size?: number;
        modifiedAt?: string;
      }>;
    }>;
  };
  components: C4DComponent[];
  missingExamples: Array<{
    filename: string;
    owner: string;
    category: string;
    characterRelated: boolean;
    renderCritical: boolean;
    recovery?: {
      status:
        | "recovered_exact_path"
        | "candidate_exact_basename"
        | "candidate_normalized_name"
        | "unresolved";
      candidates: Array<{
        path: string;
        commonSuffixSegments: number;
        exactRelativeSuffix: boolean;
        size?: number;
        modifiedAt?: string;
      }>;
      semanticCandidates?: Array<{
        path: string;
        score: number;
        semanticClasses: string[];
        matchingTokens: string[];
        size?: number;
        modifiedAt?: string;
        status: "semantic_candidate_unverified";
      }>;
      semanticValidationRequired?: string[];
    };
  }>;
  historicalRenderNote?: string;
  dependencyLabel?: string;
  strictLinked?: boolean;
  verificationStatus?: string;
  visualReview?: {
    status: string;
    elements: Record<string, string>;
    notes: string;
  };
  verificationBlockers?: string[];
};

type C4DVerification = {
  status:
    | "strictly_verified"
    | "match"
    | "partial"
    | "mismatch"
    | "missing"
    | "unreviewed";
  label: string;
  detail: string;
  strictLinked: boolean;
  reviewedAt?: string;
  authority?: string;
  elements: Record<
    "location" | "camera" | "character" | "hair" | "wardrobe" | "materials",
    "match" | "partial" | "mismatch" | "missing" | "not_visible" | "not_verifiable"
  >;
  notes: string;
  blockers: string[];
  remediation: string[];
  recoveryPrescription?: string;
  agentReadyChecklist?: string[];
  checks: {
    projectLinked: boolean;
    dependencyAudited: boolean;
    dependencyRenderSafe: boolean;
    proxyRenderSafe: boolean;
    cameraProofRendered: boolean;
    visualMatch: boolean;
  };
  cameraProof?: string;
  cameraName?: string;
  comparisonImage?: string;
  renderReference?: string;
  materialCompatibilityAudit?: {
    status?: string;
    outputPath?: string;
    publicPath?: string;
    comparisonPath?: string;
    diagnosticOutputPath?: string;
    diagnosticComparisonPath?: string;
    akfxSourcePackageC4d2025OutputPath?: string;
    runtimeDetail?: string;
    [key: string]: unknown;
  };
  linkageAudit?: {
    dependencyReferences: number;
    linkedReferences: number;
    missingReferences: number;
    renderCriticalMissingReferences: number;
    renderCriticalMissingFiles: number;
    recoveredExactFiles?: string[];
    missingExactFiles?: string[];
  };
};

type C4DSceneState = {
  inspected: boolean;
  generatedAt?: string;
  authority?: string;
  projectPath?: string;
  projectName?: string;
  frameInspected?: number;
  diagnosis: string;
  activeProxyCount: number;
  activeCharacterObjectCount: number;
  activeHairObjectCount: number;
  activeWardrobeObjectCount: number;
  expectedWardrobeFamily: "patchwork" | "grey" | "colored_grey";
  expectedSharedAssets: string[];
};

type C4DProxyAudit = {
  required: boolean;
  status:
    | "not_used"
    | "renderer_update_required"
    | "rebuild_ready"
    | "verified_rendered"
    | "unresolved"
    | "audit_unavailable";
  label: string;
  detail: string;
  generatedAt?: string;
  authority?: string;
  records: Array<{
    proxyObjectName?: string;
    proxyObjectPath?: string;
    proxyFile?: string;
    proxyAuditPath?: string;
    producerVersion?: string;
    editableCharacterDiagnosis?: string;
    rendererCompatibility?: {
      installed?: string;
      requiredMinimum?: string;
      currentOfficial?: string;
      status?: string;
    };
    proxyAuditSummary?: {
      dependencyCount?: number;
      dependencyByStatus?: Record<string, number>;
      bodyMeshPresent?: boolean;
      faceMeshPresent?: boolean;
      hairPresent?: boolean;
      wardrobePresent?: boolean;
      cameraPresent?: boolean;
    };
    sourceComponentsComplete: boolean;
    sourceComponents: Array<{
      path: string;
      category: string;
      sizeBytes?: number;
      modifiedAt?: string;
    }>;
  }>;
};

type C4DStructuralRecovery = {
  cutId: string;
  status: string;
  generatedAt?: string;
  authority?: string;
  sourceProject: string;
  recoveryProject: string;
  hairSourceProject?: string;
  wardrobeCache?: string;
  cameraName: string;
  renderData: string;
  targetFrame: number;
  sourceHairFrame?: number;
  matchedTimeSeconds?: number;
  targetFps?: number;
  sourceFps?: number;
  rootTransformDelta?: number;
  detail?: string;
  cameraProofEligible?: boolean;
  exactRelinks?: Array<{
    category: string;
    path: string;
    status: string;
  }>;
  hairGeometry?: {
    guidePointCounts?: number[];
    evaluatedPolygonCount?: number;
    evaluatedProofPieces?: number;
    evaluatedPiecePointCount?: number;
    evaluatedPiecePolygonCount?: number;
    staticFallbackStatus?: string;
    limitation?: string;
    status: string;
  };
  wardrobeGeometry?: {
    cachePointCount?: number;
    cachePolygonCount?: number;
    pointCount?: number;
    polygonCount?: number;
    status: string;
  };
  linkageAudit?: {
    status: string;
    originalLinkedReferences?: number;
    originalMissingReferences?: number;
    originalUniqueMissingFiles?: number;
    recoveryLinkedReferences?: number;
    recoveryMissingReferences?: number;
    recoveryUniqueMissingFiles?: number;
    additionalReferencesResolvedByCompatibilityPaths?: number;
    currentC4dLoadWarning?: string;
    redshiftCompatibility?: string;
    strictlyLinked: boolean;
  };
  proofs: Array<{
    kind: string;
    image?: string;
    status: string;
    primary?: boolean;
    visualResult?: string;
    error?: string;
  }>;
  elementReview: Record<string, string>;
  remainingBlockers: string[];
};

type C4DCameraCandidateAudit = {
  cutId: string;
  status: string;
  generatedAt?: string;
  authority?: string;
  canonicalThumbnail: string;
  expectedView: string;
  sourceRenderDirectory: string;
  sourceFrame: number;
  renderData: string;
  sourceProject: string;
  historicalProjectsTested: string[];
  summary: string;
  nextResolution: string;
  candidates: Array<{
    cameraName: string;
    projectPath: string;
    frame: number;
    image: string;
    status: string;
    difference: string;
  }>;
};

type Cut = {
  id: string;
  shotId: string;
  pipelineAttachmentId?: string;
  legacyCutId?: string | null;
  index: number;
  start: number;
  end: number;
  duration: number;
  timecode: string;
  endTimecode: string;
  thumbnail: string;
  scrubProxy?: string | null;
  scrubStart?: number;
  scrubEnd?: number;
  boundaryEvidence: string;
  boundaryDetail: string;
  verification: string;
  blockId?: string;
  sectionCode: string;
  sectionName: string;
  isGap?: boolean;
  plannedShotId?: string;
  confidence: Evidence;
  lineage: LineageNode[];
  exportScreenshots: ExportScreenshot[];
  sourceSegments: SourceSegment[];
  manualConform?: ManualConform;
  c4dLinkStatus?: C4DLinkStatus;
  c4dVerification?: C4DVerification;
  c4dSceneState?: C4DSceneState;
  c4dProxyAudit?: C4DProxyAudit;
  c4dStructuralRecovery?: C4DStructuralRecovery;
  c4dCameraCandidateAudit?: C4DCameraCandidateAudit;
  comparison?: {
    score: number;
    evidence: Evidence;
    sourceFramePath: string;
    finalImage: string;
    sourceImage: string;
    pairImage: string;
  };
};

type C4DCleanManifestRecord = {
  cutId: string;
  recoveryProjectPath?: string | null;
  recoveryRenderSafe?: boolean;
  dependencyStatus?: string;
  renderCriticalMissingFiles?: number;
  blockers?: string[];
  visualReview?: {
    status?: string;
    elements?: Record<string, string>;
    notes?: string;
  };
  originalProxyGate?: {
    status?: string;
    objectPath?: string;
    requiredPath?: string;
    filePath?: string;
    requiredFrames?: string;
    frameRate?: number;
    frameOffset?: number;
    crossShotHairAllowed?: boolean;
    authoredContents?: string[];
    authoredSceneAssets?: {
      characterRoot?: string;
      hairObject?: string;
      wardrobeObject?: string;
      renderEnabled?: boolean;
      diagnosis?: string;
    };
    authoritativeProxies?: Array<{
      objectPath?: string;
      filePath?: string;
      requiredFrames?: string;
      frameRate?: number;
      frameOffset?: number;
    }>;
    evidence?: string;
  } | null;
};

type C4DCleanManifest = {
  records?: C4DCleanManifestRecord[];
};

type PlannedShot = {
  id: string;
  scene: string;
  song: string;
  shot: string;
  start?: number;
  end?: number;
  location: string;
  framing: string;
  description: string;
  character: string;
  action: string;
  simulation: string;
  fileName: string;
  camera: string;
  notes: string;
};

type Block = {
  id: string;
  name: string;
  path: string;
  track: number;
  start: number;
  end: number;
  duration: number;
  sectionCode: string;
  sectionName: string;
  evidence: Evidence;
};

type Source = {
  name: string;
  kind: string;
  state: string;
  detail: string;
  path?: string;
  modifiedAt?: string;
};

type AtlasState = {
  generatedAt: string;
  readOnly: boolean;
  canonicalShotList?: {
    authority: string;
    path: string;
    sha256: string;
    registryPath: string;
    fps: number;
    pictureEvents: number;
    pictureShots: number;
    intentionalBlanks: number;
    identityField: "shotId";
    displayOrdinalField: "id";
  };
  groundTruth: {
    title: string;
    frameIoUrl: string;
    localPath: string;
    hoverProxy?: string | null;
    duration: number;
    durationTimecode: string;
    fps: number;
    width: number;
    height: number;
    codec: string;
    size: number;
  };
  summary: {
    editCuts: number;
    plannedShots: number;
    finalBlocks: number;
    resolveTimelines: number;
    resolveRenderJobs: number;
    c4dProjects: number;
    c4dDependencyAuditedProjects: number;
    c4dDependencyMappedProjects: number;
    c4dDependencyAuditedCuts: number;
    c4dFullyLinkedCuts: number;
    c4dStrictLinkedCuts?: number;
    c4dVisualMatchCuts?: number;
    c4dVisualPartialCuts?: number;
    c4dVisualMismatchCuts?: number;
    c4dVisualMissingProofCuts?: number;
    c4dVisualUnreviewedCuts?: number;
    c4dSceneStateAuditedCuts?: number;
    c4dProxyAffectedCuts?: number;
    c4dProxyRendererUpdateRequiredCuts?: number;
    c4dProxyRebuildReadyCuts?: number;
    c4dProxyUnresolvedCuts?: number;
    c4dRenderSafeWarningCuts: number;
    c4dMissingRenderDependencyCuts: number;
    c4dDependencyUnavailableCuts: number;
    afterEffectsProjects: number;
    premiereProjects: number;
    renderSequences: number;
    exactRenderProjectMatches: number;
    cameraConfirmed: number;
    pictureCuts: number;
    cameraConfirmedCuts: number;
    renderAlignedCameraCuts: number;
    cameraUnresolvedCuts: number;
    cameraAuditConfirmations: number;
    framePairsArchived: number;
    framePairsVisuallyConfirmed: number;
    lineageExportScreenshots: number;
    chapterEditTaggedCuts: number;
    sourceRenderTaggedCuts: number;
    sourceRenderTaggedNodes: number;
    recoveredSourceRenders: number;
    recoveredSourceCandidates: number;
    sourceConformSegments: number;
    sourceConformConfirmed: number;
    premiereConformVerified: boolean;
    premiereConformClips: number;
    manualConformPictureClips?: number;
    manualConformIntentionalBlanks?: number;
    manualConformExactSources?: number;
    manualConformOlderSources?: number;
    manualConformNewerSources?: number;
    manualConformCanonicalSources?: number;
    manualConformV1Sources?: number;
    manualConformV2Sources?: number;
    sourceMediaCompleteClips?: number;
    sourceMediaIncompleteClips?: number;
    sourceMediaMissingSelectedFrames?: number;
    cameraProofTargets?: number;
    cameraProofRendered?: number;
    cameraProofFailed?: number;
    cameraProofUnresolved?: number;
    cameraProofTaggedCuts?: number;
    manualConformStatusCounts?: Record<string, number>;
    evidenceCounts: Record<string, number>;
  };
  sources: Source[];
  chapterEdits: Array<{
    sectionCode: string;
    sectionName: string;
    system: string;
    projectLabel: string;
    projectPath: string;
    editName: string;
    editAlias?: string;
    exportPath?: string;
    detail: string;
    evidence: Evidence;
    taggedCuts: number;
  }>;
  premiere: {
    project: string;
    sequence: string;
    blocks: Block[];
    primaryBlocks: Block[];
  };
  premiereConform: {
    success: boolean;
    verifiedSegments: number;
    expectedSegments: number;
    reverseVerified: number;
    reverseExpected: number;
    projectExport: string;
    fcpXml: string;
  };
  conform: {
    baseSequence: string;
    segments: SourceSegment[];
    omittedSubframeEvents: SourceSegment[];
    summary: {
      segments: number;
      omittedSubframeEvents: number;
      confirmed: number;
      strongInference: number;
      sections: Record<string, number>;
    };
  };
  revisedConform?: {
    active: boolean;
    authorityKind?: string;
    authority?: string;
    projectPath?: string;
    projectSha256?: string;
    projectModifiedAt?: string;
    sequence?: string;
    timelineFrameRate?: number;
    sourceImageFrameRate?: number;
    canonicalTracks?: number[];
    chapterBoundaryTrack?: number;
    chapterCuts?: Array<{
      sectionCode: string;
      sectionName: string;
      start: number;
      end: number;
      startFrame: number;
      endFrame: number;
    }>;
    visualAlignment?: {
      path?: string;
      appliedCorrections?: Array<{
        sourcePath?: string;
        detail?: string;
      }>;
    };
    manualTrimPolicy?: string;
    summary?: {
      v1PictureClips?: number;
      intentionalBlanks?: number;
      v5OlderSources?: number;
      v6ExactSources?: number;
      v7NewerSources?: number;
      pictureClips?: number;
      canonicalSources?: number;
      v1CanonicalSources?: number;
      v2CanonicalSources?: number;
      chapterCuts?: number;
      allVisibleFramesLinked?: boolean;
      exactTimelineFrames?: number;
      pictureTimelineFrames?: number;
      alternateSearch?: {
        searched?: number;
        ranked?: number;
        visuallyConfirmedCandidates?: number;
        strongCandidates?: number;
        candidates?: number;
      };
    };
  };
  plannedShots: PlannedShot[];
  cuts: Cut[];
  resolve: {
    project: string;
    exportedAt: string;
    timelines: Array<{
      index: number;
      name: string;
      startFrame: number;
      endFrame: number;
      itemCount: number;
    }>;
  };
  method: {
    boundaryThreshold: number;
    minimumBoundaryGap: number;
    boundaryStatus: string;
    evidenceLevels: string[];
    notes: string[];
  };
};

const API = runtimeApiBase();
const evidenceLabels: Record<string, string> = {
  confirmed: "Confirmed",
  visually_confirmed: "Visual match",
  visually_confirmed_candidate: "Visual candidate",
  strong_inference: "Strong inference",
  candidate: "Candidate",
  missing: "Missing",
};

const nodeLabels: Record<string, string> = {
  reference: "Final frame",
  premiere: "Premiere block",
  premiere_sequence: "Nested Premiere source",
  premiere_export: "Premiere export",
  premiere_gap: "Editorial gap",
  premiere_frame_alignment: "Frame-aligned Premiere conform",
  resolve: "Resolve",
  resolve_media: "Resolve source",
  after_effects: "After Effects",
  after_effects_comp: "AE source comp",
  after_effects_layer: "AE source layer",
  render_sequence: "Render sequence",
  cinema4d: "Cinema 4D",
  cinema4d_recovery: "Cinema 4D recovery",
  camera: "Render camera",
  camera_proof: "Camera test render",
  process_image: "Process image",
  material_diagnostic: "Material compatibility test",
  camera_search: "Camera candidate exhaust",
  visual_match: "Frame comparison",
  redshift_render_log: "Redshift render log",
  render_reference: "Production render reference",
};

const conformStatusLabels: Record<string, string> = {
  intentional_blank: "Intentional V1 blank",
  exact_match: "Canonical V6 / Iris",
  partially_exact: "Partially exact",
  bracketed_missing_exact: "Older + newer bracket",
  older_than_cut: "Older only / V5 Rose",
  newer_than_cut: "Canonical V7 / Green",
  partially_tracked: "Partially tracked",
  untracked: "Source missing",
};

function conformStatusLabel(status: string, cleanConform: boolean) {
  if (cleanConform) {
    if (status === "intentional_blank") return "V1/V2 picture gap";
    if (status === "exact_match") return "Canonical V1/V2 source";
  }
  return conformStatusLabels[status] || status;
}

function shortPath(path?: string) {
  if (!path) return "";
  return path
    .replace("/Users/alphaone/Futuro Dropbox/Futuro Team Folder/Absolutely", "…/Absolutely")
    .replace("/Users/alphaone/Documents/Code", "…/Code")
    .replace("/Users/alphaone", "~");
}

function splitPathForDisplay(path: string) {
  const normalized = path.replace(/\/+$/, "");
  const separator = normalized.lastIndexOf("/");
  if (separator < 0) return { leading: "", ending: normalized };
  return {
    leading: normalized.slice(0, separator + 1),
    ending: normalized.slice(separator + 1),
  };
}

function fileName(path?: string) {
  if (!path) return "";
  return path.replace(/\/+$/, "").split("/").pop() || path;
}

function isCompositeEvidenceImage(path?: string) {
  if (!path) return false;
  const name = fileName(path);
  return (
    /(?:contact|comparison|composite|sheet)/i.test(name) ||
    /(?:^|[._-])pair(?:[._-]|$)/i.test(name) ||
    /(?:^|[._-])(?:vs|side[-_]by[-_]side|split[-_]screen)(?:[._-]|$)/i.test(
      name,
    )
  );
}

const browserEvidenceImageOverrides: Record<string, string> = {
  "/archive/c4d-local-recovery-20260809/CUT-061/full-gui-host/CUT-061-full-gui-c4d2026p1p4-exact-source-f0342-160x90-20260812_0342.tif":
    "/archive/c4d-local-recovery-20260809/CUT-061/full-gui-host/CUT-061-full-gui-c4d2026p1p4-exact-source-f0342-160x90-20260812_0342.png",
};

function publicEvidenceImagePath(path?: string) {
  if (!path) return undefined;
  const publicMarker = "/paracosm-provenance/public/";
  const publicIndex = path.indexOf(publicMarker);
  let publicPath: string | undefined;
  if (publicIndex >= 0) {
    publicPath = `/${path.slice(publicIndex + publicMarker.length)}`;
  } else if (path.startsWith("/archive/") || path.startsWith("/data/")) {
    publicPath = path;
  }
  return publicPath
    ? browserEvidenceImageOverrides[publicPath] || publicPath
    : undefined;
}

function isFreshFullColorEvidence(
  image: string | undefined,
  fullColorRender?: boolean,
  freshAuditRender?: boolean,
) {
  if (!image) return false;
  return Boolean(
    (fullColorRender === true && freshAuditRender === true) ||
      /\/archive\/redshift-full-color-final-\d{8}\//i.test(image),
  );
}

type C4DNavMode = "all" | "preview" | C4DCameraProofTone;

function bestC4DPreviewImage(cut: Cut) {
  const resolved = resolveC4DEvidenceStatus(cut);
  const materialAudit = cut.c4dVerification?.materialCompatibilityAudit;
  const reviewedFullColorCameraProof =
    cut.c4dVerification?.checks.cameraProofRendered &&
    materialAudit?.status?.startsWith("fresh_full_color") === true
      ? publicEvidenceImagePath(
          materialAudit.outputPath ||
            materialAudit.publicPath ||
            cut.c4dVerification.cameraProof,
        )
      : undefined;
  if (
    reviewedFullColorCameraProof &&
    !isCompositeEvidenceImage(reviewedFullColorCameraProof)
  ) {
    return reviewedFullColorCameraProof;
  }
  const explicitFullColorCameraProof = publicEvidenceImagePath(
    cut.c4dVerification?.cameraProof,
  );
  if (
    explicitFullColorCameraProof &&
    /(?:full[-_]color|donor[-_]materials|exact191[-_]ocio)/i.test(
      explicitFullColorCameraProof,
    ) &&
    !isCompositeEvidenceImage(explicitFullColorCameraProof)
  ) {
    return explicitFullColorCameraProof;
  }
  const eligibleCameraProof = (node: LineageNode) =>
    Boolean(
      node.kind === "camera_proof" &&
        node.comparisonImage &&
        node.proofStatus?.startsWith("rendered") === true &&
        !node.visualVerificationStatus?.toLowerCase().includes("rejected") &&
        !node.productionSourceReference &&
        !node.historicalProductionReference &&
        !isCompositeEvidenceImage(node.comparisonImage),
    );
  const eligibleColorPreview = (node: LineageNode) =>
    Boolean(
      node.comparisonImage &&
        node.fullColorRender === true &&
        isFreshFullColorEvidence(
          node.comparisonImage,
          node.fullColorRender,
          node.freshAuditRender,
        ) &&
        !node.productionSourceReference &&
        !node.historicalProductionReference &&
        !isCompositeEvidenceImage(node.comparisonImage),
    );
  const primaryColorProof = cut.lineage.find(
    (node) =>
      node.primaryRecoveryProof === true &&
      eligibleColorPreview(node),
  );
  if (primaryColorProof?.comparisonImage) {
    const image = publicEvidenceImagePath(
      primaryColorProof.comparisonImage,
    );
    if (image) return image;
  }

  const activeColorProof =
    resolved.activeProof &&
    eligibleColorPreview(resolved.activeProof as LineageNode)
      ? publicEvidenceImagePath(resolved.activeProof.comparisonImage)
      : undefined;
  if (activeColorProof) return activeColorProof;

  for (const node of cut.lineage) {
    if (!eligibleColorPreview(node) || !node.comparisonImage) continue;
    const image = publicEvidenceImagePath(node.comparisonImage);
    if (image) return image;
  }

  const activeProofImage =
    resolved.activeProof &&
    eligibleCameraProof(resolved.activeProof as LineageNode)
      ? publicEvidenceImagePath(resolved.activeProof.comparisonImage)
      : undefined;
  if (activeProofImage) return activeProofImage;

  const ranked = [
    ...cut.lineage.filter(
      (node) =>
        node.primaryRecoveryProof === true && eligibleCameraProof(node),
    ),
    ...cut.lineage.filter(
      (node) =>
        node.evidence === "confirmed" && eligibleCameraProof(node),
    ),
    ...cut.lineage.filter(
      (node) => eligibleCameraProof(node),
    ),
  ];
  const seen = new Set<string>();
  for (const node of ranked) {
    if (!eligibleCameraProof(node) || !node.comparisonImage) continue;
    const image = publicEvidenceImagePath(node.comparisonImage);
    if (!image || seen.has(image)) continue;
    seen.add(image);
    return image;
  }
  return undefined;
}

function applyCleanC4DOverlay(
  cut: Cut,
  record?: C4DCleanManifestRecord,
): Cut {
  const hasExactProofRevisionAudit = Boolean(
    cut.c4dVerification?.linkageAudit &&
      cut.c4dVerification.checks.cameraProofRendered &&
      cut.lineage.some(
        (node) =>
          node.kind === "camera_proof" &&
          node.primaryRecoveryProof &&
          node.comparisonImage,
      ),
  );
  if (hasExactProofRevisionAudit) {
    const proofProjectPath = cut.c4dLinkStatus?.projectPath;
    const sceneStateMatchesProof =
      !cut.c4dSceneState?.projectPath ||
      !proofProjectPath ||
      cut.c4dSceneState.projectPath === proofProjectPath;
    return {
      ...cut,
      c4dSceneState: sceneStateMatchesProof
        ? cut.c4dSceneState
        : undefined,
    };
  }

  if (!record?.originalProxyGate) {
    return cut;
  }

  const proxyGate = record.originalProxyGate;
  const preservedCameraProofRendered = Boolean(
    cut.c4dVerification?.checks.cameraProofRendered &&
      cut.c4dVerification.cameraProof,
  );
  const preservedCameraResult =
    preservedCameraProofRendered &&
    cut.c4dVerification?.elements.camera
      ? cut.c4dVerification.elements.camera
      : "partial";
  if (
    proxyGate.status ===
    "shot_authored_proxy_cache_missing_authored_hierarchy_present"
  ) {
    const sceneAssets = proxyGate.authoredSceneAssets || {};
    const proxyCount = Math.max(
      1,
      proxyGate.authoritativeProxies?.length || 0,
    );
    const proxyDetail =
      `This shot already contains its own character root ` +
      `${sceneAssets.characterRoot || "in the source project"}, hair ` +
      `${sceneAssets.hairObject || "inside that character"}, and wardrobe ` +
      `${sceneAssets.wardrobeObject || "inside that character"}. ` +
      `${proxyCount} exact render-time Redshift proxy ` +
      `${proxyCount === 1 ? "sequence is" : "sequences are"} absent locally. ` +
      "Restore that shot's cache or validate its disabled authored hierarchy; " +
      "never import, clone, or substitute hair.";
    const components = (cut.c4dLinkStatus?.components || []).map(
      (component) => {
        if (component.key === "character") {
          return {
            ...component,
            status: "warning" as const,
            summary:
              "Shot-authored character, hair, and wardrobe exist · exact render proxy cache missing",
          };
        }
        if (component.key === "proxies") {
          return {
            ...component,
            status: "missing" as const,
            summary:
              `${proxyCount} exact in-shot Redshift proxy ` +
              `${proxyCount === 1 ? "sequence" : "sequences"} missing locally`,
          };
        }
        return component;
      },
    );

    return {
      ...cut,
      c4dLinkStatus: cut.c4dLinkStatus
        ? {
            ...cut.c4dLinkStatus,
            status: "render_dependencies_missing",
            label: "Shot-authored hair present · exact proxy cache missing",
            detail: proxyDetail,
            renderCriticalMissingFiles:
              record.renderCriticalMissingFiles ||
              cut.c4dLinkStatus.renderCriticalMissingFiles,
            components,
            dependencyLabel:
              "Exact shot proxy cache missing · no cross-shot substitution",
            verificationBlockers: ["shot_authored_proxy_missing"],
            visualReview: {
              status:
                "exact_proxy_missing_authored_hierarchy_present",
              elements: record.visualReview?.elements || {},
              notes: record.visualReview?.notes || proxyDetail,
            },
          }
        : cut.c4dLinkStatus,
      c4dVerification: {
        status: "partial",
        label: "Hair authored in this shot · proxy restore required",
        detail: proxyDetail,
        strictLinked: false,
        reviewedAt: cut.c4dVerification?.reviewedAt,
        authority:
          "Read-only C4D 2025 scene/take and Redshift proxy audit",
        elements: {
          location: "match",
          camera: preservedCameraResult,
          character: "partial",
          hair: "partial",
          wardrobe: "partial",
          materials: "not_verifiable",
        },
        notes: proxyDetail,
        blockers: ["shot_authored_proxy_missing"],
        remediation: [
          "Restore every exact in-shot Redshift proxy sequence at its saved path.",
          "If unavailable, validate only the disabled character/hair/wardrobe hierarchy already authored in this source project.",
          "Reject any recovery that imports or substitutes hair from another shot.",
        ],
        checks: {
          projectLinked: true,
          dependencyAudited: true,
          dependencyRenderSafe: false,
          proxyRenderSafe: false,
          cameraProofRendered: preservedCameraProofRendered,
          visualMatch: false,
        },
        cameraProof: cut.c4dVerification?.cameraProof,
        cameraName: cut.c4dVerification?.cameraName,
      },
      c4dSceneState: cut.c4dSceneState
        ? {
            ...cut.c4dSceneState,
            diagnosis:
              "shot_authored_character_hair_wardrobe_present_exact_proxy_cache_missing",
          }
        : cut.c4dSceneState,
    };
  }

  if (
    proxyGate.status !==
    "exact_shot_proxy_linked_runtime_incompatible"
  ) {
    return cut;
  }

  const authored = record.originalProxyGate.authoredContents || [
    "character",
    "hair",
    "wardrobe",
  ];
  const proxyDetail =
    `Exact in-shot ${record.originalProxyGate.objectPath || "RS proxy"} is linked ` +
    `and contains authored ${authored.join(", ")}. Redshift 2026.1.1 cannot ` +
    "load its mesh-format 49 cache with renderer format 47. Update the renderer; " +
    "do not import, clone, or substitute hair.";
  const components = (cut.c4dLinkStatus?.components || []).map((component) => {
    if (component.key === "character") {
      return {
        ...component,
        status: "linked" as const,
        summary:
          "Authored character and curled hair linked inside the exact in-shot RS proxy · historical render confirmed",
        renderCriticalMissingReferences: 0,
        renderCriticalMissingFiles: 0,
      };
    }
    if (component.key === "proxies") {
      return {
        ...component,
        status: "warning" as const,
        summary:
          "Exact in-shot RS proxy linked · renderer update required for mesh format 49",
        renderCriticalMissingReferences: 0,
        renderCriticalMissingFiles: 0,
      };
    }
    if (component.key === "textures") {
      return {
        ...component,
        status: "warning" as const,
        summary:
          "Render-critical textures linked · only inactive/noncritical legacy references remain",
        renderCriticalMissingReferences: 0,
        renderCriticalMissingFiles: 0,
      };
    }
    return component;
  });

  return {
    ...cut,
    c4dLinkStatus: cut.c4dLinkStatus
      ? {
          ...cut.c4dLinkStatus,
          status: "render_safe_with_warnings",
          label: "Exact authored proxy linked · renderer update required",
          detail: proxyDetail,
          projectPath:
            record.recoveryProjectPath ||
            cut.c4dLinkStatus.projectPath,
          projectName:
            fileName(record.recoveryProjectPath || undefined) ||
            cut.c4dLinkStatus.projectName,
          renderCriticalMissingReferences: 0,
          renderCriticalMissingFiles: 0,
          renderCriticalUnresolvedFiles: 0,
          components,
          dependencyLabel:
            "Render-critical links complete · Redshift proxy version blocked",
          verificationBlockers: [
            "redshift_proxy_runtime_incompatible",
          ],
          visualReview: {
            status: "runtime_blocked",
            elements: record.visualReview?.elements || {},
            notes: record.visualReview?.notes || proxyDetail,
          },
        }
      : cut.c4dLinkStatus,
    c4dVerification: {
      status: "partial",
      label: "Authored character + hair confirmed · renderer update required",
      detail: proxyDetail,
      strictLinked: false,
      reviewedAt: cut.c4dVerification?.reviewedAt,
      authority:
        "Exact shot-authored proxy plus archived production Redshift frame",
      elements: {
        location: "match",
        camera: preservedCameraResult,
        character: "match",
        hair: "match",
        wardrobe: "match",
        materials: "match",
      },
      notes: proxyDetail,
      blockers: ["redshift_proxy_runtime_incompatible"],
      remediation: [
        "Update Redshift from 2026.1.1 to 2026.8.0.",
        "Re-render the existing exact in-shot proxy; do not import hair.",
      ],
      checks: {
        projectLinked: true,
        dependencyAudited: true,
        dependencyRenderSafe: true,
        proxyRenderSafe: false,
        cameraProofRendered: preservedCameraProofRendered,
        visualMatch: false,
      },
      cameraProof: cut.c4dVerification?.cameraProof,
      cameraName: cut.c4dVerification?.cameraName,
    },
    c4dSceneState: cut.c4dSceneState
      ? {
          ...cut.c4dSceneState,
          diagnosis:
            "exact_in_shot_proxy_contains_character_hair_wardrobe_renderer_update_required",
          activeProxyCount: Math.max(1, cut.c4dSceneState.activeProxyCount),
          activeCharacterObjectCount: Math.max(
            1,
            cut.c4dSceneState.activeCharacterObjectCount,
          ),
          activeHairObjectCount: Math.max(
            1,
            cut.c4dSceneState.activeHairObjectCount,
          ),
          activeWardrobeObjectCount: Math.max(
            1,
            cut.c4dSceneState.activeWardrobeObjectCount,
          ),
        }
      : cut.c4dSceneState,
  };
}

function normalizeCutEvidenceCollections(cut: Cut): Cut {
  const cameraAudit = cut.c4dCameraCandidateAudit;
  const structuralRecovery = cut.c4dStructuralRecovery;

  return {
    ...cut,
    exportScreenshots: cut.exportScreenshots || [],
    c4dCameraCandidateAudit: cameraAudit
      ? {
          ...cameraAudit,
          historicalProjectsTested: cameraAudit.historicalProjectsTested || [],
          candidates: cameraAudit.candidates || [],
        }
      : undefined,
    c4dStructuralRecovery: structuralRecovery
      ? {
          ...structuralRecovery,
          exactRelinks: structuralRecovery.exactRelinks || [],
          proofs: structuralRecovery.proofs || [],
          elementReview: structuralRecovery.elementReview || {},
          remainingBlockers: structuralRecovery.remainingBlockers || [],
        }
      : undefined,
  };
}

function formatDate(value?: string) {
  if (!value) return "Not archived";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function compactC4DElementLabel(key: string) {
  const labels: Record<string, string> = {
    location: "LOC",
    camera: "CAM",
    character: "CHAR",
    hair: "HAIR",
    wardrobe: "WRD",
    materials: "MAT",
    lighting: "LGT",
    environment: "ENV",
  };
  return labels[key.toLowerCase()] || key.slice(0, 4).toUpperCase();
}

function EvidenceBadge({ value }: { value: Evidence | string }) {
  return (
    <span className={`evidence-badge evidence-${value}`}>
      <i aria-hidden="true" />
      {evidenceLabels[value] || value.replaceAll("_", " ")}
    </span>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="empty-state">
      <span className="empty-orbit" aria-hidden="true" />
      <p>{message}</p>
    </div>
  );
}

type InspectorLightboxImage = {
  src: string;
  alt: string;
};

function EvidenceImageButton({
  src,
  alt,
  onOpen,
  className = "",
  children,
}: {
  src: string;
  alt: string;
  onOpen: (image: InspectorLightboxImage) => void;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <button
      type="button"
      className={`detail-evidence-thumb ${className}`.trim()}
      onClick={() => onOpen({ src, alt })}
      aria-label={`Open large image: ${alt}`}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} />
      {children}
    </button>
  );
}

export function ProvenanceAtlas() {
  const [siteView, setSiteView] = useState<
    "pipeline" | "feedback" | "mockup" | "objects" | "character" | "palette"
  >("pipeline");
  const [objectView, setObjectView] = useState<"inventory" | "3d">(
    "inventory",
  );
  const [initial3DObjectId, setInitial3DObjectId] = useState("");
  const [data, setData] = useState<AtlasState | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [section, setSection] = useState("ALL");
  const [c4dStatusFilter, setC4dStatusFilter] =
    useState<C4DNavMode>("preview");
  const [selectedId, setSelectedId] = useState("");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [scanMessage, setScanMessage] = useState("");
  const [detailOpen, setDetailOpen] = useState(false);
  const [lightboxImage, setLightboxImage] =
    useState<InspectorLightboxImage | null>(null);
  const [scrub, setScrub] = useState<{
    shotId: string;
    fraction: number;
    time: number;
  } | null>(null);
  const [scrubReadyShotId, setScrubReadyShotId] = useState("");
  const [detailScrub, setDetailScrub] = useState<{
    shotId: string;
    fraction: number;
    time: number;
  } | null>(null);
  const [detailScrubReadyShotId, setDetailScrubReadyShotId] = useState("");
  const scrubVideoRef = useRef<HTMLVideoElement | null>(null);
  const detailScrubVideoRef = useRef<HTMLVideoElement | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      let response: Response;
      try {
        response = await fetch(`${API}/api/state`, { cache: "no-store" });
      } catch {
        response = await fetch("/data/state.json", { cache: "no-store" });
      }
      if (!response.ok) {
        response = await fetch("/data/state.json", { cache: "no-store" });
      }
      if (!response.ok) throw new Error("The first provenance scan has not finished.");
      const next = (await response.json()) as AtlasState;
      let cleanManifest: C4DCleanManifest = {};
      try {
        const cleanResponse = await fetch("/data/c4d-clean-manifest.json", {
          cache: "no-store",
        });
        if (cleanResponse.ok) {
          cleanManifest = (await cleanResponse.json()) as C4DCleanManifest;
        }
      } catch {
        // The primary state remains usable while the clean recovery ledger builds.
      }
      const cleanByCut = new Map(
        (cleanManifest.records || []).map((record) => [
          record.cutId,
          record,
        ]),
      );
      next.cuts = next.cuts.map((cut) =>
        applyCleanC4DOverlay(
          normalizeCutEvidenceCollections(cut),
          cleanByCut.get(cut.legacyCutId || cut.id),
        ),
      );
      setData(next);
      setSelectedId((current) => current || next.cuts[0]?.shotId || "");
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to read the archive.");
    }
  }, []);

  useEffect(() => {
    // Initial archive hydration is intentionally driven by the local fetch callback.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

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
    const video = detailScrubVideoRef.current;
    if (!video || !detailScrub) return;
    const seek = () => {
      video.pause();
      if (Math.abs(video.currentTime - detailScrub.time) > 0.015) {
        video.currentTime = detailScrub.time;
      }
    };
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      seek();
      return;
    }
    video.addEventListener("loadedmetadata", seek, { once: true });
    return () => video.removeEventListener("loadedmetadata", seek);
  }, [detailScrub]);

  useEffect(() => {
    if (!lightboxImage) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      setLightboxImage(null);
    };
    window.addEventListener("keydown", closeOnEscape, true);
    return () => {
      window.removeEventListener("keydown", closeOnEscape, true);
      document.body.style.overflow = previousOverflow;
    };
  }, [lightboxImage]);

  const sectionOptions = useMemo(() => {
    if (!data) return [];
    const byCode = new Map<string, string>();
    for (const block of data.premiere.primaryBlocks) {
      byCode.set(block.sectionCode, block.sectionName);
    }
    return Array.from(byCode, ([code, name]) => ({ code, name }));
  }, [data]);

  const plannedById = useMemo(
    () => new Map(data?.plannedShots.map((shot) => [shot.id, shot]) || []),
    [data],
  );

  const filteredCuts = useMemo(() => {
    if (!data) return [];
    const normalized = query.trim().toLowerCase();
    return data.cuts.filter((cut) => {
      const shot = cut.plannedShotId ? plannedById.get(cut.plannedShotId) : undefined;
      const matchesSection = section === "ALL" || cut.sectionCode === section;
      const matchesC4DStatus =
        c4dStatusFilter === "all" ||
        c4dStatusFilter === "preview" ||
        resolveC4DEvidenceStatus(cut).tone === c4dStatusFilter;
      const searchable = [
        cut.id,
        cut.sectionCode,
        cut.sectionName,
        cut.plannedShotId,
        shot?.description,
        shot?.fileName,
        shot?.camera,
        cut.c4dLinkStatus?.label,
        cut.c4dLinkStatus?.detail,
        cut.c4dLinkStatus?.projectName,
        cut.c4dLinkStatus?.take,
        cut.c4dVerification?.label,
        cut.c4dVerification?.notes,
        ...(cut.c4dVerification
          ? Object.entries(cut.c4dVerification.elements).flatMap(
              ([key, value]) => [key, value],
            )
          : []),
        ...(
          cut.c4dLinkStatus?.components?.flatMap((component) => [
            component.label,
            component.summary,
          ]) || []
        ),
        ...cut.lineage.flatMap((node) => [
          node.label,
          node.path,
          ...(node.tags || []).flatMap((tag) => [tag.label, tag.detail]),
        ]),
        ...cut.exportScreenshots.flatMap((item) => [
          item.label,
          item.exportPath,
          ...item.producers.flatMap((producer) => [
            producer.label,
            producer.sequence,
            producer.projectPath,
          ]),
        ]),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return (
        matchesSection &&
        matchesC4DStatus &&
        (!normalized || searchable.includes(normalized))
      );
    });
  }, [c4dStatusFilter, data, plannedById, query, section]);

  const selected =
    filteredCuts.find((cut) => cut.shotId === selectedId) ||
    data?.cuts.find((cut) => cut.shotId === selectedId) ||
    filteredCuts[0];
  const selectedShot = selected?.plannedShotId
    ? plannedById.get(selected.plannedShotId)
    : undefined;
  const selectedShotName = selected
    ? deriveShotDisplayName({
        isGap: selected.isGap,
        plannedShotId: selected.plannedShotId,
        chapter: selected.sectionCode,
        sourceClipName: selected.sourceSegments[0]?.clipName,
        plannedFileName: selectedShot?.fileName,
        plannedAction: selectedShot?.action,
        plannedDescription: selectedShot?.description,
      })
    : "";
  const selectedC4DEvidence = selected
    ? resolveC4DEvidenceStatus(selected)
    : undefined;
  const selectedCameraProof = selected
    ? selectedC4DEvidence?.activeProof ||
      selected.lineage.find(
        (node) =>
          node.kind === "camera_proof" &&
          node.primaryRecoveryProof &&
          node.comparisonImage,
      ) ||
      selected.lineage.find(
        (node) =>
          node.kind === "camera_proof" &&
          node.recoveryProof &&
          node.comparisonImage,
      ) ||
      selected.lineage.find(
        (node) => node.kind === "camera_proof" && node.comparisonImage,
      ) ||
      selected.lineage.find(
        (node) => node.kind === "camera" && node.comparisonImage,
      )
    : undefined;
  const selectedCameraNode = selected?.lineage.find(
    (node) => node.kind === "camera",
  );
  const selectedCameraProofImage =
    selected?.c4dVerification?.cameraProof &&
    !isCompositeEvidenceImage(selected.c4dVerification.cameraProof)
      ? selected.c4dVerification.cameraProof
      : selectedCameraProof?.comparisonImage &&
          !isCompositeEvidenceImage(selectedCameraProof.comparisonImage)
        ? selectedCameraProof.comparisonImage
        : undefined;
  const selectedCameraProofRendered = Boolean(
    selectedCameraProofImage &&
      selected?.c4dVerification?.checks.cameraProofRendered,
  );
  const selectedCameraProofQualified = Boolean(
    selectedC4DEvidence?.tone === "redshift-verified" ||
      selectedC4DEvidence?.tone === "camera-verified",
  );
  const selectedCameraMatchConfirmed = Boolean(
    selectedCameraProofRendered && selectedC4DEvidence?.cameraMatched,
  );
  const selectedCameraProofText = [
    selectedCameraProof?.detail,
    selectedCameraProof?.comparisonImage,
    selectedCameraProof?.confirmationMethod,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  const selectedCameraProofIsGrey = Boolean(
    selectedCameraProof?.fullColorProof !== true &&
      (selectedCameraProof?.redshiftProof === true ||
        /\b(?:grey|gray|neutral)\b/.test(selectedCameraProofText)),
  );
  const selectedFreshFullColorRenderPaths = new Set(
    [
      ...(selected?.lineage
        .filter((node) =>
          isFreshFullColorEvidence(
            node.comparisonImage,
            node.fullColorRender,
            node.freshAuditRender,
          ),
        )
        .map((node) => publicEvidenceImagePath(node.comparisonImage)) || []),
      publicEvidenceImagePath(
        selected?.c4dVerification?.materialCompatibilityAudit?.outputPath ||
          selected?.c4dVerification?.materialCompatibilityAudit?.publicPath,
      ),
    ].filter((path): path is string => Boolean(path)),
  );
  const selectedFreshFullColorRenderCount =
    selectedFreshFullColorRenderPaths.size;
  const selectedFreshFullColorRenderLabel =
    selectedFreshFullColorRenderCount > 0
      ? `${selectedFreshFullColorRenderCount} FULL-COLOR ${
          selectedFreshFullColorRenderCount === 1 ? "TEST" : "TESTS"
        } RETAINED`
      : "FULL COLOR MISSING";
  const selectedCameraProofBadge =
    selectedC4DEvidence?.tone === "redshift-verified"
      ? "FULL-COLOR REDSHIFT MATCH"
      : selectedC4DEvidence?.tone === "camera-verified" &&
          selectedC4DEvidence?.reason ===
            "redshift_camera_match_dependencies_incomplete"
        ? "FULL-COLOR REDSHIFT CAMERA MATCH · STRICT GATE INCOMPLETE"
        : selectedC4DEvidence?.tone === "camera-verified" &&
          selectedC4DEvidence?.reason === "hardware_camera_match"
        ? `HARDWARE CAMERA MATCH · ${selectedFreshFullColorRenderLabel}`
        : selectedC4DEvidence?.tone === "camera-verified" &&
            selectedC4DEvidence?.reason === "redshift_grey_camera_match"
          ? `GREY REDSHIFT CAMERA MATCH · ${selectedFreshFullColorRenderLabel}`
          : selectedC4DEvidence?.tone === "camera-verified"
            ? `GREY CAMERA MATCH · ${selectedFreshFullColorRenderLabel}`
        : selectedCameraProofRendered &&
            selectedC4DEvidence?.cameraMatched &&
            selectedCameraProofIsGrey
          ? `GREY CAMERA MATCH · ${selectedFreshFullColorRenderLabel}`
          : selectedCameraProofRendered &&
              selectedC4DEvidence?.tone === "unconfirmed"
            ? "SOURCE FILE UNCONFIRMED"
            : selectedCameraProofRendered &&
                selectedC4DEvidence?.reason === "camera_mismatch"
              ? "CAMERA MISMATCH"
              : selectedCameraProofRendered
                ? "TEST NOT CONFIRMED"
                : "NOT CONFIRMED";
  const selectedProcessImages = (() => {
    if (!selected) return [];
    const images = new Map<
      string,
      {
        image: string;
        label: string;
        kind: string;
        detail: string;
        evidence: string;
        composite: boolean;
        fullColor: boolean;
      }
    >();
    const addImage = (
      image: string | undefined,
      label: string,
      kind: string,
      detail: string,
      evidence: string,
      fullColor = false,
    ) => {
      const publicImage = publicEvidenceImagePath(image);
      if (
        !publicImage ||
        publicImage === selectedCameraProofImage ||
        images.has(publicImage)
      ) {
        return;
      }
      images.set(publicImage, {
        image: publicImage,
        label,
        kind,
        detail,
        evidence,
        composite: isCompositeEvidenceImage(publicImage),
        fullColor,
      });
    };
    for (const node of selected.lineage) {
      if (!node.comparisonImage) continue;
      const kind =
        node.kind === "camera_proof"
          ? "Camera test"
          : node.kind === "render_reference"
            ? "Historical render reference"
            : node.kind === "material_diagnostic"
              ? "Material diagnostic"
              : node.kind === "visual_match"
                ? "Frame comparison"
                : nodeLabels[node.kind] || "Process image";
      addImage(
        node.comparisonImage,
        node.label,
        kind,
        node.confirmationMethod || node.detail || "Recorded process image",
        node.visualVerificationStatus ||
          evidenceLabels[node.evidence] ||
          node.evidence,
        isFreshFullColorEvidence(
          node.comparisonImage,
          node.fullColorRender,
          node.freshAuditRender,
        ),
      );
    }
    addImage(
      selected.c4dVerification?.comparisonImage,
      `${selected.id} camera comparison`,
      "Comparison sheet",
      "Camera test beside its canonical source reference",
      "Reference",
    );
    addImage(
      selected.c4dVerification?.renderReference,
      `${selected.id} retained production frame`,
      "Historical render reference",
      "Historical output retained for comparison only; never a camera proof",
      "Reference only",
    );
    const materialAudit =
      selected.c4dVerification?.materialCompatibilityAudit;
    addImage(
      materialAudit?.publicPath || materialAudit?.outputPath,
      `${selected.id} material-runtime diagnostic`,
      "Material diagnostic",
      materialAudit?.runtimeDetail ||
        "Current-runtime material compatibility render",
      materialAudit?.status || "Diagnostic",
      Boolean(
        materialAudit?.fullColor === true &&
          materialAudit?.freshAuditRender === true,
      ),
    );
    addImage(
      materialAudit?.diagnosticComparisonPath ||
        (materialAudit?.comparisonPath as string | undefined),
      `${selected.id} material comparison`,
      "Material comparison",
      materialAudit?.runtimeDetail ||
        "Current-runtime material result beside the canonical reference",
      materialAudit?.status || "Diagnostic",
    );
    if (materialAudit) {
      for (const [key, value] of Object.entries(materialAudit)) {
        if (
          typeof value !== "string" ||
          !/(?:output|comparison)path$/i.test(key) ||
          !/\.(?:avif|gif|jpe?g|png|webp)$/i.test(value)
        ) {
          continue;
        }
        addImage(
          value,
          `${selected.id} ${key
            .replace(/Path$/, "")
            .replace(/([a-z])([A-Z])/g, "$1 $2")
            .toLowerCase()}`,
          /comparison/i.test(key)
            ? "Material comparison"
            : "Material diagnostic",
          materialAudit.runtimeDetail ||
            "Current-runtime material compatibility process image",
          materialAudit.status || "Diagnostic",
        );
      }
    }
    return [...images.values()].sort(
      (left, right) => Number(right.fullColor) - Number(left.fullColor),
    );
  })();
  const selectedExactCutAudit =
    selected?.c4dLinkStatus?.exactCutAudit;
  const selectedProofLinkage = selectedExactCutAudit
    ? undefined
    : selected?.c4dVerification?.linkageAudit;
  const selectedRecoverySteps =
    selected?.c4dVerification?.agentReadyChecklist?.length
      ? selected.c4dVerification.agentReadyChecklist
      : selected?.c4dVerification?.remediation || [];

  async function post(endpoint: string, body: object) {
    const response = await fetch(`${API}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || "The local action failed.");
    }
    return response.json();
  }

  async function reveal(path?: string) {
    if (!path) return;
    if (!isLocalProductionBrowser()) {
      try {
        await copyProductionPath(path);
        setScanMessage(`Copied ${fileName(path)} · Finder actions stay on the production Mac.`);
      } catch {
        setScanMessage("Finder actions are available in the local production app.");
      }
      return;
    }
    try {
      await post("/api/reveal", { path });
    } catch (actionError) {
      setScanMessage(actionError instanceof Error ? actionError.message : "Unable to reveal file.");
    }
  }

  async function revealAndCopyPath(path?: string) {
    if (!path) return;
    if (!isLocalProductionBrowser()) {
      try {
        await copyProductionPath(path);
        setScanMessage(`Copied ${fileName(path)} · open it on the production Mac.`);
      } catch {
        setScanMessage("Source-file actions are available in the local production app.");
      }
      return;
    }
    try {
      await post("/api/reveal", { path, copyPath: true });
      setScanMessage(`Opened in Finder · copied ${fileName(path)}`);
    } catch (actionError) {
      setScanMessage(
        actionError instanceof Error
          ? actionError.message
          : "Unable to reveal and copy source.",
      );
    }
  }

  async function openNode(node: LineageNode) {
    if (!node.path && !node.projectPath) return;
    if (!isLocalProductionBrowser()) {
      const path = node.projectPath || node.path;
      try {
        await copyProductionPath(path!);
        setScanMessage(`Copied ${fileName(path)} · creative-app launch stays on the production Mac.`);
      } catch {
        setScanMessage("Creative-app launch is available in the local production app.");
      }
      return;
    }
    try {
      await post("/api/open", {
        path: node.projectPath || node.path,
        kind: node.kind,
      });
    } catch (actionError) {
      setScanMessage(actionError instanceof Error ? actionError.message : "Unable to open source.");
    }
  }

  function updateScrub(
    event: ReactPointerEvent<HTMLDivElement>,
    cut: Cut,
  ) {
    if (!data || cut.isGap) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const fraction = Math.max(
      0,
      Math.min(1, (event.clientX - bounds.left) / bounds.width),
    );
    const scrubStart = cut.scrubStart ?? cut.start;
    const scrubEnd = cut.scrubEnd ?? cut.end;
    const lastFrame = Math.max(
      scrubStart,
      scrubEnd - 1 / data.groundTruth.fps,
    );
    setScrub({
      shotId: cut.shotId,
      fraction,
      time: scrubStart + fraction * (lastFrame - scrubStart),
    });
  }

  function updateDetailScrub(
    event: ReactPointerEvent<HTMLDivElement>,
    cut: Cut,
  ) {
    if (!data || cut.isGap) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const fraction = Math.max(
      0,
      Math.min(1, (event.clientX - bounds.left) / bounds.width),
    );
    const scrubStart = cut.scrubStart ?? cut.start;
    const scrubEnd = cut.scrubEnd ?? cut.end;
    const lastFrame = Math.max(
      scrubStart,
      scrubEnd - 1 / data.groundTruth.fps,
    );
    setDetailScrub({
      shotId: cut.shotId,
      fraction,
      time: scrubStart + fraction * (lastFrame - scrubStart),
    });
  }

  if (!data) {
    return (
      <main className="loading-shell">
        <p className="eyebrow">PARACOSM</p>
        <h1>{error || "Reading the evidence archive…"}</h1>
        <p className="loading-note">
          The first pass can take a few minutes while reference frames and source indices are archived.
        </p>
        {error && (
          <button className="primary-button" onClick={() => void load()}>
            Try again
          </button>
        )}
      </main>
    );
  }

  const cleanConform = data.revisedConform?.authorityKind === "clean_v1_v2";
  const canonicalEdl = Boolean(data.canonicalShotList);
  const frameAlignedConform =
    (data.revisedConform?.visualAlignment?.appliedCorrections?.length || 0) > 0;
  const selectedSourceTrack = selected?.sourceSegments[0]?.sourceTrack;
  const selectedTrackLabel = selectedSourceTrack
    ? `V${selectedSourceTrack}`
    : cleanConform && !canonicalEdl
      ? "V1/V2"
      : "V1";

  return (
    <main className="atlas-shell">
      <header className="topbar">
        <div className="brand-group">
          <a
            className="brand-ground-truth"
            href={data.groundTruth.frameIoUrl}
            target="_blank"
            rel="noreferrer"
            title="Open Ground Truth"
          >
            <h1>PARACOSM</h1>
          </a>
        </div>
        <nav className="site-nav" aria-label="Paracosm views">
          <button
            className={siteView === "pipeline" ? "active" : ""}
            onClick={() => setSiteView("pipeline")}
          >
            Pipeline
          </button>
          <button
            className={siteView === "feedback" ? "active" : ""}
            onClick={() => setSiteView("feedback")}
          >
            Feedback
          </button>
          <button
            className={siteView === "mockup" ? "active" : ""}
            onClick={() => setSiteView("mockup")}
          >
            Mockup
          </button>
          <button
            className={siteView === "objects" ? "active" : ""}
            onClick={() => setSiteView("objects")}
          >
            Objects
          </button>
          <button
            className={siteView === "character" ? "active" : ""}
            onClick={() => setSiteView("character")}
          >
            Character
          </button>
          <button
            className={siteView === "palette" ? "active" : ""}
            onClick={() => setSiteView("palette")}
          >
            Palette
          </button>
        </nav>
      </header>

      {siteView === "feedback" ? (
        <FeedbackTracker
          apiBase={API}
          fps={data.groundTruth.fps}
          hoverProxy={data.groundTruth.hoverProxy}
          cuts={data.cuts.map((cut) => ({
            shotName: deriveShotDisplayName({
              isGap: cut.isGap,
              plannedShotId: cut.plannedShotId,
              chapter: cut.sectionCode,
              sourceClipName: cut.sourceSegments[0]?.clipName,
              plannedFileName: cut.plannedShotId
                ? plannedById.get(cut.plannedShotId)?.fileName
                : null,
              plannedAction: cut.plannedShotId
                ? plannedById.get(cut.plannedShotId)?.action
                : null,
              plannedDescription: cut.plannedShotId
                ? plannedById.get(cut.plannedShotId)?.description
                : null,
            }),
            description:
              (cut.plannedShotId
                ? plannedById.get(cut.plannedShotId)?.description
                : null) ||
              (cut.isGap ? "No active picture" : cut.sectionName),
            id: cut.id,
            shotId: cut.shotId,
            thumbnail: cut.thumbnail,
            scrubProxy: cut.scrubProxy,
            scrubStart: cut.scrubStart,
            scrubEnd: cut.scrubEnd,
            sectionCode: cut.sectionCode,
            timecode: cut.timecode,
            endTimecode: cut.endTimecode,
            start: cut.start,
            end: cut.end,
            duration: cut.duration,
            isGap: cut.isGap,
            lineage: cut.lineage,
            c4dVerification: cut.c4dVerification,
          }))}
        />
      ) : siteView === "objects" ? (
        objectView === "3d" ? (
          <Object3DGallery
            initialObjectId={initial3DObjectId}
            onModeChange={() => {
              setInitial3DObjectId("");
              setObjectView("inventory");
            }}
          />
        ) : (
          <ObjectInventory
            onModeChange={() => {
              setInitial3DObjectId("");
              setObjectView("3d");
            }}
          />
        )
      ) : siteView === "character" ? (
        <CharacterLibrary />
      ) : siteView === "mockup" ? (
        <MockupGallery
          fps={data.groundTruth.fps}
          hoverProxy={data.groundTruth.hoverProxy}
          cuts={data.cuts.map((cut) => ({
            id: cut.id,
            shotId: cut.shotId,
            shotName: deriveShotDisplayName({
              isGap: cut.isGap,
              plannedShotId: cut.plannedShotId,
              chapter: cut.sectionCode,
              sourceClipName: cut.sourceSegments[0]?.clipName,
              plannedFileName: cut.plannedShotId
                ? plannedById.get(cut.plannedShotId)?.fileName
                : null,
              plannedAction: cut.plannedShotId
                ? plannedById.get(cut.plannedShotId)?.action
                : null,
              plannedDescription: cut.plannedShotId
                ? plannedById.get(cut.plannedShotId)?.description
                : null,
            }),
            description:
              (cut.plannedShotId
                ? plannedById.get(cut.plannedShotId)?.description
                : null) ||
              (cut.isGap ? "No active picture" : cut.sectionName),
            sectionCode: cut.sectionCode,
            thumbnail: cut.thumbnail,
            scrubProxy: cut.scrubProxy,
            scrubStart: cut.scrubStart,
            scrubEnd: cut.scrubEnd,
            start: cut.start,
            end: cut.end,
            duration: cut.duration,
            timecode: cut.timecode,
            isGap: cut.isGap,
          }))}
        />
      ) : siteView === "palette" ? (
        <InstagramPalette />
      ) : (
        <div
          className={`workspace ${detailOpen ? "right-open" : ""}`}
        >
        <section className="cut-browser">
          <div className="metric-row">
            {[
              [
                "Edit cuts",
                data.summary.editCuts,
                data.revisedConform?.active
                  ? `${data.summary.manualConformPictureClips} picture · ${data.summary.manualConformIntentionalBlanks} true blanks`
                  : `${data.summary.framePairsVisuallyConfirmed} frame matches`,
              ],
              ["Planned shots", data.summary.plannedShots, "shotlist reference"],
              [
                "Source clips",
                data.summary.sourceConformSegments,
                data.revisedConform?.active
                  ? cleanConform
                    ? data.summary.sourceMediaIncompleteClips
                      ? `${data.summary.sourceMediaCompleteClips} complete · ${data.summary.sourceMediaIncompleteClips} incomplete`
                      : canonicalEdl
                        ? `${data.summary.manualConformCanonicalSources} canonical · EDL V1`
                        : `${data.summary.manualConformCanonicalSources} canonical · V1 + V2`
                    : `${data.summary.manualConformCanonicalSources} canonical · V6 + V7`
                  : data.summary.premiereConformVerified
                    ? `${data.summary.premiereConformClips} verified in Premiere`
                    : "terminal image segments",
              ],
              ["C4D projects", data.summary.c4dProjects, `${data.summary.exactRenderProjectMatches} exact render links`],
              [
                "Cameras",
                `${data.summary.cameraProofRendered}/${data.summary.cameraProofTargets}`,
                `${data.summary.cameraProofFailed} failed · ${data.summary.cameraProofUnresolved} unmapped`,
              ],
              [
                "C4D linkage",
                `${data.summary.c4dDependencyAuditedCuts}/${data.summary.pictureCuts}`,
                data.summary.c4dMissingRenderDependencyCuts ||
                  data.summary.c4dDependencyUnavailableCuts
                  ? `${data.summary.c4dMissingRenderDependencyCuts} missing · ${data.summary.c4dDependencyUnavailableCuts} unmapped`
                  : "every mapped source fully linked",
              ],
            ].map(([label, value, note]) => (
              <div className="metric" key={String(label)}>
                <span>{label}</span>
                <strong>{value}</strong>
                <small>{note}</small>
              </div>
            ))}
          </div>

          <section className="timeline-panel">
            <div className="timeline-heading">
              <div>
                <span>FINAL ASSEMBLY</span>
                <strong>{data.premiere.sequence}</strong>
              </div>
              <div className="timeline-status">
                {data.premiereConform.success ? (
                  <span className="verified-badge">
                    {canonicalEdl ? "CANONICAL EDL LOCKED" : "PREMIERE VERIFIED"}
                  </span>
                ) : null}
                <small>{data.groundTruth.durationTimecode}</small>
              </div>
            </div>
            <div className="timeline-row-label">
              <span>
                {data.revisedConform?.active
                  ? cleanConform
                    ? canonicalEdl
                      ? "CANONICAL SOURCE RENDERS / EDL V1"
                      : "CANONICAL SOURCE RENDERS / V1 + V2"
                    : "MANUALLY ALIGNED SOURCES / V6 + V7 CANONICAL"
                  : "SOURCE IMAGE SEQUENCES / ABOVE"}
              </span>
              <small>
                {data.revisedConform?.active
                  ? `${
                      frameAlignedConform
                        ? "saved sources + exact reference-frame alignment"
                        : canonicalEdl
                          ? "stable shot IDs + exact EDL record/source In/Out"
                          : "saved timeline + source In/Out"
                    } · source sequences ${data.revisedConform.sourceImageFrameRate?.toFixed(2)} fps`
                  : `${data.conform.segments.length} clips · ${data.conform.summary.omittedSubframeEvents} audited subframe event`}
              </small>
            </div>
            {(data.revisedConform?.active
              ? cleanConform
                ? canonicalEdl
                  ? [["exact_match", "V1", "CANONICAL EDL", 1]]
                  : [
                    ["exact_match", "V1", "CANONICAL", 1],
                    ["exact_match", "V2", "CANONICAL", 2],
                  ]
                : [
                    ["older_than_cut", "V5", "ROSE / OLDER", undefined],
                    ["exact_match", "V6", "IRIS / CANONICAL", undefined],
                    ["newer_than_cut", "V7", "GREEN / CANONICAL", undefined],
                  ]
              : [[undefined, "SRC", "TERMINAL SOURCES", undefined]]
            ).map(([role, track, label, sourceTrack]) => (
              <div className="manual-source-row" key={track}>
                {data.revisedConform?.active && (
                  <span className={`manual-source-row-label role-${role}`}>
                    <b>{track}</b>
                    <small>{label}</small>
                  </span>
                )}
                <div className="source-timeline">
                  {data.conform.segments
                    .filter(
                      (segment) =>
                        (!role || segment.role === role) &&
                        (!sourceTrack || segment.sourceTrack === sourceTrack),
                    )
                    .map((segment) => (
                      <button
                        key={segment.id}
                        className={`source-segment source-${segment.sectionCode.toLowerCase()} ${
                          segment.role ? `source-role-${segment.role}` : ""
                        }`}
                        style={{
                          left: `${(segment.finalStart / data.groundTruth.duration) * 100}%`,
                          width: `${Math.max(0.22, ((segment.finalEnd - segment.finalStart) / data.groundTruth.duration) * 100)}%`,
                        }}
                        onClick={() => {
                          const cut = data.cuts.find(
                            (candidate) =>
                              candidate.start < segment.finalEnd &&
                              candidate.end > segment.finalStart,
                          );
                          if (cut) setSelectedId(cut.shotId);
                        }}
                        title={`${segment.id} · ${segment.sourceEdit} · final ${segment.finalStartFrame ?? "?"}–${segment.finalEndFrame ?? "?"} · source ${segment.selectedFirstFrame ?? "?"}–${segment.selectedLastFrame ?? "?"} · ${shortPath(segment.sourcePath)}`}
                      >
                        <span>{segment.id.replace("USER-SRC-", "")}</span>
                      </button>
                    ))}
                </div>
              </div>
            ))}
            {data.revisedConform?.active && (
              <div className="manual-track-legend">
                {cleanConform ? (
                  <>
                    <span className="role-exact_match">
                      <i />{" "}
                      {canonicalEdl
                        ? "V1 · canonical EDL picture track"
                        : "V1 · canonical render clips"}
                    </span>
                    {!canonicalEdl && (
                      <span className="role-exact_match">
                        <i /> V2 · canonical render clips
                      </span>
                    )}
                  </>
                ) : (
                  <>
                    <span className="role-older_than_cut">
                      <i /> V5 Rose · older
                    </span>
                    <span className="role-exact_match">
                      <i /> V6 Iris · canonical
                    </span>
                    <span className="role-newer_than_cut">
                      <i /> V7 Green · canonical
                    </span>
                  </>
                )}
              </div>
            )}
            <div className="timeline-row-label block-row-label">
              <span>{cleanConform ? "A1 CHAPTER CUTS" : "V1 FINAL CUT / BELOW"}</span>
              <small>
                {data.premiere.primaryBlocks.length} {cleanConform ? "chapters" : "blocks"}
              </small>
            </div>
            <div className="block-timeline">
              {data.premiere.primaryBlocks.map((block, index) => (
                <button
                  key={block.id}
                  className={`block block-${index + 1} ${section === block.sectionCode ? "selected" : ""}`}
                  style={{
                    left: `${(block.start / data.groundTruth.duration) * 100}%`,
                    width: `${Math.max(1.3, (block.duration / data.groundTruth.duration) * 100)}%`,
                  }}
                  onClick={() =>
                    setSection((current) => (current === block.sectionCode ? "ALL" : block.sectionCode))
                  }
                  title={`${block.name} · ${block.duration.toFixed(1)} seconds`}
                >
                  <span>{block.sectionCode}</span>
                </button>
              ))}
              {data.cuts.map((cut) => (
                <i
                  key={cut.shotId}
                  className="cut-tick"
                  style={{ left: `${(cut.start / data.groundTruth.duration) * 100}%` }}
                />
              ))}
            </div>
            <div className="timeline-legend">
              {data.premiere.primaryBlocks.map((block, index) => (
                <button
                  key={block.id}
                  onClick={() => setSection(block.sectionCode)}
                  className={section === block.sectionCode ? "active" : ""}
                >
                  <i className={`legend-${index + 1}`} />
                  <span>{block.sectionName}</span>
                  <small>{block.duration.toFixed(1)}s</small>
                </button>
              ))}
            </div>
          </section>

          <div className="browser-tools">
            <div className="section-tabs">
              <button
                className={section === "ALL" ? "active" : ""}
                onClick={() => setSection("ALL")}
              >
                All cuts <b>{data.cuts.length}</b>
              </button>
              {sectionOptions.map((option) => (
                <button
                  key={option.code}
                  className={section === option.code ? "active" : ""}
                  onClick={() => setSection(option.code)}
                  title={option.name}
                >
                  {option.code}
                </button>
              ))}
            </div>
            <label className="search-box">
              <span aria-hidden="true">⌕</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search cut, planned ID, camera, or source file"
                aria-label="Search provenance"
              />
              {query && (
                <button onClick={() => setQuery("")} aria-label="Clear search">
                  ×
                </button>
              )}
            </label>
            <label
              className={`c4d-status-filter c4d-status-filter-${c4dStatusFilter}`}
            >
              <span>C4D</span>
              <select
                value={c4dStatusFilter}
                onChange={(event) => {
                  setC4dStatusFilter(
                    event.target.value as
                      C4DNavMode,
                  );
                  setScrub(null);
                  setScrubReadyShotId("");
                }}
                aria-label="Filter cuts by C4D state"
              >
                <option value="all">ALL</option>
                <option value="redshift-verified">GREEN</option>
                <option value="camera-verified">YELLOW</option>
                <option value="file-confirmed">BLACK</option>
                <option value="unconfirmed">GRAY</option>
                <option value="preview">PREVIEW</option>
              </select>
            </label>
            <div className="view-toggle" aria-label="Change cut layout">
              <button
                className={view === "grid" ? "active" : ""}
                onClick={() => setView("grid")}
                aria-label="Grid view"
              >
                ▦
              </button>
              <button
                className={view === "list" ? "active" : ""}
                onClick={() => setView("list")}
                aria-label="List view"
              >
                ☷
              </button>
            </div>
          </div>

          <div className="results-heading">
            <span>
              {filteredCuts.length} of {data.cuts.length} authoritative cut intervals
              {c4dStatusFilter !== "all"
                ? ` · ${
                    c4dStatusFilter === "preview"
                      ? "preview"
                      : {
                          "redshift-verified": "green",
                          "camera-verified": "yellow",
                          "file-confirmed": "black",
                          unconfirmed: "gray",
                        }[c4dStatusFilter]
                  }`
                : ""}
            </span>
            <small>
              {data.revisedConform?.active
                ? cleanConform
                  ? frameAlignedConform
                    ? "V1/V2 sources · exact film-frame boundaries · corrections preserved in audit"
                    : "Exact saved V1/V2 timeline + source In/Out · no trim recalculation"
                  : "Exact saved V1 timeline In/Out · no trim recalculation"
                : `Boundary detector ${data.method.boundaryThreshold.toFixed(2)} · project confirmation pending`}
            </small>
          </div>

          {filteredCuts.length ? (
            <div className={`cut-grid cut-${view}`}>
              {filteredCuts.map((cut) => {
                const shot = cut.plannedShotId ? plannedById.get(cut.plannedShotId) : undefined;
                const shotName = deriveShotDisplayName({
                  isGap: cut.isGap,
                  plannedShotId: cut.plannedShotId,
                  chapter: cut.sectionCode,
                  sourceClipName: cut.sourceSegments[0]?.clipName,
                  plannedFileName: shot?.fileName,
                  plannedAction: shot?.action,
                  plannedDescription: shot?.description,
                });
                const previewMode = c4dStatusFilter === "preview";
                const directFullColorCameraProof =
                  publicEvidenceImagePath(
                    cut.c4dVerification?.cameraProof,
                  );
                const previewImage = previewMode
                  ? directFullColorCameraProof &&
                    /(?:full[-_]color|donor[-_]materials|exact191[-_]ocio)/i.test(
                      directFullColorCameraProof,
                    ) &&
                    !isCompositeEvidenceImage(
                      directFullColorCameraProof,
                    )
                    ? directFullColorCameraProof
                    : bestC4DPreviewImage(cut)
                  : undefined;
                return (
                  <article
                    key={cut.shotId}
                    data-cut-id={cut.id}
                    data-shot-id={cut.shotId}
                    data-c4d-preview={
                      previewMode
                        ? previewImage
                          ? "best-available"
                          : "missing"
                        : undefined
                    }
                    data-c4d-preview-image={previewImage}
                    data-c4d-direct-proof={directFullColorCameraProof}
                    className={`cut-card ${
                      selected?.shotId === cut.shotId ? "selected" : ""
                    }`}
                  >
                    <button
                      className="cut-card-trigger"
                      aria-label={`Open ${cut.id} details`}
                      onClick={() => {
                        setSelectedId(cut.shotId);
                        setDetailOpen(true);
                      }}
                    >
                      <div
                        className={`cut-frame ${
                          cut.isGap ? "" : "scrubbable"
                        } ${previewMode ? "c4d-preview-mode" : ""}`}
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
                          cut.isGap
                            ? undefined
                            : previewMode
                              ? "Move left to right to reveal and scrub the original shot"
                              : "Move left to right to scrub this cut"
                        }
                      >
                        {cut.isGap ? (
                          <div
                            className="gap-frame"
                            aria-label="No active picture"
                          />
                        ) : (
                          <>
                            {previewMode ? (
                              previewImage ? (
                                /* eslint-disable-next-line @next/next/no-img-element */
                                <img
                                  key={previewImage}
                                  className="c4d-preview-proof"
                                  src={previewImage}
                                  alt={`Best available C4D preview for ${cut.id}`}
                                />
                              ) : (
                                <div
                                  className="c4d-preview-missing"
                                  aria-label={`No verified C4D camera match available for ${cut.id}`}
                                >
                                  <span aria-hidden="true" />
                                </div>
                              )
                            ) : (
                              /* eslint-disable-next-line @next/next/no-img-element */
                              <img
                                src={cut.thumbnail}
                                alt={`Reference frame for ${cut.id}`}
                              />
                            )}
                            {scrub?.shotId === cut.shotId && (
                              <video
                                ref={scrubVideoRef}
                                className={`cut-scrub-video ${
                                  scrubReadyShotId === cut.shotId ? "ready" : ""
                                }`}
                                src={
                                  cut.scrubProxy ||
                                  data.groundTruth.hoverProxy ||
                                  "/archive/reference/paracosm-hover.mp4"
                                }
                                poster={cut.thumbnail}
                                muted
                                playsInline
                                preload="auto"
                                aria-hidden="true"
                                onSeeked={() =>
                                  setScrubReadyShotId(cut.shotId)
                                }
                              />
                            )}
                            <span className="scrub-track" aria-hidden="true">
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
                      </div>
                      <ShotCardDetails
                        chapter={cut.sectionCode}
                        name={shotName}
                        duration={cut.duration}
                        cutNumber={cut.id}
                        timecode={cut.timecode}
                        description={
                          shot?.description ||
                          (cut.isGap ? "No active picture" : cut.sectionName)
                        }
                      />
                    </button>
                    <SourceApplicationLinks
                      cut={cut}
                      apiBase={API}
                      onMessage={setScanMessage}
                    />
                  </article>
                );
              })}
            </div>
          ) : (
            <EmptyState message="No cuts match this evidence view." />
          )}
        </section>

        <RightInspectorPanel
          open={detailOpen}
          onOpenChange={setDetailOpen}
          label="Details"
          panelClassName="detail-panel pipeline-inspector"
          contentClassName="detail-panel-content"
          contentId="pipeline-inspector-content"
        >
          {selected ? (
            <>
              <section className="pipeline-detail-hero">
                <div
                  className={`detail-frame detail-hero-frame ${
                    selected.isGap ? "" : "scrubbable"
                  }`}
                  onPointerEnter={(event) => {
                    setDetailScrubReadyShotId("");
                    updateDetailScrub(event, selected);
                  }}
                  onPointerMove={(event) =>
                    updateDetailScrub(event, selected)
                  }
                  onPointerLeave={() => {
                    setDetailScrub(null);
                    setDetailScrubReadyShotId("");
                  }}
                  title={
                    selected.isGap
                      ? undefined
                      : "Move left to right to scrub this cut"
                  }
                  aria-label={
                    selected.isGap
                      ? `${selected.id} editorial gap`
                      : `Scrub ${selected.id}`
                  }
                >
                  {selected.isGap ? (
                    <div className="gap-frame detail-gap">
                      <b>EDITORIAL GAP</b>
                      <small>
                        {cleanConform
                          ? "no active V1/V2 source-render clip"
                          : "no active picture block in Paracosm Full Copy 01"}
                      </small>
                    </div>
                  ) : (
                    <>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={selected.thumbnail}
                        alt={`Reference frame for ${selected.id}`}
                      />
                      {detailScrub?.shotId === selected.shotId && (
                        <video
                          ref={detailScrubVideoRef}
                          className={`cut-scrub-video ${
                            detailScrubReadyShotId === selected.shotId
                              ? "ready"
                              : ""
                          }`}
                          src={
                            selected.scrubProxy ||
                            data.groundTruth.hoverProxy ||
                            "/archive/reference/paracosm-hover.mp4"
                          }
                          poster={selected.thumbnail}
                          muted
                          playsInline
                          preload="auto"
                          aria-hidden="true"
                          onSeeked={() =>
                            setDetailScrubReadyShotId(selected.shotId)
                          }
                        />
                      )}
                      <span className="scrub-track" aria-hidden="true">
                        <i
                          style={{
                            width: `${
                              detailScrub?.shotId === selected.shotId
                                ? detailScrub.fraction * 100
                                : 0
                            }%`,
                          }}
                        />
                      </span>
                    </>
                  )}
                  <div className="frame-ruler">
                    <span>{selected.timecode}</span>
                    <i />
                    <span>{selected.endTimecode}</span>
                  </div>
                </div>
                <ShotCardDetails
                  chapter={selected.sectionCode}
                  name={selectedShotName}
                  duration={selected.duration}
                  cutNumber={selected.id}
                  timecode={selected.timecode}
                  description={
                    selectedShot?.description ||
                    (selected.isGap ? "No active picture" : selected.sectionName)
                  }
                  tags={<EvidenceBadge value={selected.confidence} />}
                />
              </section>

              <section className="planned-shot pipeline-flow-section">
                <div className="detail-section-title">
                  <span>Shotlist association</span>
                  <b>{selectedShot?.id || "UNASSIGNED"}</b>
                </div>
                {selectedShot ? (
                  <>
                    <p>{selectedShot.description}</p>
                    <dl>
                      <div>
                        <dt>Framing</dt>
                        <dd>{selectedShot.framing || "—"}</dd>
                      </div>
                      <div>
                        <dt>Location</dt>
                        <dd>{selectedShot.location || "—"}</dd>
                      </div>
                      <div>
                        <dt>Planned file</dt>
                        <dd>{selectedShot.fileName || "—"}</dd>
                      </div>
                      <div>
                        <dt>Camera</dt>
                        <dd>
                          {selected?.c4dVerification?.cameraName ||
                            selectedShot.camera ||
                            "Pending source extraction"}
                        </dd>
                      </div>
                    </dl>
                  </>
                ) : (
                  <p>No planned-shot record is attached to this editorial interval.</p>
                )}
              </section>

              <section className="pipeline-camera-proof pipeline-flow-section">
                <div className="detail-section-title">
                  <span>
                    {selectedCameraMatchConfirmed
                      ? "Camera proof"
                      : selectedCameraProofImage
                        ? "Camera test"
                        : "Camera proof"}
                  </span>
                  <b>{selectedCameraProofBadge}</b>
                </div>
                {selectedCameraProofImage ? (
                  <div className="pipeline-proof-row">
                    <EvidenceImageButton
                      src={selectedCameraProofImage}
                      alt={`Camera ${
                        selectedCameraMatchConfirmed ? "proof" : "test"
                      } for ${selected.id}`}
                      onOpen={setLightboxImage}
                    />
                    <div>
                      <strong>
                        {selectedCameraProof?.recoveryProof
                          ? selectedCameraProof.label
                          : selectedCameraNode?.label ||
                            selectedCameraProof?.label ||
                            selected.c4dVerification?.cameraName ||
                            "C4D camera proof"}
                      </strong>
                      <span>
                        {selectedCameraProof?.confirmationMethod ||
                          "render-to-cut comparison"}
                      </span>
                      {!selectedCameraProofQualified && (
                        <em>
                          {selectedC4DEvidence?.tone === "unconfirmed"
                            ? "Recovery/candidate test only; the C4D source file is not confirmed."
                            : selectedCameraMatchConfirmed &&
                                selectedCameraProofIsGrey
                              ? "Camera match confirmed; full-color materials and render-critical dependencies are not yet verified."
                            : selectedC4DEvidence?.reason === "camera_mismatch"
                              ? "Rendered test retained as negative evidence; the camera does not match."
                              : "Rendered test retained as process evidence; it does not qualify as a confirmed camera match."}
                        </em>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="pipeline-empty-row">
                    <strong>{selectedCameraNode?.label || "No camera proof"}</strong>
                    <span>No visual comparison is attached to this shot.</span>
                  </div>
                )}
              </section>

              {!!selectedProcessImages.length && (
                <section className="pipeline-process-images pipeline-flow-section">
                  <div className="detail-section-title">
                    <span>Process images</span>
                    <b>
                      {selectedProcessImages.length} RETAINED
                      {selectedFreshFullColorRenderCount
                        ? ` · ${selectedFreshFullColorRenderCount} FULL COLOR`
                        : ""}
                    </b>
                  </div>
                  <div className="pipeline-process-image-grid">
                    {selectedProcessImages.map((item) => (
                      <figure key={item.image} className="pipeline-process-image">
                        <EvidenceImageButton
                          src={item.image}
                          alt={`${item.label} · ${item.kind} for ${selected.id}`}
                          onOpen={setLightboxImage}
                        />
                        <figcaption>
                          <span>
                            {item.kind}
                            {item.composite ? " · comparison" : ""}
                          </span>
                          <strong>{item.label}</strong>
                          <small>{item.evidence}</small>
                          <p>{item.detail}</p>
                        </figcaption>
                      </figure>
                    ))}
                  </div>
                </section>
              )}

              <section className="pipeline-canonical-source pipeline-flow-section">
                <div className="detail-section-title">
                  <span>Canonical source</span>
                  <b>
                    {selected.sourceSegments.length
                      ? `${selected.sourceSegments.length} LINKED`
                      : "NO ACTIVE SOURCE"}
                  </b>
                </div>
                {selected.sourceSegments.length ? (
                  <div className="pipeline-source-summary">
                    {selected.sourceSegments.map((segment) => {
                      const sourcePathParts = splitPathForDisplay(
                        segment.sourcePath,
                      );
                      return (
                        <article key={segment.id}>
                          <div>
                            <strong>{segment.id}</strong>
                            <span>
                              V{segment.sourceTrack} ·{" "}
                              {cleanConform
                                ? "canonical"
                                : segment.role || "linked"}
                            </span>
                          </div>
                          <button
                            className="path-button canonical-source-path"
                            onClick={() =>
                              void revealAndCopyPath(segment.sourcePath)
                            }
                            title={`${segment.sourcePath} · Reveal in Finder and copy full path`}
                            aria-label={`Reveal ${fileName(segment.sourcePath)} in Finder and copy its full path`}
                          >
                            <span>{sourcePathParts.leading}</span>
                            <b>{sourcePathParts.ending}</b>
                          </button>
                          <small>
                            Source {segment.sourceIn?.toFixed(3) ?? "—"} →
                            {segment.sourceOut?.toFixed(3) ?? "—"}s · frames{" "}
                            {segment.sourceStartFrame ?? "—"} →
                            {segment.sourceEndFrame ?? "—"}
                          </small>
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <div className="pipeline-empty-row">
                    <strong>Editorial gap</strong>
                    <span>No canonical source should be attached.</span>
                  </div>
                )}
              </section>
		              {selected.manualConform && (
                <details
                  className={`manual-conform-panel status-${selected.manualConform.status}`}
                >
                  <summary className="manual-conform-heading">
                    <div>
                      <span>Saved Premiere trims</span>
                      <strong>
                        {conformStatusLabel(
                          selected.manualConform.status,
                          cleanConform,
                        )}
                      </strong>
                    </div>
                    <b>{cleanConform ? "CANONICAL AUTHORITY" : "MANUAL AUTHORITY"}</b>
                  </summary>
                  <div className="manual-trim-grid">
                    <div>
                      <span>{selectedTrackLabel} timeline frames</span>
                      <strong>
                        {selected.manualConform.startFrame} →{" "}
                        {selected.manualConform.endFrame}
                      </strong>
                      <small>
                        {selected.start.toFixed(6)}–{selected.end.toFixed(6)}s
                      </small>
                    </div>
                    <div>
                      <span>{selectedTrackLabel} source In / Out</span>
                      <strong>
                        {selected.manualConform.sourceIn?.toFixed(6) ?? "—"} →{" "}
                        {selected.manualConform.sourceOut?.toFixed(6) ?? "—"}
                      </strong>
                      <small>
                        offsets {selected.manualConform.sourceInFrameOffset ?? "—"} →{" "}
                        {selected.manualConform.sourceOutFrameOffset ?? "—"}
                      </small>
                    </div>
                    <div>
                      <span>
                        {cleanConform ? "Canonical source layer" : "Saved aligned layers"}
                      </span>
                      <strong>
                        {selected.sourceSegments.length
                          ? selected.sourceSegments
                              .map((segment) => `V${segment.sourceTrack}`)
                              .filter((value, index, values) => values.indexOf(value) === index)
                              .join(" + ")
                          : "none"}
                      </strong>
                      <small>{selected.manualConform.sources.join(", ") || "true blank / unresolved"}</small>
                    </div>
                  </div>
                  {!selected.isGap && (
                    <div className="manual-coverage">
                      <div>
                        <span>
                          Exact coverage{" "}
                          {Math.round((selected.manualConform.exactCoverage || 0) * 1000) /
                            10}
                          %
                        </span>
                        <i>
                          <b
                            style={{
                              width: `${Math.min(
                                100,
                                (selected.manualConform.exactCoverage || 0) * 100,
                              )}%`,
                            }}
                          />
                        </i>
                      </div>
                      <div>
                        <span>
                          Any tracked source{" "}
                          {Math.round((selected.manualConform.coverage || 0) * 1000) / 10}%
                        </span>
                        <i>
                          <b
                            style={{
                              width: `${Math.min(
                                100,
                                (selected.manualConform.coverage || 0) * 100,
                              )}%`,
                            }}
                          />
                        </i>
                      </div>
                    </div>
                  )}
                  <p>
                    {selected.manualConform.frameAlignedConform
                      ? `This source placement is present in the independently verified frame-aligned Premiere project. ${selected.manualConform.frameAlignedConform.adapterFrames} one-frame adapter links preserve the exact final-to-render cadence.`
                      : selected.manualConform.visualAlignment
                      ? `This source placement was corrected by exact reference-frame comparison. ${selected.manualConform.visualAlignment.detail}`
                      : "These timeline and source In/Out values are copied from the saved clip instances. The atlas does not move, extend, or re-time them."}
                  </p>
                </details>
              )}
              {selected.comparison && (
                <section className="frame-comparison">
                  <div className="detail-section-title">
                    <span>Final ↔ source frame</span>
                    <b>{selected.comparison.score.toFixed(3)}</b>
                  </div>
                  <EvidenceImageButton
                    src={selected.comparison.pairImage}
                    alt={`Final and AE source comparison for ${selected.id}`}
                    onOpen={setLightboxImage}
                  />
                  <EvidenceBadge value={selected.comparison.evidence} />
                </section>
              )}

              {!!selected.exportScreenshots.length && (
                <details className="lineage-export-section pipeline-collapsible">
                  <summary className="detail-section-title">
                    <span>Lineage export frames</span>
                    <b>{selected.exportScreenshots.length} archived</b>
                  </summary>
                  <div className="lineage-export-list">
                    {selected.exportScreenshots.map((item) => (
                      <article key={item.id}>
                        <EvidenceImageButton
                          className="lineage-export-image"
                          src={item.image}
                          alt={`${item.label} export frame for ${selected.id}`}
                          onOpen={setLightboxImage}
                        >
                          <span>{item.sourceTime.toFixed(3)}s</span>
                        </EvidenceImageButton>
                        <div className="lineage-export-body">
                          <div className="lineage-export-heading">
                            <strong>{item.label}</strong>
                            <EvidenceBadge value={item.evidence} />
                          </div>
                          <p>{item.detail}</p>
                          <div className="export-producer-list">
                            {item.producers.map((producer, index) => (
                              <div
                                className="export-producer"
                                key={`${producer.kind}-${producer.sequence}-${index}`}
                              >
                                <span>{nodeLabels[producer.kind] || producer.kind}</span>
                                <strong>{producer.sequence || producer.label}</strong>
                                <small>{producer.label}</small>
                              </div>
                            ))}
                          </div>
                          <button
                            className="path-button"
                            onClick={() => navigator.clipboard.writeText(item.exportPath)}
                            title="Copy full export path"
                          >
                            {shortPath(item.exportPath)}
                          </button>
                          <div className="node-actions">
                            <button onClick={() => void reveal(item.exportPath)}>
                              Reveal export
                            </button>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </details>
              )}

              {selected.c4dLinkStatus && !selected.isGap && (
                <section
                  className={`c4d-linkage-panel health-${
                    selected.c4dLinkStatus.status
                  } verification-${
                    selected.c4dVerification?.status || "unreviewed"
                  }`}
                >
                  <div className="c4d-linkage-heading">
                    <div>
                      <span>Strict C4D verification</span>
                      <strong>
                        {selected.c4dVerification?.label ||
                          selected.c4dLinkStatus.label}
                      </strong>
                    </div>
                    <i aria-hidden="true" />
                  </div>
                  <p className="c4d-linkage-detail">
                    {selected.c4dVerification?.detail ||
                      selected.c4dLinkStatus.detail}
                  </p>
                  <div className="c4d-linkage-source">
                    <span>
                      {selected.c4dLinkStatus.projectName || "Mapped C4D source"}
                    </span>
                    <b>Take · {selected.c4dLinkStatus.take || "Main"}</b>
                  </div>
                  {selected.c4dVerification && (
                    <div className="c4d-visual-grid">
                      {Object.entries(selected.c4dVerification.elements).map(
                        ([key, status]) => (
                          <article
                            className={`visual-${status}`}
                            key={key}
                            title={`${key}: ${status.replaceAll("_", " ")}`}
                            aria-label={`${key}: ${status.replaceAll("_", " ")}`}
                          >
                            <div>
                              <i aria-hidden="true" />
                              <span>{compactC4DElementLabel(key)}</span>
                            </div>
                            <strong>{status.replaceAll("_", " ")}</strong>
                          </article>
                        ),
                      )}
                    </div>
                  )}
                  {selected.c4dSceneState && (
                    <div className="c4d-scene-state">
                      <div>
                        <span>Saved scene state</span>
                        <strong>
                          {selected.c4dSceneState.diagnosis.replaceAll("_", " ")}
                        </strong>
                      </div>
                      <div className="c4d-scene-state-counts">
                        <span>
                          <b>{selected.c4dSceneState.activeCharacterObjectCount}</b>{" "}
                          character
                        </span>
                        <span>
                          <b>{selected.c4dSceneState.activeHairObjectCount}</b> hair
                        </span>
                        <span>
                          <b>{selected.c4dSceneState.activeWardrobeObjectCount}</b>{" "}
                          wardrobe
                        </span>
                        <span>
                          <b>{selected.c4dSceneState.activeProxyCount}</b> proxy
                        </span>
                      </div>
                      <small className="c4d-wardrobe-expectation">
                        Expected wardrobe ·{" "}
                        <b>
                          {selected.c4dSceneState.expectedWardrobeFamily.replaceAll(
                            "_",
                            " ",
                          )}
                        </b>
                      </small>
                    </div>
                  )}
                  <div className="pipeline-c4d-dependency">
                    <div>
                      <span>
                        {selectedExactCutAudit
                          ? "Exact cut dependency audit"
                          : selectedProofLinkage
                          ? "Proof-revision linkage audit"
                          : "Dependency audit"}
                      </span>
                      <strong>
                        {selectedExactCutAudit
                          ? selectedExactCutAudit.strictDependencyRenderSafe
                            ? "Render-critical dependencies linked"
                            : `${selectedExactCutAudit.postRelinkUnresolvedFiles} render-critical file${
                                selectedExactCutAudit.postRelinkUnresolvedFiles === 1
                                  ? ""
                                  : "s"
                              } unresolved`
                          : selectedProofLinkage
                          ? selectedProofLinkage.renderCriticalMissingFiles
                            ? `${selectedProofLinkage.renderCriticalMissingFiles} render-critical file${
                                selectedProofLinkage.renderCriticalMissingFiles === 1
                                  ? ""
                                  : "s"
                              } unresolved`
                            : "Render-critical dependencies linked"
                          : selected.c4dLinkStatus.dependencyLabel ||
                            selected.c4dLinkStatus.label}
                      </strong>
                    </div>
                    <small>
                      {selectedExactCutAudit
                        ? `${selectedExactCutAudit.mappedPaths} exact local relinks verified · ${selectedExactCutAudit.postRelinkUnresolvedReferences} active missing references`
                        : selectedProofLinkage
                        ? `${selectedProofLinkage.linkedReferences} linked · ${selectedProofLinkage.missingReferences} missing · ${selectedProofLinkage.renderCriticalMissingReferences} active missing references`
                        : `${selected.c4dLinkStatus.linkedFiles || 0} linked · ${
                            selected.c4dLinkStatus.missingFiles || 0
                          } missing · ${
                            selected.c4dLinkStatus.renderCriticalMissingFiles || 0
                          } render-critical`}
                    </small>
                  </div>
                  <details className="c4d-deep-audit">
                    <summary>
                      <span>Full C4D evidence</span>
                      <b>
                        Cameras · recovery · proxies · dependencies
                      </b>
                    </summary>
                  {selected.c4dCameraCandidateAudit && (
                    <section className="c4d-camera-candidate-audit">
                      <div className="c4d-camera-candidate-heading">
                        <div>
                          <span>Retained camera exhaust</span>
                          <strong>
                            {selected.c4dCameraCandidateAudit.candidates.length}{" "}
                            cameras visually tested
                          </strong>
                        </div>
                        <b>
                          {selected.c4dCameraCandidateAudit.status.replaceAll(
                            "_",
                            " ",
                          )}
                        </b>
                      </div>
                      <p>{selected.c4dCameraCandidateAudit.summary}</p>
                      <small>
                        Expected · {selected.c4dCameraCandidateAudit.expectedView}
                      </small>
                      <div className="c4d-camera-candidate-grid">
                        <article className="camera-candidate-canonical">
                          <EvidenceImageButton
                            src={
                              selected.c4dCameraCandidateAudit
                                .canonicalThumbnail
                            }
                            alt={`${selected.id} canonical thumbnail`}
                            onOpen={setLightboxImage}
                          />
                          <div>
                            <strong>Canonical</strong>
                            <span>
                              source frame{" "}
                              {selected.c4dCameraCandidateAudit.sourceFrame}
                            </span>
                          </div>
                        </article>
                        {selected.c4dCameraCandidateAudit.candidates.map(
                          (candidate) => (
                            <article
                              key={`${candidate.projectPath}-${candidate.cameraName}`}
                              title={candidate.difference}
                            >
                              <EvidenceImageButton
                                src={candidate.image}
                                alt={`${selected.id} ${candidate.cameraName} ruled-out proof`}
                                onOpen={setLightboxImage}
                              />
                              <div>
                                <strong>{candidate.cameraName}</strong>
                                <span>ruled out · f{candidate.frame}</span>
                              </div>
                              <p>{candidate.difference}</p>
                            </article>
                          ),
                        )}
                      </div>
                      <div className="c4d-camera-candidate-next">
                        <span>Resolution path</span>
                        <p>{selected.c4dCameraCandidateAudit.nextResolution}</p>
                        <button
                          className="path-button"
                          onClick={() =>
                            void reveal(
                              selected.c4dCameraCandidateAudit!.sourceProject,
                            )
                          }
                        >
                          Reveal output-owner project
                        </button>
                      </div>
                    </section>
                  )}
                  {selected.c4dStructuralRecovery && (
                    <section className="c4d-structural-recovery">
                      <div className="c4d-structural-recovery-heading">
                        <div>
                          <span>Dated recovery copy</span>
                          <strong>
                            {selected.c4dStructuralRecovery.status.replaceAll(
                              "_",
                              " ",
                            )}
                          </strong>
                        </div>
                        <b>ORIGINAL UNTOUCHED</b>
                      </div>
                      <div className="c4d-structural-proof-grid">
                        {selected.c4dStructuralRecovery.proofs
                          .filter(
                            (proof) =>
                              proof.image &&
                              !proof.status
                                .toLocaleLowerCase()
                                .includes("rejected"),
                          )
                          .map((proof) => (
                            <article
                              key={`${proof.kind}-${proof.image}`}
                            >
                              <EvidenceImageButton
                                src={proof.image}
                                alt={`${proof.kind} recovery proof for ${selected.id}`}
                                onOpen={setLightboxImage}
                              />
                              <div>
                                <strong>
                                  {proof.kind.replaceAll("_", " ")}
                                </strong>
                                <span>{proof.status}</span>
                              </div>
                              <p>{proof.visualResult}</p>
                            </article>
                          ))}
                      </div>
                      <div className="c4d-structural-facts">
                        <span>
                          Camera
                          <b>{selected.c4dStructuralRecovery.cameraName}</b>
                        </span>
                        <span>
                          Hair
                          <b>
                            {selected.c4dStructuralRecovery.hairGeometry
                              ?.evaluatedPolygonCount
                              ? `${selected.c4dStructuralRecovery.hairGeometry.evaluatedPolygonCount} evaluated polys`
                              : selected.c4dStructuralRecovery.elementReview
                                  .hair?.replaceAll("_", " ") || "not recovered"}
                          </b>
                        </span>
                        <span>
                          Wardrobe
                          <b>
                            {selected.c4dStructuralRecovery.wardrobeGeometry
                              ?.cachePolygonCount
                              ? `${selected.c4dStructuralRecovery.wardrobeGeometry.cachePolygonCount} cache polys`
                              : selected.c4dStructuralRecovery.wardrobeGeometry
                                  ?.status.replaceAll("_", " ") ||
                                "not recovered"}
                          </b>
                        </span>
                        {!!selected.c4dStructuralRecovery.exactRelinks
                          ?.length && (
                          <span>
                            Relinks
                            <b>
                              {
                                selected.c4dStructuralRecovery.exactRelinks
                                  .length
                              }{" "}
                              exact verified
                            </b>
                          </span>
                        )}
                        {selected.c4dStructuralRecovery.linkageAudit && (
                          <span>
                            Link audit
                            <b>
                              {selected.c4dStructuralRecovery.linkageAudit
                                .recoveryLinkedReferences ?? "?"}{" "}
                              linked ·{" "}
                              {selected.c4dStructuralRecovery.linkageAudit
                                .recoveryUniqueMissingFiles ?? "?"}{" "}
                              files left
                            </b>
                          </span>
                        )}
                      </div>
                      {selected.c4dStructuralRecovery.linkageAudit
                        ?.currentC4dLoadWarning && (
                        <p className="c4d-structural-link-warning">
                          {
                            selected.c4dStructuralRecovery.linkageAudit
                              .currentC4dLoadWarning
                          }
                        </p>
                      )}
                      <div className="c4d-structural-actions">
                        <button
                          className="path-button"
                          onClick={() =>
                            void reveal(
                              selected.c4dStructuralRecovery!.recoveryProject,
                            )
                          }
                        >
                          Reveal recovery copy
                        </button>
                        {selected.c4dStructuralRecovery.hairSourceProject && (
                          <button
                            className="path-button"
                            onClick={() =>
                              void reveal(
                                selected.c4dStructuralRecovery!
                                  .hairSourceProject!,
                              )
                            }
                          >
                            Reveal hair source
                          </button>
                        )}
                      </div>
                      <ol>
                        {selected.c4dStructuralRecovery.remainingBlockers.map(
                          (blocker) => (
                            <li key={blocker}>{blocker}</li>
                          ),
                        )}
                      </ol>
                    </section>
                  )}
                  {selected.c4dProxyAudit?.required && (
                    <section
                      className={`c4d-proxy-audit proxy-${selected.c4dProxyAudit.status}`}
                    >
                      <div className="c4d-proxy-heading">
                        <div>
                          <span>Redshift proxy reproducibility</span>
                          <strong>{selected.c4dProxyAudit.label}</strong>
                        </div>
                        <i aria-hidden="true" />
                      </div>
                      <p>{selected.c4dProxyAudit.detail}</p>
                      <div className="c4d-proxy-records">
                        {selected.c4dProxyAudit.records.map((record, recordIndex) => {
                          const audit = record.proxyAuditSummary;
                          const dependencyStatuses =
                            audit?.dependencyByStatus || {};
                          const unresolvedDependencies = Object.entries(
                            dependencyStatuses,
                          )
                            .filter(([status]) => status === "unresolved")
                            .reduce((total, [, count]) => total + count, 0);
                          const componentCategories = Array.from(
                            new Set(
                              record.sourceComponents.map(
                                (component) => component.category,
                              ),
                            ),
                          );
                          return (
                            <article
                              key={`${record.proxyObjectPath || "proxy"}-${recordIndex}`}
                            >
                              <div className="c4d-proxy-record-title">
                                <div>
                                  <span>Active proxy object</span>
                                  <strong>
                                    {record.proxyObjectName || "Unnamed RS proxy"}
                                  </strong>
                                </div>
                                <em>
                                  {record.editableCharacterDiagnosis
                                    ?.replaceAll("_", " ") || "scene state unknown"}
                                </em>
                              </div>
                              {audit && (
                                <>
                                  <div className="c4d-proxy-elements">
                                    {[
                                      ["BODY", audit.bodyMeshPresent],
                                      ["FACE", audit.faceMeshPresent],
                                      ["HAIR", audit.hairPresent],
                                      ["WRD", audit.wardrobePresent],
                                      ["CAM", audit.cameraPresent],
                                    ].map(([label, present]) => (
                                      <span
                                        className={present ? "present" : "missing"}
                                        key={String(label)}
                                      >
                                        <i aria-hidden="true" />
                                        {String(label)}
                                      </span>
                                    ))}
                                  </div>
                                  <small className="c4d-proxy-dependency-counts">
                                    {audit.dependencyCount || 0} embedded dependency
                                    records · {unresolvedDependencies} unresolved
                                  </small>
                                </>
                              )}
                              {record.rendererCompatibility && (
                                <div className="c4d-proxy-compatibility">
                                  <span>
                                    Installed
                                    <b>
                                      {record.rendererCompatibility.installed ||
                                        "unknown"}
                                    </b>
                                  </span>
                                  <span>
                                    Required
                                    <b>
                                      {record.rendererCompatibility.requiredMinimum ||
                                        record.producerVersion ||
                                        "unknown"}
                                    </b>
                                  </span>
                                </div>
                              )}
                              {!!componentCategories.length && (
                                <div className="c4d-proxy-source-status">
                                  <span>Regeneration sources</span>
                                  <strong>
                                    {record.sourceComponentsComplete
                                      ? "Complete"
                                      : "Incomplete"}
                                  </strong>
                                  <div>
                                    {componentCategories.map((category) => (
                                      <i key={category}>{category}</i>
                                    ))}
                                  </div>
                                </div>
                              )}
                              <div className="c4d-proxy-actions">
                                {record.proxyFile && (
                                  <button
                                    className="path-button"
                                    onClick={() => void reveal(record.proxyFile)}
                                    title="Reveal exact Redshift proxy"
                                  >
                                    Reveal proxy
                                  </button>
                                )}
                                {record.sourceComponents[0]?.path && (
                                  <button
                                    className="path-button"
                                    onClick={() =>
                                      void reveal(record.sourceComponents[0].path)
                                    }
                                    title="Reveal a recovered regeneration source"
                                  >
                                    Reveal source set
                                  </button>
                                )}
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    </section>
                  )}
                  {!!selectedRecoverySteps.length && (
                    <div className="c4d-remediation-list">
                      <span>Agent-ready recovery checklist</span>
                      <ol>
                        {selectedRecoverySteps.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ol>
                    </div>
                  )}
                  <div className="c4d-dependency-verdict">
                    <span>
                      {selectedProofLinkage
                        ? "Current local project dependency audit"
                        : "Dependency audit"}
                    </span>
                    <strong>
                      {selected.c4dLinkStatus.dependencyLabel ||
                        selected.c4dLinkStatus.label}
                    </strong>
                  </div>
                  {!!selected.c4dLinkStatus.renderCriticalMissingFiles && (
                    <div className="c4d-recovery-verdict">
                      <span>
                        <b>
                          {selected.c4dLinkStatus.renderCriticalExactRecoveries ||
                            0}
                        </b>{" "}
                        exact Dropbox recoveries
                      </span>
                      <span>
                        <b>
                          {selected.c4dLinkStatus
                            .renderCriticalCandidateRecoveries || 0}
                        </b>{" "}
                        candidates to validate
                      </span>
                      <span>
                        <b>
                          {selected.c4dLinkStatus
                            .renderCriticalUnresolvedFiles || 0}
                        </b>{" "}
                        genuinely unresolved
                      </span>
                    </div>
                  )}
                  <div className="c4d-component-grid">
                    {selected.c4dLinkStatus.components.map((component) => (
                      <article
                        className={`component-${component.status}`}
                        key={component.key}
                        title={component.summary}
                      >
                        <div>
                          <i aria-hidden="true" />
                          <span>{component.label}</span>
                        </div>
                        <strong>{component.summary}</strong>
                        <small>
                          {component.renderCriticalMissingFiles
                            ? `${component.renderCriticalMissingFiles} active file${
                                component.renderCriticalMissingFiles === 1 ? "" : "s"
                              } missing`
                            : component.missingFiles
                              ? `${component.missingFiles} inactive file${
                                  component.missingFiles === 1 ? "" : "s"
                                } missing`
                              : component.linkedFiles
                                ? `${component.linkedFiles} external file${
                                    component.linkedFiles === 1 ? "" : "s"
                                  } resolved`
                                : component.status === "embedded"
                                  ? "stored in project"
                                  : "no external dependency"}
                        </small>
                      </article>
                    ))}
                  </div>
                  <div className="c4d-linkage-counts">
                    <span>
                      <b>{selected.c4dLinkStatus.objectCount || 0}</b> objects
                    </span>
                    <span>
                      <b>{selected.c4dLinkStatus.linkedFiles || 0}</b> linked files
                    </span>
                    <span>
                      <b>{selected.c4dLinkStatus.missingFiles || 0}</b> missing files
                    </span>
                    <span>
                      <b>
                        {selected.c4dLinkStatus.renderCriticalMissingFiles || 0}
                      </b>{" "}
                      render-critical
                    </span>
                  </div>
                  {!!selected.c4dLinkStatus.missingExamples.length && (
                    <details className="c4d-missing-details">
                      <summary>
                        Inspect missing dependency evidence
                        <b>
                          {selected.c4dLinkStatus.missingFiles} unique files ·{" "}
                          {selected.c4dLinkStatus.missingReferences} scene references
                        </b>
                      </summary>
                      <div className="c4d-missing-list">
                        {selected.c4dLinkStatus.missingExamples.map((item, index) => (
                          <article key={`${item.filename}-${index}`}>
                            <div>
                              <span>{item.category}</span>
                              {item.characterRelated && <em>character</em>}
                              <b className={item.renderCritical ? "critical" : "inactive"}>
                                {item.renderCritical ? "render-active" : "inactive"}
                              </b>
                            </div>
                            <strong>{shortPath(item.filename)}</strong>
                            <small>{item.owner || "owner unavailable"}</small>
                            {!!item.recovery?.candidates.length && (
                              <div className="c4d-recovery-candidate">
                                <span>
                                  {item.recovery.status === "recovered_exact_path"
                                    ? "Exact Dropbox path recovered"
                                    : "Candidate dependency"}
                                </span>
                                <strong>
                                  {shortPath(item.recovery.candidates[0].path)}
                                </strong>
                                <button
                                  className="path-button"
                                  onClick={() =>
                                    void reveal(
                                      item.recovery?.candidates[0].path,
                                    )
                                  }
                                  title="Reveal recovered dependency and copy its containing folder"
                                >
                                  Reveal recovery
                                </button>
                              </div>
                            )}
                            {!!item.recovery?.semanticCandidates?.length && (
                              <div className="c4d-recovery-candidate semantic">
                                <span>
                                  Semantic source candidate · validation required
                                </span>
                                <strong>
                                  {shortPath(
                                    item.recovery.semanticCandidates[0].path,
                                  )}
                                </strong>
                                <small>
                                  {item.recovery.semanticValidationRequired?.join(
                                    " · ",
                                  )}
                                </small>
                                <button
                                  className="path-button"
                                  onClick={() =>
                                    void reveal(
                                      item.recovery?.semanticCandidates?.[0].path,
                                    )
                                  }
                                  title="Reveal unverified semantic source candidate"
                                >
                                  Reveal candidate
                                </button>
                              </div>
                            )}
                            <button
                              className="path-button"
                              onClick={() => navigator.clipboard.writeText(item.filename)}
                              title="Copy unresolved asset path"
                            >
                              Copy unresolved path
                            </button>
                          </article>
                        ))}
                      </div>
                    </details>
                  )}
                  {selected.c4dLinkStatus.projectPath && (
                    <div className="c4d-linkage-actions">
                      <button
                        onClick={() =>
                          void reveal(selected.c4dLinkStatus?.projectPath)
                        }
                      >
                        Reveal C4D project
                      </button>
                      <button
                        onClick={() =>
                          navigator.clipboard.writeText(
                            selected.c4dLinkStatus?.projectPath || "",
                          )
                        }
                      >
                        Copy project path
                      </button>
                    </div>
                  )}
                  <p className="c4d-historical-note">
                    {selected.c4dLinkStatus.historicalRenderNote}
                  </p>
                  </details>
                </section>
              )}

              {!!selected.sourceSegments.length && (
                <details className="source-conform-section pipeline-collapsible">
                  <summary className="detail-section-title">
                    <span>
                      {data.revisedConform?.active
                        ? cleanConform
                          ? "Canonical V1/V2 source inventory"
                          : "Manual source inventory"
                        : "Terminal source conform"}
                    </span>
                    <b>{selected.sourceSegments.length} overlapping</b>
                  </summary>
                  <div className="source-conform-list">
                    {selected.sourceSegments.map((segment) => (
                      <article key={segment.id}>
                        <div>
                          <strong>{segment.id}</strong>
                          {segment.role && (
                            <span className={`source-role-badge role-${segment.role}`}>
                              V{segment.sourceTrack} ·{" "}
                              {cleanConform
                                ? "canonical"
                                : segment.role === "exact_match"
                                ? "exact"
                                : segment.role === "older_than_cut"
                                  ? "older"
                                  : "newer"}
                            </span>
                          )}
                          {segment.isNewRecovery && (
                            <span className="source-recovery-label">
                              Premiere · {segment.premiereLabel || "Yellow"}
                            </span>
                          )}
                          <EvidenceBadge
                            value={segment.verification?.evidence || segment.evidence}
                          />
                        </div>
                        <p>{segment.sourceEdit}</p>
                        {segment.sourceMediaHealth?.status === "incomplete" && (
                          <small className="source-media-warning">
                            Selected render incomplete on disk ·{" "}
                            {segment.sourceMediaHealth.missingFrames}/
                            {segment.sourceMediaHealth.expectedFrames} frames missing ·{" "}
                            {segment.sourceMediaHealth.missingFirstFrame}→
                            {segment.sourceMediaHealth.missingLastFrame}
                          </small>
                        )}
                        <button
                          className="path-button"
                          onClick={() => navigator.clipboard.writeText(segment.sourcePath)}
                          title="Copy full source path"
                        >
                          {shortPath(segment.sourcePath)}
                        </button>
                        <small>
                          final {segment.finalStart.toFixed(6)}–{segment.finalEnd.toFixed(6)}s
                          {segment.finalStartFrame !== undefined
                            ? ` · timeline frames ${segment.finalStartFrame}→${segment.finalEndFrame}`
                            : ""}
                        </small>
                        <small>
                          source In/Out {segment.sourceIn?.toFixed(6) ?? "—"}→
                          {segment.sourceOut?.toFixed(6) ?? "—"}s · selected frames{" "}
                          {segment.sourceStartFrame ?? "—"}→{segment.sourceEndFrame ?? "—"}
                          {segment.playBackwards ? " · reverse" : ""}
                        </small>
                        {segment.frameAlignedConform && (
                          <small>
                            frame-aligned Premiere ·{" "}
                            {segment.frameAlignedConform.adapterFrames} adapter frames ·
                            render cadence{" "}
                            {segment.frameAlignedConform.chosenFirstFrame}→
                            {segment.frameAlignedConform.chosenLastFrame} · median
                            structural match{" "}
                            {segment.frameAlignedConform.similarity.median.toFixed(3)}
                          </small>
                        )}
                        <div className="node-actions">
                          <button onClick={() => void reveal(segment.sourceFirstFramePath)}>
                            Reveal frame
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                </details>
              )}

              <details className="lineage-section pipeline-collapsible">
                <summary className="detail-section-title">
                  <span>Backward lineage</span>
                  <b>{selected.lineage.length} nodes</b>
                </summary>
                <div className="lineage">
                  {selected.lineage.map((node, index) => (
                    <article className="lineage-node" key={`${node.kind}-${index}`}>
                      <div className={`node-icon node-${node.kind}`}>
                        <span>{index + 1}</span>
                      </div>
                      <div className="node-body">
                        <div className="node-kicker">
                          <span>{nodeLabels[node.kind] || node.kind}</span>
                          <EvidenceBadge value={node.evidence} />
                        </div>
                        {!!node.tags?.length && (
                          <div className="lineage-tags">
                            {node.tags.map((tag) => (
                              <span
                                className={`lineage-tag tag-${tag.type}`}
                                key={tag.type}
                                title={`${tag.detail} · ${evidenceLabels[tag.evidence] || tag.evidence}`}
                              >
                                {tag.label}
                              </span>
                            ))}
                          </div>
                        )}
                        {node.assetHealth && (
                          <div
                            className={`lineage-asset-health health-${node.assetHealth.status}`}
                            title={`Take ${node.assetHealth.take}`}
                          >
                            <i aria-hidden="true" />
                            {node.assetHealth.label}
                          </div>
                        )}
                        <strong>{node.label}</strong>
                        <p>{node.detail}</p>
                        {node.comparisonImage &&
                          !(
                            node.kind === "camera_proof" &&
                            isCompositeEvidenceImage(node.comparisonImage)
                          ) && (
                          <figure className="camera-audit-proof">
                            <EvidenceImageButton
                              src={node.comparisonImage}
                              alt={`${selected.id} ${
                                node.kind === "visual_match"
                                  ? "alternate render"
                                  : node.kind === "camera_proof"
                                    ? "camera test render"
                                    : "render-camera"
                              } comparison`}
                              onOpen={setLightboxImage}
                            />
                            <figcaption>
                              {node.kind === "visual_match"
                                ? "Alternate search"
                                : node.kind === "camera_proof"
                                  ? "Camera proof"
                                  : "Camera audit"}{" "}
                              · {node.confirmationMethod || "frame comparison"}
                            </figcaption>
                          </figure>
                        )}
                        {node.path && (
                          <button
                            className="path-button"
                            onClick={() => navigator.clipboard.writeText(node.path || "")}
                            title="Copy full path"
                          >
                            {shortPath(node.path)}
                          </button>
                        )}
                        {node.path && (
                          <div className="node-actions">
                            <button onClick={() => void reveal(node.path)}>Reveal</button>
                            <button onClick={() => void openNode(node)}>Open source</button>
                          </div>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              </details>

              <section className="verification-note">
                <span aria-hidden="true">!</span>
                <div>
                  <strong>
                    {selected.manualConform
                      ? cleanConform
                        ? selected.manualConform.visualAlignment
                          ? "Exact frame alignment confirmed"
                          : "Canonical Premiere trim preserved"
                        : "Manual trim preserved"
                      : selected.verification === "source_edit_confirmed"
                      ? "Source edit located"
                      : "Next evidence gate"}
                  </strong>
                  <p>
                    {selected.manualConform
                      ? selected.isGap
                        ? cleanConform
                          ? "This interval is a true V1/V2 picture gap in the canonical Premiere sequence. No source render or camera is attached."
                          : "This interval is an intentional V1 blank. No source render or camera should be attached."
                        : cleanConform
                          ? selected.manualConform.visualAlignment
                            ? `The source render is preserved, but its visible boundary follows direct reference-frame matching: ${selected.manualConform.visualAlignment.detail}`
                            : "The saved V1/V2 timeline and source In/Out ticks are authoritative. The source-render clip instance and its exact Premiere placement are preserved."
                          : `The saved V1 and source-layer In/Out values are locked. ${
                              selected.manualConform.status === "exact_match"
                                ? "This interval is fully covered by the user-confirmed V6/Iris source."
                                : "Replacement searches may add evidence, but cannot change these trims automatically."
                            }`
                      : selected.verification === "source_edit_confirmed"
                      ? `${selected.boundaryDetail}. Candidate badges identify the remaining render-output or image-match checks.`
                      : "Confirm this machine boundary from the source edit, then compare the final frame to its render and test the active C4D render camera."}
                  </p>
                </div>
              </section>
            </>
          ) : (
            <EmptyState message="Choose a cut to inspect its lineage." />
          )}
        </RightInspectorPanel>
        </div>
      )}

      {lightboxImage && (
        <div
          className="inspector-image-lightbox"
          data-inspector-lightbox
          role="dialog"
          aria-modal="true"
          aria-label={lightboxImage.alt}
          onMouseDown={(event) => {
            const target = event.target;
            if (target instanceof HTMLImageElement) {
              const bounds = target.getBoundingClientRect();
              const scale = Math.min(
                bounds.width / target.naturalWidth,
                bounds.height / target.naturalHeight,
              );
              const renderedWidth = target.naturalWidth * scale;
              const renderedHeight = target.naturalHeight * scale;
              const localX = event.clientX - bounds.left;
              const localY = event.clientY - bounds.top;
              const insideRenderedImage =
                localX >= (bounds.width - renderedWidth) / 2 &&
                localX <= (bounds.width + renderedWidth) / 2 &&
                localY >= (bounds.height - renderedHeight) / 2 &&
                localY <= (bounds.height + renderedHeight) / 2;
              if (insideRenderedImage) return;
            }
            setLightboxImage(null);
          }}
        >
          <figure>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={lightboxImage.src} alt={lightboxImage.alt} />
            <figcaption>
              <strong>{fileName(lightboxImage.src)}</strong>
              <span>{lightboxImage.alt}</span>
            </figcaption>
          </figure>
        </div>
      )}

      {scanMessage && (
        <div className="scan-toast">
          <span />
          <p>{scanMessage}</p>
          <button onClick={() => setScanMessage("")} aria-label="Dismiss status">
            ×
          </button>
        </div>
      )}
    </main>
  );
}
