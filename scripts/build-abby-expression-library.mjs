import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const manifestPath = join(root, "data", "abby-expression-library.json");
const supplementalCuePath = join(
  root,
  "data",
  "abby-performance-facial-cues.json",
);
const baseManifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const supplementalCues = JSON.parse(
  readFileSync(supplementalCuePath, "utf8"),
).cues;
const cues = [...baseManifest.cues, ...supplementalCues];
const manifest = {
  ...baseManifest,
  summary: {
    ...baseManifest.summary,
    facialExpressionCount: cues.filter((cue) => isFacialCueKind(cue.kind))
      .length,
    performanceBeatCount: cues.filter(
      (cue) => !isFacialCueKind(cue.kind),
    ).length,
  },
  cues,
};
const force = process.argv.includes("--force");
const forceCloseups =
  force || process.argv.includes("--force-closeups");
const forceSourceIndex = process.argv.indexOf("--force-source");
const forceSourceId =
  forceSourceIndex >= 0 ? process.argv[forceSourceIndex + 1] : "";
const archiveRoot = join(
  root,
  "public",
  "archive",
  "character-reference",
  "abby",
  "expression-library",
);
const sourceDirectory = join(archiveRoot, "sources");
const posterDirectory = join(archiveRoot, "posters");
const previewDirectory = join(archiveRoot, "previews");
const publicManifest = join(root, "public", "data", "abby-expression-library.json");

mkdirSync(sourceDirectory, { recursive: true });
mkdirSync(posterDirectory, { recursive: true });
mkdirSync(previewDirectory, { recursive: true });
mkdirSync(dirname(publicManifest), { recursive: true });

const sourceById = new Map(manifest.sources.map((source) => [source.id, source]));
const facialCues = manifest.cues.filter((cue) =>
  isFacialCueKind(cue.kind),
);
const performanceCues = manifest.cues.filter(
  (cue) => !isFacialCueKind(cue.kind),
);

function isFacialCueKind(kind) {
  return kind !== "performance_beat" && kind !== "hand_performance";
}

function runFfmpeg(args) {
  execFileSync("ffmpeg", ["-hide_banner", "-loglevel", "error", ...args], {
    stdio: "inherit",
  });
}

function visualFilter(source, tail) {
  const normalizeHlg = source.toneMap
    ? ["eq=gamma=0.72:saturation=1.18:contrast=1.03"]
    : [];
  return [...normalizeHlg, ...tail].join(",");
}

function squareCrop(size) {
  return [
    "crop='min(iw,ih)':'min(iw,ih)':'(iw-ow)/2':'(ih-oh)/2'",
    `scale=${size}:${size}:flags=lanczos`,
  ];
}

function cueCrop(cue, source, size) {
  const focus = cue.posterFocus || source.posterFocus;
  if (!focus) return squareCrop(size);
  const side = `min(iw,ih)*${focus.scale}`;
  return [
    `crop='${side}':'${side}':'max(0,min(iw-ow,iw*${focus.x}-ow/2))':'max(0,min(ih-oh,ih*${focus.y}-oh/2))'`,
    `scale=${size}:${size}:flags=lanczos`,
  ];
}

function hasUsableFile(path) {
  return existsSync(path) && statSync(path).size > 1024;
}

function hasUsableVideo(path, expectedDuration) {
  if (!hasUsableFile(path)) return false;
  try {
    const duration = Number(
      execFileSync(
        "ffprobe",
        [
          "-v",
          "error",
          "-show_entries",
          "format=duration",
          "-of",
          "default=nk=1:nw=1",
          path,
        ],
        { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] },
      ).trim(),
    );
    return Number.isFinite(duration) && duration >= expectedDuration - 0.2;
  } catch {
    return false;
  }
}

for (const source of manifest.sources) {
  const target = join(sourceDirectory, `${source.id}.mp4`);
  if (!force && hasUsableVideo(target, source.durationSeconds)) continue;
  const partialTarget = `${target}.partial.mp4`;
  rmSync(partialTarget, { force: true });

  runFfmpeg([
    "-y",
    "-i",
    source.originalPath,
    "-map",
    "0:v:0",
    "-map",
    "0:a:0?",
    "-vf",
    visualFilter(source, [
      ...squareCrop(720),
      "fps=30",
      "format=yuv420p",
      "setsar=1",
    ]),
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "24",
    "-profile:v",
    "high",
    "-level:v",
    "4.1",
    "-metadata:s:v:0",
    "rotate=0",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-colorspace",
    "bt709",
    "-c:a",
    "aac",
    "-b:a",
    "96k",
    "-ac",
    "1",
    "-movflags",
    "+faststart",
    partialTarget,
  ]);
  renameSync(partialTarget, target);
}

for (const cue of facialCues) {
  const source = sourceById.get(cue.sourceId);
  if (!source) {
    throw new Error(`Unknown source ${cue.sourceId} for cue ${cue.id}`);
  }
  const expectedDuration = cue.end - cue.start;
  const target = join(previewDirectory, `${cue.id}.mp4`);
  const rebuildCloseup =
    forceCloseups && (!forceSourceId || cue.sourceId === forceSourceId);
  if (!rebuildCloseup && hasUsableVideo(target, expectedDuration)) continue;
  const partialTarget = `${target}.partial.mp4`;
  rmSync(partialTarget, { force: true });

  runFfmpeg([
    "-y",
    "-ss",
    String(cue.start),
    "-i",
    source.originalPath,
    "-t",
    String(expectedDuration),
    "-map",
    "0:v:0",
    "-vf",
    visualFilter(source, [
      ...cueCrop(cue, source, 720),
      "fps=30",
      "format=yuv420p",
      "setsar=1",
    ]),
    "-c:v",
    "libx264",
    "-preset",
    "medium",
    "-crf",
    "24",
    "-profile:v",
    "high",
    "-level:v",
    "4.1",
    "-metadata:s:v:0",
    "rotate=0",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-colorspace",
    "bt709",
    "-an",
    "-movflags",
    "+faststart",
    partialTarget,
  ]);
  renameSync(partialTarget, target);
}

for (const cue of manifest.cues) {
  const source = sourceById.get(cue.sourceId);
  if (!source) {
    throw new Error(`Unknown source ${cue.sourceId} for cue ${cue.id}`);
  }
  const target = join(posterDirectory, `${cue.id}.jpg`);
  const rebuildFocusedPoster =
    forceCloseups &&
    isFacialCueKind(cue.kind) &&
    (!forceSourceId || cue.sourceId === forceSourceId);
  if (!rebuildFocusedPoster && hasUsableFile(target)) continue;
  const partialTarget = `${target}.partial.jpg`;
  rmSync(partialTarget, { force: true });

  runFfmpeg([
    "-y",
    "-ss",
    String(cue.peak),
    "-i",
    source.originalPath,
    "-frames:v",
    "1",
    "-vf",
    visualFilter(source, [
      ...cueCrop(cue, source, 640),
      "format=yuv420p",
      "setsar=1",
    ]),
    "-q:v",
    "3",
    partialTarget,
  ]);
  renameSync(partialTarget, target);
}

writeFileSync(publicManifest, `${JSON.stringify(manifest, null, 2)}\n`);

console.log(
  `Built ${manifest.sources.length} source proxies, ${facialCues.length} close-up facial previews, and ${performanceCues.length} performance cues.`,
);
