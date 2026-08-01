import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const statePath = path.join(projectRoot, "public/data/state.json");
const outputPath = path.join(
  projectRoot,
  "data/c4d-status-consistency-audit-20260728.json",
);
const publicOutputPath = path.join(
  projectRoot,
  "public/data/c4d-status-consistency-audit-20260728.json",
);

const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
const relinkAuditDir = path.join(
  projectRoot,
  "data/c4d-cut-dependency-audits-20260728",
);
const cleanRecoveryDir = path.join(
  projectRoot,
  "data/c4d-clean-recoveries",
);

function unsafeRelinkTargetReason(targetPath) {
  const parts = String(targetPath || "")
    .replaceAll("\\", "/")
    .split("/")
    .filter(Boolean)
    .map((part) => part.toLowerCase().replaceAll("-", "_"));
  for (const part of parts) {
    if (
      part === "quarantine" ||
      part.startsWith("quarantine_") ||
      part.endsWith("_quarantine")
    ) {
      return "quarantined_target";
    }
    if (part.includes("rejected") && part.includes("unproven")) {
      return "rejected_unproven_target";
    }
  }
  return null;
}

const unsafeRelinkMappings = fs.existsSync(relinkAuditDir)
  ? fs
      .readdirSync(relinkAuditDir)
      .filter((filename) => /-relink-manifest(?:-[^.]+)?\.json$/i.test(filename))
      .flatMap((filename) => {
        const manifest = JSON.parse(
          fs.readFileSync(path.join(relinkAuditDir, filename), "utf8"),
        );
        return (manifest.mappings || []).flatMap((mapping) => {
          const reason = unsafeRelinkTargetReason(mapping.targetPath);
          return reason
            ? [
                {
                  cutId: filename.match(/CUT-\d{3}/i)?.[0]?.toUpperCase() || null,
                  manifest: filename,
                  requiredPath: mapping.requiredPath,
                  targetPath: mapping.targetPath,
                  reason,
                },
              ]
            : [];
        });
      })
  : [];

const unsafeProcessRenders = fs.existsSync(cleanRecoveryDir)
  ? fs
      .readdirSync(cleanRecoveryDir)
      .filter((filename) => /-result\.json$/i.test(filename))
      .flatMap((filename) => {
        const result = JSON.parse(
          fs.readFileSync(path.join(cleanRecoveryDir, filename), "utf8"),
        );
        const violations = [
          "temporaryExactDependencyRelinks",
          "temporaryExactMaterialRelinks",
          "temporaryExactSceneMaterialRelinks",
          "postEvaluationExactMaterialRelinks",
          "postEvaluationExactSceneMaterialRelinks",
        ].flatMap((relinkGroup) =>
          (result[relinkGroup] || []).flatMap((mapping) => {
            const reason = unsafeRelinkTargetReason(mapping.targetPath);
            return reason
              ? [
                  {
                    relinkGroup,
                    requiredPath: mapping.requiredPath,
                    targetPath: mapping.targetPath,
                    reason,
                  },
                ]
              : [];
          }),
        );
        if (!violations.length) return [];
        return [
          {
            cutId:
              filename.match(/CUT-\d{3}/i)?.[0]?.toUpperCase() || null,
            resultPath: `data/c4d-clean-recoveries/${filename}`,
            outputPath: result.output || null,
            violations,
          },
        ];
      })
  : [];

