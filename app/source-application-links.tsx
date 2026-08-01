"use client";

type SourceApplicationLineageNode = {
  kind: string;
  path?: string;
  projectPath?: string;
  label?: string;
  detail?: string;
  evidence?: string;
  comparisonImage?: string;
  confirmationMethod?: string;
  proofStatus?: string;
  primaryRecoveryProof?: boolean;
  recoveryProof?: boolean;
  redshiftProof?: boolean;
  fullColorProof?: boolean;
  tags?: Array<{ type: string }>;
  sourceApplicationPrimary?: boolean;
};

export type SourceApplicationCut = {
  id: string;
  lineage: SourceApplicationLineageNode[];
  c4dVerification?: {
    checks?: {
      cameraProofRendered?: boolean;
      cameraProofMatched?: boolean;
      visualMatch?: boolean;
      dependencyAudited?: boolean;
      dependencyRenderSafe?: boolean;
    };
    elements?: {
      camera?: string;
    };
    authority?: string;
    cameraProof?: string;
    cameraName?: string;
  };
  c4dLinkStatus?: {
    strictDependencyRenderSafe?: boolean;
    exactCutAudit?: {
      strictDependencyRenderSafe?: boolean;
    };
  };
};

export type C4DCameraProofTone =
  | "redshift-verified"
  | "camera-verified"
  | "file-confirmed"
  | "unconfirmed";

export type C4DEvidenceResolution = {
  tone: C4DCameraProofTone;
  fileConfirmed: boolean;
  cameraMatched: boolean;
  proofRendered: boolean;
  proofConfirmed: boolean;
  dependencyRenderSafe: boolean;
  reason:
    | "redshift_camera_match"
    | "redshift_camera_match_dependencies_incomplete"
    | "redshift_grey_camera_match"
    | "hardware_camera_match"
    | "neutral_camera_match"
    | "c4d_file_unconfirmed"
    | "dependency_audit_incomplete"
    | "camera_test_unconfirmed"
    | "camera_mismatch"
    | "camera_test_missing"
    | "renderer_unconfirmed";
  c4dNode?: SourceApplicationLineageNode;
  activeProof?: SourceApplicationLineageNode;
};

const sourceKinds = {
  premiere: new Set([
    "premiere",
    "premiere_sequence",
    "premiere_export",
    "premiere_frame_alignment",
  ]),
  afterEffects: new Set([
    "after_effects",
    "after_effects_comp",
    "after_effects_layer",
  ]),
  cinema4d: new Set(["cinema4d"]),
};

function sourceNode(cut: SourceApplicationCut, kinds: Set<string>) {
  const nodes = cut.lineage.filter(
    (node) => kinds.has(node.kind) && (node.projectPath || node.path),
  );
  return (
    nodes.find((node) => node.sourceApplicationPrimary) ||
    nodes.find((node) =>
      node.tags?.some((tag) => tag.type === "chapter_edit"),
    ) ||
    nodes.find((node) => node.projectPath) ||
    nodes[0]
  );
}

function sourcePath(node?: SourceApplicationLineageNode) {
  return node?.projectPath || node?.path || "";
}

function fileName(path?: string) {
  if (!path) return "";
  return path.replace(/\/+$/, "").split("/").pop() || path;
}

export function c4dCameraProofTone(
  cut: SourceApplicationCut,
): C4DCameraProofTone {
  return resolveC4DEvidenceStatus(cut).tone;
}

