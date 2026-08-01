#!/usr/bin/env node

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";

const root = "/Users/alphaone/Documents/Code/paracosm-provenance";
const runPath = path.join(
  root,
  "data/wardrobe-static-cloth-proof-batch-20260728.json",
);
const outputDirectory = path.join(
  root,
  "public/archive/objects/3d/simulations/proof-review",
);
const run = JSON.parse(await readFile(runPath, "utf8"));
const groups = new Map();

for (const entry of run.objects) {
  if (entry.status !== "succeeded") continue;
  if (!groups.has(entry.materialClass)) groups.set(entry.materialClass, []);
  groups.get(entry.materialClass).push(entry);
}

await mkdir(outputDirectory, { recursive: true });

function escapeXml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

async function cardFor(entry) {
  const directory = path.join(
    root,
    "public/archive/objects/3d/simulations",
    entry.objectId,
  );
  const stem = `${entry.objectId}-cloth-static-proof-v1`;
  const [medium, closeup] = await Promise.all([
    sharp(path.join(directory, `${stem}-final.png`))
      .resize(340, 340, { fit: "contain", background: "#f2f2f0" })
      .png()
      .toBuffer(),
    sharp(path.join(directory, `${stem}-closeup.png`))
      .resize(340, 340, { fit: "contain", background: "#f2f2f0" })
      .png()
      .toBuffer(),
  ]);
  const label = Buffer.from(
    `<svg width="700" height="40" xmlns="http://www.w3.org/2000/svg">
      <rect width="700" height="40" fill="#ffffff"/>
      <text x="10" y="17" font-family="Arial, sans-serif" font-size="13" font-weight="700" fill="#27333e">${escapeXml(entry.objectId)}</text>
      <text x="10" y="33" font-family="Arial, sans-serif" font-size="10" fill="#737b80">MEDIUM</text>
      <text x="360" y="33" font-family="Arial, sans-serif" font-size="10" fill="#737b80">CLOSEUP</text>
    </svg>`,
  );
  return sharp({
    create: {
      width: 700,
      height: 390,
      channels: 4,
      background: "#ffffff",
    },
  })
    .composite([
      { input: label, left: 0, top: 0 },
      { input: medium, left: 10, top: 40 },
      { input: closeup, left: 350, top: 40 },
    ])
    .png()
    .toBuffer();
}

const manifest = {
  schemaVersion: 1,
  createdAt: new Date().toISOString(),
  sheets: [],
};

for (const [materialClass, entries] of groups) {
  const cards = await Promise.all(entries.map(cardFor));
  const columns = Math.min(2, cards.length);
  const rows = Math.ceil(cards.length / columns);
  const composites = cards.map((input, index) => ({
    input,
    left: (index % columns) * 700,
    top: Math.floor(index / columns) * 390,
  }));
  const outputPath = path.join(
    outputDirectory,
    `${materialClass}-proof-review.png`,
  );
  await sharp({
    create: {
      width: columns * 700,
      height: rows * 390,
      channels: 4,
      background: "#e9e9e6",
    },
  })
    .composite(composites)
    .png()
    .toFile(outputPath);
  manifest.sheets.push({
    materialClass,
    objectCount: entries.length,
    objects: entries.map((entry) => entry.objectId),
    image: `/${path.relative(path.join(root, "public"), outputPath)}`,
  });
}

await writeFile(
  path.join(outputDirectory, "review-sheets.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
);

console.log(
  JSON.stringify(
    {
      sheetCount: manifest.sheets.length,
      objectCount: manifest.sheets.reduce(
        (sum, sheet) => sum + sheet.objectCount,
        0,
      ),
    },
    null,
    2,
  ),
);