function sourceC4DNode(cut) {
  const nodes = cut.lineage.filter(
    (node) =>
      node.kind === "cinema4d" && (node.projectPath || node.path),
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

function isComposite(pathname) {
  const filename = String(pathname || "")
    .replace(/\/+$/, "")
    .split("/")
    .pop();
  return /(?:^|[._-])(?:contact|comparison|composite|pair|sheet)(?:[._-]|$)/i.test(
    filename,
  );
}

function isHistoricalProductionReference(pathname) {
  const normalized = String(pathname || "").toLowerCase();
  return (
    normalized.startsWith("/archive/c4d-source-frames-20260726/") ||
    normalized.includes("__historical-redshift.")
  );
}

function publicImageExists(publicPath) {
  const imagePath = String(publicPath || "");
  if (!imagePath.startsWith("/")) return null;
  if (path.isAbsolute(imagePath) && imagePath.startsWith(projectRoot)) {
    return fs.existsSync(imagePath);
  }
  return fs.existsSync(path.join(projectRoot, "public", imagePath));
}

function publicEvidenceImagePath(imagePath) {
  const pathname = String(imagePath || "");
  const publicRoot = path.join(projectRoot, "public");
  if (pathname.startsWith(`${publicRoot}/`)) {
    return pathname.slice(publicRoot.length);
  }
  return pathname.startsWith("/archive/") || pathname.startsWith("/data/")
    ? pathname
    : null;
}

function resolveStatus(cut) {
  const c4dNode = sourceC4DNode(cut);
  const verification = cut.c4dVerification || {};
  const activeProof = cut.lineage.find(
    (node) =>
      node.kind === "camera_proof" &&
      node.comparisonImage === verification.cameraProof,
  );
  const fileConfirmed = c4dNode?.evidence === "confirmed";
  const cameraResult = String(
    verification.elements?.camera || "",
  ).toLowerCase();
  const cameraMatched =
    verification.checks?.cameraProofMatched === true ||
    cameraResult === "match" ||
    cameraResult.startsWith("match_") ||
    cameraResult.startsWith("confirmed_exact_");
  const proofRendered = Boolean(
    verification.checks?.cameraProofRendered === true &&
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
      verification.checks?.dependencyAudited === true &&
        verification.checks?.dependencyRenderSafe === true,
    );

  if (!fileConfirmed) {
    return {
      tone: "unconfirmed",
      reason: "c4d_file_unconfirmed",
      c4dNode,
      activeProof,
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
    };
  }
  if (!proofRendered) {
    return {
      tone: "file-confirmed",
      reason: "camera_test_missing",
      c4dNode,
      activeProof,
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
    };
  }
  if (!cameraMatched) {
    return {
      tone: "file-confirmed",
      reason: "camera_mismatch",
      c4dNode,
      activeProof,
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
    };
  }

  const proofText = [
    activeProof?.detail,
    activeProof?.comparisonImage,
    activeProof?.confirmationMethod,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (
    activeProof?.redshiftProof === true &&
    activeProof?.fullColorProof === true &&
    proofConfirmed &&
    dependencyRenderSafe
  ) {
    return {
      tone: "redshift-verified",
      reason: "redshift_camera_match",
      c4dNode,
      activeProof,
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
    };
  }
  const proofSupportsCameraMatch =
    proofConfirmed || activeProof?.evidence === "partial";
  if (
    proofSupportsCameraMatch &&
    activeProof?.redshiftProof === true &&
    activeProof?.fullColorProof === true
  ) {
    return {
      tone: "camera-verified",
      reason: "redshift_camera_match_dependencies_incomplete",
      c4dNode,
      activeProof,
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
    };
  }
  if (proofSupportsCameraMatch && activeProof?.redshiftProof === true) {
    return {
      tone: "camera-verified",
      reason: "redshift_grey_camera_match",
      c4dNode,
      activeProof,
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
    };
  }
  if (
    proofSupportsCameraMatch &&
    activeProof?.redshiftProof === false &&
    /cinema 4d hardware|hardware camera proof|hardware preview/.test(
      proofText,
    )
  ) {
    return {
      tone: "camera-verified",
      reason: "hardware_camera_match",
      c4dNode,
      activeProof,
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
    };
  }
  if (proofSupportsCameraMatch) {
    return {
      tone: "camera-verified",
      reason: "neutral_camera_match",
      c4dNode,
      activeProof,
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
    };
  }
  if (!proofConfirmed) {
    return {
      tone: "file-confirmed",
      reason: "camera_test_unconfirmed",
      c4dNode,
      activeProof,
      fileConfirmed,
      cameraMatched,
      proofRendered,
      proofConfirmed,
      dependencyRenderSafe,
    };
  }
  return {
    tone: "file-confirmed",
    reason: "renderer_unconfirmed",
    c4dNode,
    activeProof,
    fileConfirmed,
    cameraMatched,
    proofRendered,
    proofConfirmed,
    dependencyRenderSafe,
  };
}

const records = state.cuts.map((cut) => {
  const status = resolveStatus(cut);
  const verification = cut.c4dVerification || {};
  const cameraImage = verification.cameraProof || null;
  const processImages = new Set(
    cut.lineage
      .map((node) => node.comparisonImage)
      .map(publicEvidenceImagePath)
      .filter(Boolean),
  );
  const materialAudit = verification.materialCompatibilityAudit || {};
  const additionalImages = [
    verification.comparisonImage,
    verification.renderReference,
    ...Object.entries(materialAudit)
      .filter(
        ([key, value]) =>
          typeof value === "string" &&
          /(?:output|comparison)path$/i.test(key) &&
          /\.(?:avif|gif|jpe?g|png|webp)$/i.test(value),
      )
      .map(([, value]) => value),
  ];
  for (const image of additionalImages) {
    const publicImage = publicEvidenceImagePath(image);
    if (publicImage) processImages.add(publicImage);
  }
  const inconsistencies = [];
  if (unsafeRelinkMappings.some((item) => item.cutId === cut.id)) {
    inconsistencies.push("unsafe_relink_manifest_target");
  }
  const activeProofResultPath = String(
    status.activeProof?.resultPath ||
      status.activeProof?.redshiftResultPath ||
      "",
  ).replaceAll("\\", "/");
  if (
    activeProofResultPath &&
    unsafeProcessRenders.some((item) =>
      item.resultPath.endsWith(activeProofResultPath),
    )
  ) {
    inconsistencies.push("unsafe_process_render_used_as_camera_proof");
  }
  if (verification.checks?.cameraProofRendered && !cameraImage) {
    inconsistencies.push("rendered_flag_without_camera_image");
  }
  if (cameraImage && !status.activeProof) {
    inconsistencies.push("camera_image_without_exact_proof_node");
  }
  if (cameraImage && isComposite(cameraImage)) {
    inconsistencies.push("composite_used_as_camera_image");
  }
  if (cameraImage && isHistoricalProductionReference(cameraImage)) {
    inconsistencies.push("historical_frame_used_as_camera_image");
  }
  if (cameraImage && publicImageExists(cameraImage) === false) {
    inconsistencies.push("camera_image_missing_from_public_archive");
  }
  for (const image of processImages) {
    if (publicImageExists(image) === false) {
      inconsistencies.push(`process_image_missing:${image}`);
    }
  }
  if (
    status.tone === "redshift-verified" &&
    (!status.fileConfirmed ||
      !status.proofRendered ||
      !status.proofConfirmed ||
      !status.cameraMatched ||
      status.activeProof?.fullColorProof !== true)
  ) {
    inconsistencies.push("green_without_full_color_redshift_contract");
  }
  if (
    status.tone === "camera-verified" &&
    (!status.fileConfirmed ||
      !status.proofRendered ||
      !status.cameraMatched ||
      !(
        status.proofConfirmed ||
        status.activeProof?.evidence === "partial"
      ))
  ) {
    inconsistencies.push("yellow_without_matching_camera_contract");
  }
  if (
    status.tone === "file-confirmed" &&
    status.fileConfirmed &&
    status.proofRendered &&
    status.cameraMatched &&
    (status.proofConfirmed || status.activeProof?.evidence === "partial")
  ) {
    inconsistencies.push("black_despite_usable_matching_camera_proof");
  }
  if (!status.fileConfirmed && status.tone !== "unconfirmed") {
    inconsistencies.push("unconfirmed_file_not_grey");
  }

  return {
    cutId: cut.id,
    pictureCut: !cut.isGap,
    c4dFilePath:
      status.c4dNode?.projectPath || status.c4dNode?.path || null,
    c4dFileEvidence: status.c4dNode?.evidence || "missing",
    cameraImage,
    cameraImageRole: status.proofRendered
      ? status.tone === "redshift-verified"
        ? "qualifying_full_color_proof"
        : status.tone === "camera-verified"
          ? "qualifying_camera_proof"
        : status.cameraMatched
          ? "matching_nonqualifying_camera_test"
        : "nonqualifying_camera_test"
      : cameraImage
        ? "nonqualifying_camera_test"
        : "none",
    proofNodeEvidence: status.activeProof?.evidence || null,
    proofStatus: status.activeProof?.proofStatus || null,
    fullColorProof: status.activeProof?.fullColorProof === true,
    renderer: status.activeProof?.redshiftProof
      ? status.activeProof?.fullColorProof === true
        ? "redshift_full_color"
        : "redshift_nonqualifying_or_grey"
      : status.activeProof?.redshiftProof === false
        ? "hardware_or_unspecified_non_redshift"
        : null,
    cameraResult: verification.elements?.camera || null,
    expectedTone: status.tone,
    reason: status.reason,
    processImageCount: processImages.size,
    processImages: [...processImages],
    inconsistencies,
  };
});

const pictureRecords = records.filter((record) => record.pictureCut);
const countsByTone = Object.fromEntries(
  ["redshift-verified", "camera-verified", "file-confirmed", "unconfirmed"].map(
    (tone) => [
      tone,
      pictureRecords.filter((record) => record.expectedTone === tone).length,
    ],
  ),
);
const inconsistentRecords = records.filter(
  (record) => record.inconsistencies.length,
);
const report = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  authority:
    "public/data/state.json evaluated against the shared C4D file and camera-proof color contract",
  contract: {
    green:
      "Confirmed C4D file plus a strict frame-specific dependency pass and a confirmed newly rendered full-color material Redshift visual match",
    yellow:
      "Confirmed C4D file plus a newly rendered matching grey or neutral Redshift proof, a matching Cinema 4D Hardware Preview, or a full-color match whose strict dependency gate is incomplete",
    black: "Confirmed C4D file without a usable matching visual camera proof",
    grey: "C4D file absent or unconfirmed",
    references:
      "Historical production images and composites remain process/reference images and never affect color",
  },
  summary: {
    totalCuts: records.length,
    pictureCuts: pictureRecords.length,
    gapCuts: records.length - pictureRecords.length,
    countsByTone,
    cutsWithCameraImages: pictureRecords.filter(
      (record) => record.cameraImage,
    ).length,
    cutsWithProcessImages: pictureRecords.filter(
      (record) => record.processImageCount,
    ).length,
    inconsistentCuts: inconsistentRecords.length,
    unsafeRelinkMappings: unsafeRelinkMappings.length,
    unsafeProcessRenders: unsafeProcessRenders.length,
  },
  unsafeRelinkMappings,
  unsafeProcessRenders,
  inconsistentCutIds: inconsistentRecords.map((record) => record.cutId),
  cuts: records,
};

const serialized = `${JSON.stringify(report, null, 2)}\n`;
fs.writeFileSync(outputPath, serialized);
fs.writeFileSync(publicOutputPath, serialized);

if (inconsistentRecords.length) {
  console.error(
    JSON.stringify(
      {
        summary: report.summary,
        inconsistencies: inconsistentRecords.map((record) => ({
          cutId: record.cutId,
          inconsistencies: record.inconsistencies,
        })),
      },
      null,
      2,
    ),
  );
  process.exitCode = 1;
} else {
  console.log(JSON.stringify(report.summary, null, 2));
}