export function resolveC4DEvidenceStatus(
  cut: SourceApplicationCut,
): C4DEvidenceResolution {
  const c4dNode = sourceNode(cut, sourceKinds.cinema4d);
  const verification = cut.c4dVerification;
  const activeProof = cut.lineage.find(
    (node) =>
      node.kind === "camera_proof" &&
      node.comparisonImage === verification?.cameraProof,
  );
  const fileConfirmed = c4dNode?.evidence === "confirmed";
  const cameraResult = (verification?.elements?.camera || "").toLowerCase();
  const cameraMatched =
    verification?.checks?.cameraProofMatched === true ||
    cameraResult === "match" ||
    cameraResult.startsWith("match_") ||
    cameraResult.startsWith("confirmed_exact_");
  const proofRendered = Boolean(
    verification?.checks?.cameraProofRendered === true &&
      activeProof?.comparisonImage &&
      activeProof.proofStatus?.startsWith("rendered"),
  );
  const proofConfirmed = activeProof?.evidence === "confirmed";
  const exactDependencyResult =
    cut.c4dLinkStatus?.exactCutAudit?.strictDependencyRenderSafe ??
    cut.c4dLinkStatus?.strictDependencyRenderSafe;
  const dependencyRenderSafe =
    exactDependencyResult ??
    Boolean(
      verification?.checks?.dependencyAudited === true &&
        verification?.checks?.dependencyRenderSafe === true,
    );

  if (!fileConfirmed) {
    return {
      tone: "unconfirmed",
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
      reason: "c4d_file_unconfirmed",
      c4dNode,
      activeProof,
    };
  }
  if (!proofRendered) {
    return {
      tone: "file-confirmed",
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
      reason: "camera_test_missing",
      c4dNode,
      activeProof,
    };
  }
  if (!cameraMatched) {
    return {
      tone: "file-confirmed",
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
      reason: "camera_mismatch",
      c4dNode,
      activeProof,
    };
  }

  const cameraProofEvidence = [
    activeProof?.detail,
    activeProof?.comparisonImage,
    activeProof?.confirmationMethod,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  const hasFullColorRedshiftProof =
    activeProof?.redshiftProof === true &&
    activeProof?.fullColorProof === true;
  if (
    hasFullColorRedshiftProof &&
    proofConfirmed &&
    dependencyRenderSafe
  ) {
    return {
      tone: "redshift-verified",
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
      reason: "redshift_camera_match",
      c4dNode,
      activeProof,
    };
  }
  const proofSupportsCameraMatch =
    proofConfirmed || activeProof?.evidence === "partial";
  if (hasFullColorRedshiftProof && proofSupportsCameraMatch) {
    return {
      tone: "camera-verified",
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
      reason: "redshift_camera_match_dependencies_incomplete",
      c4dNode,
      activeProof,
    };
  }
  if (proofSupportsCameraMatch && activeProof?.redshiftProof === true) {
    return {
      tone: "camera-verified",
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
      reason: "redshift_grey_camera_match",
      c4dNode,
      activeProof,
    };
  }

  const hasHardwareProof =
    proofSupportsCameraMatch &&
    activeProof?.redshiftProof === false &&
    /cinema 4d hardware|hardware camera proof|hardware preview/.test(
      cameraProofEvidence,
    );
  if (hasHardwareProof) {
    return {
      tone: "camera-verified",
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
      reason: "hardware_camera_match",
      c4dNode,
      activeProof,
    };
  }
  if (proofSupportsCameraMatch) {
    return {
      tone: "camera-verified",
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
      reason: "neutral_camera_match",
      c4dNode,
      activeProof,
    };
  }
  if (!proofConfirmed) {
    return {
      tone: "file-confirmed",
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
      reason: "camera_test_unconfirmed",
      c4dNode,
      activeProof,
    };
  }
  return {
    tone: "file-confirmed",
    fileConfirmed,
    cameraMatched,
    proofRendered,
    proofConfirmed,
    dependencyRenderSafe,
    reason: "renderer_unconfirmed",
    c4dNode,
    activeProof,
  };
}

export function SourceApplicationLinks({
  cut,
  apiBase,
  onMessage,
}: {
  cut: SourceApplicationCut;
  apiBase: string;
  onMessage?: (message: string) => void;
}) {
  const c4dProofTone = c4dCameraProofTone(cut);
  const applications = [
    {
      label: "PR",
      name: "Premiere",
      node: sourceNode(cut, sourceKinds.premiere),
    },
    {
      label: "AE",
      name: "After Effects",
      node: sourceNode(cut, sourceKinds.afterEffects),
    },
    {
      label: "C4D",
      name: "Cinema 4D",
      node: sourceNode(cut, sourceKinds.cinema4d),
    },
  ].map((application) => ({
    ...application,
    filename: fileName(sourcePath(application.node)),
    proofTone:
      application.label === "C4D" && application.node
        ? c4dProofTone
        : undefined,
  }));

  async function revealSourceAndCopyDirectory(
    node?: SourceApplicationLineageNode,
  ) {
    const path = sourcePath(node);
    if (!path) return;
    try {
      const response = await fetch(`${apiBase}/api/reveal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, copyDirectory: true }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(result.error || "Unable to reveal source.");
      }
      onMessage?.(`Copied folder: ${result.directory}`);
    } catch (error) {
      onMessage?.(
        error instanceof Error ? error.message : "Unable to reveal source.",
      );
    }
  }

  return (
    <div className="cut-source-links" aria-label="Source applications">
      {applications.map((application) => (
        <button
          key={application.label}
          className={[
            application.node ? "available" : "missing",
            application.proofTone
              ? `c4d-camera-${application.proofTone}`
              : "",
          ]
            .filter(Boolean)
            .join(" ")}
          disabled={!application.node}
          data-app={application.label}
          data-filename={application.filename || undefined}
          data-camera-proof={application.proofTone}
          title={
            application.node
              ? [
                  application.filename,
                  application.proofTone === "redshift-verified"
                    ? "C4D file confirmed · RS camera visually verified"
                    : application.proofTone === "camera-verified"
                      ? "C4D file confirmed · camera visually matched · full color not verified"
                      : application.proofTone === "file-confirmed"
                        ? "C4D file confirmed · no matching visual camera proof"
                      : application.label === "C4D"
                        ? "C4D file not confirmed"
                        : "",
                ]
                  .filter(Boolean)
                  .join(" · ")
              : `${application.name} source missing`
          }
          aria-label={
            application.node
              ? `Reveal ${application.filename} in Finder and copy its containing folder`
              : `${application.name} source missing for ${cut.id}`
          }
          onClick={() =>
            application.node &&
            void revealSourceAndCopyDirectory(application.node)
          }
        >
          {application.label}
        </button>
      ))}
    </div>
  );
}
