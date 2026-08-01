#!/usr/bin/env node

import fs from "node:fs";

const [blenderPath, c4dPath] = process.argv.slice(2);
if (!blenderPath || !c4dPath) {
  throw new Error("Usage: compare_motion_pose_signatures.mjs blender.json c4d.json");
}

const blender = JSON.parse(fs.readFileSync(blenderPath, "utf8"));
const c4d = JSON.parse(fs.readFileSync(c4dPath, "utf8"));

function stats(records) {
  const dimensions = records[0].signature.length;
  const means = Array(dimensions).fill(0);
  for (const record of records) {
    record.signature.forEach((value, index) => {
      means[index] += value / records.length;
    });
  }
  const standardDeviations = Array(dimensions).fill(0);
  for (const record of records) {
    record.signature.forEach((value, index) => {
      standardDeviations[index] +=
        ((value - means[index]) ** 2) / records.length;
    });
  }
  return {
    means,
    standardDeviations: standardDeviations.map((value) =>
      Math.max(Math.sqrt(value), 1e-6),
    ),
  };
}

function normalize(records) {
  const { means, standardDeviations } = stats(records);
  return records.map((record) => ({
    frame: record.frame,
    signature: record.signature.map(
      (value, index) => (value - means[index]) / standardDeviations[index],
    ),
  }));
}

function squaredDistance(left, right) {
  return (
    left.reduce(
      (sum, value, index) => sum + (value - right[index]) ** 2,
      0,
    ) / left.length
  );
}

const blenderNormalized = normalize(blender.records);
const c4dNormalized = normalize(c4d.records);
const blenderByFrame = new Map(
  blenderNormalized.map((record) => [record.frame, record]),
);

let best = null;
for (let scale = 0.8; scale <= 1.8; scale += 0.0025) {
  for (let offset = -80; offset <= 80; offset += 1) {
    let error = 0;
    let count = 0;
    for (const c4dRecord of c4dNormalized) {
      const blenderFrame = Math.round(offset + scale * c4dRecord.frame);
      const blenderRecord = blenderByFrame.get(blenderFrame);
      if (!blenderRecord) continue;
      error += squaredDistance(
        blenderRecord.signature,
        c4dRecord.signature,
      );
      count += 1;
    }
    if (count < c4dNormalized.length * 0.7) continue;
    const rms = Math.sqrt(error / count);
    if (!best || rms < best.rms) {
      best = { scale, offset, rms, count };
    }
  }
}

const representativeBlenderFrame = 170;
let closestC4d = null;
const representative = blenderNormalized.find(
  (record) => record.frame === representativeBlenderFrame,
);
for (const record of c4dNormalized) {
  const distance = Math.sqrt(
    squaredDistance(representative.signature, record.signature),
  );
  if (!closestC4d || distance < closestC4d.distance) {
    closestC4d = { frame: record.frame, distance };
  }
}

const c4dRawByFrame = new Map(c4d.records.map((record) => [record.frame, record]));
let alignedSquaredError = 0;
let alignedValueCount = 0;
let alignedMaxAbsError = 0;
for (const blenderRecord of blender.records) {
  const c4dRecord = c4dRawByFrame.get(blenderRecord.frame);
  if (!c4dRecord) continue;
  blenderRecord.signature.forEach((value, index) => {
    const difference = value - c4dRecord.signature[index];
    alignedSquaredError += difference ** 2;
    alignedValueCount += 1;
    alignedMaxAbsError = Math.max(alignedMaxAbsError, Math.abs(difference));
  });
}

console.log(
  JSON.stringify(
    {
      blenderSource: blender.source,
      c4dSource: c4d.source,
      bestLinearMapping: {
        blenderFrame:
          "round(offset + scale * c4dFrame)",
        ...best,
      },
      representativeBlenderFrame,
      mappedC4dFrame: best
        ? Math.round((representativeBlenderFrame - best.offset) / best.scale)
        : null,
      closestC4dFrameByPose: closestC4d,
      sameFrameRawError: {
        rms: Math.sqrt(alignedSquaredError / Math.max(alignedValueCount, 1)),
        maxAbs: alignedMaxAbsError,
        valueCount: alignedValueCount,
      },
    },
    null,
    2,
  ),
);
