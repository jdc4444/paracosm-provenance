#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const statePath = path.join(root, "public", "data", "state.json");
const statusPath = path.join(
  root,
  "data",
  "c4d-status-consistency-audit-20260728.json",
);
const inventoryPath = path.join(
  root,
  "data",
  "c4d-full-color-camera-render-inventory-20260729.json",
);
const snapshotPath = path.join(root, "data", "worktree-snapshot-20260801.json");
const jsonOutput = path.join(
  root,
  "data",
  "c4d-consolidated-handoff-20260801.json",
);
const markdownOutput = path.join(
  root,
  "data",
  "c4d-consolidated-handoff-20260801.md",
);

function readJson(filename) {
  return JSON.parse(fs.readFileSync(filename, "utf8"));
}

function relative(filename) {
  return path.relative(root, filename);
}

const state = readJson(statePath);
const status = readJson(statusPath);
const inventory = readJson(inventoryPath);
const pictureCuts = state.cuts.filter((cut) => !cut.isGap);
const renderedCuts = new Set(
  inventory.records.map((record) => String(record.cutId || "")),
);
const missingFullColorCuts = pictureCuts
  .map((cut) => cut.id)
  .filter((cutId) => !renderedCuts.has(cutId));
const unresolvedCuts = status.cuts
  .filter(
    (cut) =>
      cut.pictureCut &&
      !["redshift-verified", "camera-verified"].includes(cut.expectedTone),
  )
  .map((cut) => ({
    cutId: cut.cutId,
    tone: cut.expectedTone,
    reason: cut.reason,
    c4dFilePath: cut.c4dFilePath,
    cameraImage: cut.cameraImage,
  }));
const scopeExceptions = pictureCuts
  .map((cut) => ({
    cutId: cut.id,
    ...(cut.c4dVerification?.linkageAudit || {}),
  }))
  .filter(
    (audit) =>
      audit.scope !== "active_project_take_and_frame" &&
      audit.scope !== "active_project_take_render_graph",
  )
  .map((audit) => ({
    cutId: audit.cutId,
    scope: audit.scope,
    auditProject: audit.auditProject,
    auditTake: audit.auditTake,
    auditFrame: audit.auditFrame,
    activeProofFrame: audit.activeProofFrame,
    matchesActiveProject: audit.matchesActiveProject,
    matchesActiveFrame: audit.matchesActiveFrame,
  }));
const integration = {
  dependencyAuditLinks: pictureCuts.filter(
    (cut) => cut.c4dVerification?.dependencyAuditPath,
  ).length,
  linkageAuditLinks: pictureCuts.filter(
    (cut) => cut.c4dVerification?.linkageAudit,
  ).length,
  cameraLineageLinks: pictureCuts.filter((cut) =>
    cut.lineage?.some((node) => node.kind === "camera"),
  ).length,
  recoveryPrescriptions: pictureCuts.filter(
    (cut) => cut.c4dVerification?.recoveryPrescription,
  ).length,
};

const porcelain = execFileSync("git", ["status", "--porcelain=v1", "-z"], {
  cwd: root,
  encoding: "utf8",
});
const statusEntries = porcelain.split("\0").filter(Boolean);
const worktree = {
  trackedModifiedOrDeleted: statusEntries.filter(
    (entry) => !entry.startsWith("??"),
  ).length,
  untracked: statusEntries.filter((entry) => entry.startsWith("??")).length,
  total: statusEntries.length,
  clean: statusEntries.length === 0,
};
const snapshot = fs.existsSync(snapshotPath) ? readJson(snapshotPath) : null;
const generatedAt = new Date().toISOString();
const payload = {
  schemaVersion: 1,
  generatedAt,
  authority: [
    relative(statePath),
    relative(statusPath),
    relative(inventoryPath),
  ],
  canonicalScope: {
    totalCuts: status.summary.totalCuts,
    pictureCuts: status.summary.pictureCuts,
    gapCuts: status.summary.gapCuts,
  },
  verification: {
    ...status.summary.countsByTone,
    greenYellowCuts:
      status.summary.countsByTone["redshift-verified"] +
      status.summary.countsByTone["camera-verified"],
    inconsistentCuts: status.summary.inconsistentCuts,
  },
  integration,
  fullColorRenderInventory: {
    renderedFrames: inventory.summary.renderedFrames,
    renderedShots: inventory.summary.renderedShots,
    missingCuts: missingFullColorCuts,
    proofPolicy:
      "Inventory presence is process evidence only and never promotes a cut.",
  },
  unresolvedCuts,
  dependencyAuditScopeExceptions: scopeExceptions,
  safety: {
    activeUnsafeRelinkMappings: status.summary.unsafeRelinkMappings,
    rejectedHistoricalUnsafeProcessRenders:
      status.summary.unsafeProcessRenders,
    policy:
      "Rejected and quarantined targets never qualify as linkage or camera proof.",
  },
  worktree,
  snapshot,
  regeneration: [
    "python3 scripts/scan.py",
    "node scripts/audit-c4d-status.mjs",
    "node scripts/build_c4d_consolidated_handoff.mjs",
  ],
};

