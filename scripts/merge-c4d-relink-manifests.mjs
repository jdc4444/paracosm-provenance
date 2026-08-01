#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

function usage() {
  console.error(
    "Usage: node scripts/merge-c4d-relink-manifests.mjs " +
      "--output <path> --source <path> [--source <path> ...]",
  );
  process.exit(2);
}

const args = process.argv.slice(2);
const sourcePaths = [];
let outputPath = "";
for (let index = 0; index < args.length; index += 1) {
  const value = args[index];
  if (value === "--source" && args[index + 1]) {
    sourcePaths.push(path.resolve(args[index + 1]));
    index += 1;
  } else if (value === "--output" && args[index + 1]) {
    outputPath = path.resolve(args[index + 1]);
    index += 1;
  } else {
    usage();
  }
}
if (!outputPath || sourcePaths.length === 0) usage();
if (fs.existsSync(outputPath)) {
  throw new Error(`Refusing to overwrite existing output: ${outputPath}`);
}

const sources = sourcePaths.map((sourcePath) => ({
  sourcePath,
  payload: JSON.parse(fs.readFileSync(sourcePath, "utf8")),
}));
const mappingsByRequiredPath = new Map();
const unresolved = new Set();
const unresolvedCandidates = [];

for (const { payload } of sources) {
  for (const item of payload.mappings ?? []) {
    const requiredPath = String(item?.requiredPath ?? "");
    if (requiredPath) mappingsByRequiredPath.set(requiredPath, item);
  }
  for (const requiredPath of payload.unresolved ?? []) {
    if (String(requiredPath)) unresolved.add(String(requiredPath));
  }
  for (const item of payload.unresolvedCandidates ?? []) {
    if (item && typeof item === "object") unresolvedCandidates.push(item);
  }
  for (const item of payload.renderObservedUnresolvedCandidates ?? []) {
    if (item && typeof item === "object") unresolvedCandidates.push(item);
  }
}
for (const requiredPath of mappingsByRequiredPath.keys()) {
  unresolved.delete(requiredPath);
}

const output = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  authority:
    "Deterministic union of the listed exact-path manifests. Later sources " +
    "override only the same authored requiredPath; unresolved entries are " +
    "removed only when an exact mapping exists.",
  sourceManifests: sources.map(({ sourcePath }) => sourcePath),
  renderCriticalOnly: false,
  summary: {
    sourceManifestCount: sources.length,
    sourceMappedPathCounts: Object.fromEntries(
      sources.map(({ sourcePath, payload }) => [
        path.basename(sourcePath),
        (payload.mappings ?? []).length,
      ]),
    ),
    totalMappedPaths: mappingsByRequiredPath.size,
    totalUnresolvedPaths: unresolved.size,
  },
  mappings: [...mappingsByRequiredPath.values()],
  unresolved: [...unresolved].sort(),
  unresolvedCandidates,
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(output, null, 2)}\n`);
console.log(
  JSON.stringify({
    outputPath,
    mappedPaths: output.summary.totalMappedPaths,
    unresolvedPaths: output.summary.totalUnresolvedPaths,
  }),
);