fs.writeFileSync(jsonOutput, `${JSON.stringify(payload, null, 2)}\n`);

const unresolvedRows = unresolvedCuts
  .map(
    (cut) =>
      `| ${cut.cutId} | ${cut.tone} | ${cut.reason} | ${cut.c4dFilePath || "—"} |`,
  )
  .join("\n");
const scopeRows = scopeExceptions.length
  ? scopeExceptions
      .map(
        (audit) =>
          `| ${audit.cutId} | ${audit.scope} | ${audit.auditFrame ?? "—"} | ${audit.activeProofFrame ?? "—"} |`,
      )
      .join("\n")
  : "| — | No scope exceptions | — | — |";
const snapshotSummary = snapshot
  ? `Complete snapshot: \`${snapshot.path}\` (${snapshot.method}, ${snapshot.status}).`
  : "Complete snapshot has not yet been recorded.";

const markdown = `# Paracosm C4D consolidated handoff

Generated: ${generatedAt}

## Current verified state

- Canonical conform: ${payload.canonicalScope.pictureCuts} picture cuts and ${payload.canonicalScope.gapCuts} intentional gaps.
- Status: ${payload.verification["redshift-verified"]} green, ${payload.verification["camera-verified"]} yellow, ${payload.verification["file-confirmed"]} black, ${payload.verification.unconfirmed} grey.
- Green/yellow camera-confirmed total: ${payload.verification.greenYellowCuts}/${payload.canonicalScope.pictureCuts}.
- Integration: ${integration.dependencyAuditLinks}/${payload.canonicalScope.pictureCuts} dependency-audit links, ${integration.linkageAuditLinks}/${payload.canonicalScope.pictureCuts} linkage audits, ${integration.cameraLineageLinks}/${payload.canonicalScope.pictureCuts} camera-lineage nodes, and ${integration.recoveryPrescriptions}/${payload.canonicalScope.pictureCuts} recovery/preservation prescriptions.
- Fresh full-color Redshift process inventory: ${payload.fullColorRenderInventory.renderedFrames} frames across ${payload.fullColorRenderInventory.renderedShots}/${payload.canonicalScope.pictureCuts} picture cuts.
- Consistency audit: ${payload.verification.inconsistentCuts} inconsistent cuts and ${payload.safety.activeUnsafeRelinkMappings} active unsafe relink mappings.

## Unresolved verification cuts

| Cut | Current tone | Reason | Selected C4D |
| --- | --- | --- | --- |
${unresolvedRows}

## Dependency-audit scope exceptions

| Cut | Scope | Audited frame | Active proof frame |
| --- | --- | ---: | ---: |
${scopeRows}

These exceptions are linked as supporting evidence with the scope difference explicit; they are not represented as exact active-frame audits.

## Safety and proof policy

- Historical production frames and composites are reference/process images only.
- Fresh full-color inventory presence never promotes a cut.
- ${payload.safety.rejectedHistoricalUnsafeProcessRenders} historical renders that used rejected/unproven targets remain explicitly disqualified.
- Cross-shot character, hair, wardrobe, proxy, cache, and material substitutions are forbidden.

## Versioning

- Current worktree: ${worktree.trackedModifiedOrDeleted} tracked modified/deleted paths and ${worktree.untracked} untracked paths (${worktree.total} total).
- ${snapshotSummary}

## Regeneration

\`\`\`text
${payload.regeneration.join("\n")}
\`\`\`
`;
fs.writeFileSync(markdownOutput, markdown);

console.log(
  JSON.stringify(
    {
      json: relative(jsonOutput),
      markdown: relative(markdownOutput),
      verification: payload.verification,
      integration,
      fullColorRenderInventory: payload.fullColorRenderInventory,
      worktree,
      snapshot,
    },
    null,
    2,
  ),
);
