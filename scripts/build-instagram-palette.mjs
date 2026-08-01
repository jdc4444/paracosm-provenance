import { readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceDirectory = path.join(
  root,
  "public/archive/objects/sources/wardrobe",
);
const outputPath = path.join(root, "data/instagram-palette.json");
const sampleSize = 56;
const clusterCount = 20;

const referenceNames = [
  ["Stage Black", "#09090b", "ink"],
  ["Black Cherry", "#201216", "ink"],
  ["Oxblood Shadow", "#40181e", "red"],
  ["Oxblood", "#74222a", "red"],
  ["Lacquer Red", "#b82a32", "red"],
  ["Flame Orange", "#da4c22", "red"],
  ["Copper", "#a95536", "copper"],
  ["Rust", "#8b422e", "copper"],
  ["Peach", "#d28d6c", "copper"],
  ["Dusty Taupe", "#8c7770", "copper"],
  ["Powder Cream", "#e6d6c7", "cream"],
  ["Porcelain", "#eeeae5", "cream"],
  ["Charcoal", "#39383b", "smoke"],
  ["Smoke", "#6a686a", "smoke"],
  ["Silver", "#aaa9ab", "smoke"],
  ["Dusty Pink", "#c48aa7", "mauve"],
  ["Mulberry", "#8c3f60", "mauve"],
  ["Aubergine", "#56344f", "mauve"],
  ["Electric Violet", "#5548b8", "violet"],
  ["Lilac", "#b8a5d2", "violet"],
  ["Cobalt", "#16499d", "blue"],
  ["Electric Blue", "#1769bc", "blue"],
  ["Midnight Blue", "#142856", "blue"],
  ["Petrol Blue", "#244c5d", "teal"],
  ["Icy Teal", "#62aeb7", "teal"],
  ["Ice", "#d9eef1", "teal"],
  ["Moss", "#536c48", "moss"],
  ["Olive", "#807843", "moss"],
  ["Sage", "#bfd3b8", "moss"],
  ["Antique Gold", "#bd993b", "gold"],
  ["Paper Gold", "#e7d27a", "gold"],
  ["Dark Olive", "#484728", "gold"],
];

function srgbChannelToLinear(value) {
  const channel = value / 255;
  return channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4;
}

function linearChannelToSrgb(value) {
  const channel =
    value <= 0.0031308
      ? 12.92 * value
      : 1.055 * value ** (1 / 2.4) - 0.055;
  return Math.round(Math.max(0, Math.min(1, channel)) * 255);
}

function rgbToOklab(red, green, blue) {
  const r = srgbChannelToLinear(red);
  const g = srgbChannelToLinear(green);
  const b = srgbChannelToLinear(blue);
  const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
  const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
  const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
  const lRoot = Math.cbrt(l);
  const mRoot = Math.cbrt(m);
  const sRoot = Math.cbrt(s);
  return [
    0.2104542553 * lRoot + 0.793617785 * mRoot - 0.0040720468 * sRoot,
    1.9779984951 * lRoot - 2.428592205 * mRoot + 0.4505937099 * sRoot,
    0.0259040371 * lRoot + 0.7827717662 * mRoot - 0.808675766 * sRoot,
  ];
}

function oklabToRgb([lightness, a, b]) {
  const lRoot = lightness + 0.3963377774 * a + 0.2158037573 * b;
  const mRoot = lightness - 0.1055613458 * a - 0.0638541728 * b;
  const sRoot = lightness - 0.0894841775 * a - 1.291485548 * b;
  const l = lRoot ** 3;
  const m = mRoot ** 3;
  const s = sRoot ** 3;
  return [
    linearChannelToSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    linearChannelToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    linearChannelToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

function hexToRgb(hex) {
  const value = Number.parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

function rgbToHex([red, green, blue]) {
  return `#${[red, green, blue]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("")}`;
}

function rgbToHsl([red, green, blue]) {
  const r = red / 255;
  const g = green / 255;
  const b = blue / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const lightness = (max + min) / 2;
  const delta = max - min;
  if (delta === 0) return [0, 0, lightness];
  const saturation =
    delta / (1 - Math.abs(2 * lightness - 1));
  let hue;
  if (max === r) hue = 60 * (((g - b) / delta) % 6);
  else if (max === g) hue = 60 * ((b - r) / delta + 2);
  else hue = 60 * ((r - g) / delta + 4);
  if (hue < 0) hue += 360;
  return [hue, saturation, lightness];
}

function distanceSquared(first, second) {
  return (
    (first[0] - second[0]) ** 2 +
    (first[1] - second[1]) ** 2 +
    (first[2] - second[2]) ** 2
  );
}

function familyForColor(rgb) {
  const [hue, saturation, lightness] = rgbToHsl(rgb);
  if (lightness < 0.13) return "ink";
  if (lightness > 0.84 && saturation < 0.22) return "cream";
  if (saturation < 0.13) return "smoke";
  if (hue < 18 || hue >= 345) return "red";
  if (hue < 48) return "copper";
  if (hue < 82) return "gold";
  if (hue < 165) return "moss";
  if (hue < 200) return "teal";
  if (hue < 255) return "blue";
  if (hue < 295) return "violet";
  if (hue < 345) return "mauve";
  return "red";
}

function nearestReferenceName(lab, family) {
  return referenceNames
    .filter(([, , referenceFamily]) => referenceFamily === family)
    .map(([name, hex]) => ({
      name,
      distance: distanceSquared(lab, rgbToOklab(...hexToRgb(hex))),
    }))
    .sort((first, second) => first.distance - second.distance)[0].name;
}

function roundShare(value) {
  return Number((value * 100).toFixed(1));
}

function clusterLabSamples(inputSamples, requestedCount, iterations = 20) {
  if (inputSamples.length === 0) return [];
  const centerCount = Math.min(requestedCount, inputSamples.length);
  const centers = [];
  const mean = inputSamples
    .reduce(
      (sum, sample) => [
        sum[0] + sample[0],
        sum[1] + sample[1],
        sum[2] + sample[2],
      ],
      [0, 0, 0],
    )
    .map((value) => value / inputSamples.length);
  centers.push(mean);

  while (centers.length < centerCount) {
    let farthest = inputSamples[0];
    let farthestDistance = -1;
    for (const sample of inputSamples) {
      const nearestDistance = Math.min(
        ...centers.map((center) => distanceSquared(sample, center)),
      );
      const weightedDistance =
        nearestDistance * (0.72 + sample[0] * 0.28);
      if (weightedDistance > farthestDistance) {
        farthestDistance = weightedDistance;
        farthest = sample;
      }
    }
    centers.push([...farthest]);
  }

  const assignments = new Uint8Array(inputSamples.length);
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const sums = Array.from({ length: centerCount }, () => [0, 0, 0, 0]);
    for (let index = 0; index < inputSamples.length; index += 1) {
      const sample = inputSamples[index];
      let selected = 0;
      let selectedDistance = Number.POSITIVE_INFINITY;
      for (
        let centerIndex = 0;
        centerIndex < centers.length;
        centerIndex += 1
      ) {
        const distance = distanceSquared(sample, centers[centerIndex]);
        if (distance < selectedDistance) {
          selectedDistance = distance;
          selected = centerIndex;
        }
      }
      assignments[index] = selected;
      sums[selected][0] += sample[0];
      sums[selected][1] += sample[1];
      sums[selected][2] += sample[2];
      sums[selected][3] += 1;
    }
    for (let index = 0; index < centers.length; index += 1) {
      if (sums[index][3] === 0) continue;
      centers[index] = [
        sums[index][0] / sums[index][3],
        sums[index][1] / sums[index][3],
        sums[index][2] / sums[index][3],
      ];
    }
  }

  const counts = Array.from({ length: centerCount }, () => 0);
  for (const assignment of assignments) counts[assignment] += 1;
  return centers
    .map((lab, index) => ({ lab, count: counts[index] }))
    .sort((first, second) => second.count - first.count);
}

const fileNames = (await readdir(sourceDirectory))
  .filter((fileName) => fileName.toLowerCase().endsWith(".jpg"))
  .sort();
const samples = [];

for (const fileName of fileNames) {
  const { data, info } = await sharp(path.join(sourceDirectory, fileName))
    .rotate()
    .resize(sampleSize, sampleSize, {
      fit: "cover",
      position: "attention",
    })
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  for (let offset = 0; offset < data.length; offset += info.channels) {
    samples.push(rgbToOklab(data[offset], data[offset + 1], data[offset + 2]));
  }
}

const colors = clusterLabSamples(samples, clusterCount, 24)
  .map(({ lab, count }) => {
    const rgb = oklabToRgb(lab);
    const [hue, saturation, lightness] = rgbToHsl(rgb);
    const family = familyForColor(rgb);
    return {
      name: nearestReferenceName(lab, family),
      hex: rgbToHex(rgb),
      family,
      share: roundShare(count / samples.length),
      hue: Math.round(hue),
      saturation: Math.round(saturation * 100),
      lightness: Math.round(lightness * 100),
    };
  })
  .sort((first, second) => second.share - first.share)
  .map((color, index) => ({
    id: `tone-${String(index + 1).padStart(2, "0")}`,
    ...color,
  }));

const familyMeta = [
  ["ink", "Ink", "Black stage space, dark wardrobe, and near-black framing."],
  ["red", "Oxblood + Red", "The central identity: lacquer, wine, cherry, and crimson."],
  ["copper", "Copper + Rust", "Hair, skin warmth, amber light, and burnt-orange styling."],
  ["gold", "Gold + Ochre", "Poster stock, theatrical light, brass, and yellow-green accents."],
  ["moss", "Moss + Olive", "Garden greens, velvet olive, and muted natural backdrops."],
  ["teal", "Teal", "Cool cosmetic highlights and green-blue stage lighting."],
  ["blue", "Blue", "Cobalt stage light, midnight fabrics, and electric screen glow."],
  ["violet", "Violet", "Blue-violet lighting, lilac fabric, and ultraviolet accents."],
  ["mauve", "Mauve + Pink", "Dusty pink, mulberry, blush, and soft-magenta details."],
  ["smoke", "Smoke", "Concrete gray, charcoal, silver, and desaturated transition tones."],
  ["cream", "Cream + Porcelain", "Paper, lace, white garments, and warm highlight space."],
];

const familySamples = new Map(
  familyMeta.map(([id]) => [id, []]),
);
for (const sample of samples) {
  familySamples.get(familyForColor(oklabToRgb(sample))).push(sample);
}

const families = familyMeta
  .map(([id, name, description]) => {
    const samplesForFamily = familySamples.get(id);
    const familyShare = samplesForFamily.length / samples.length;
    const familyColors = clusterLabSamples(samplesForFamily, 3, 18).map(
      ({ lab, count }, index) => {
        const rgb = oklabToRgb(lab);
        return {
          id: `${id}-${index + 1}`,
          name: nearestReferenceName(lab, id),
          hex: rgbToHex(rgb),
          share: roundShare(count / samplesForFamily.length),
        };
      },
    );
    return {
      id,
      name,
      description,
      share: roundShare(familyShare),
      colors: familyColors,
    };
  })
  .filter((family) => family.share >= 0.1)
  .sort((first, second) => second.share - first.share);

const chromaticFamilies = families.filter(
  (family) => !["ink", "smoke", "cream"].includes(family.id),
);
const chromaticTotal = chromaticFamilies.reduce(
  (sum, family) => sum + family.share,
  0,
);
const hueFamilies = chromaticFamilies
  .map((family) => ({
    id: family.id,
    name: family.name,
    share: Number(((family.share / chromaticTotal) * 100).toFixed(1)),
    colors: family.colors.map((color) => color.hex),
  }))
  .sort((first, second) => second.share - first.share);

const featuredSourceFiles = [
  "instagram-DZgcxu_GuHT-01.jpg",
  "instagram-DV6Gy_RlD6n-01.jpg",
  "instagram-DYfcoqvFcBk-02.jpg",
  "instagram-DU3rvJnkqc1-01.jpg",
  "instagram-DancEOBld60-01.jpg",
  "instagram-DVgp-wgiFZZ-01.jpg",
  "instagram-DX8CFhugOPd-02.jpg",
  "instagram-DWZpnLOkqG0-02.jpg",
];

const manifest = {
  schemaVersion: 1,
  generatedAt: "2026-07-27",
  account: "the.absolutely",
  auditRange: {
    from: "2025-07-27",
    to: "2026-07-27",
  },
  postsReviewed: 45,
  postsWithSavedStills: 36,
  sourceImageCount: fileNames.length,
  methodology:
    "Each archived still contributes an equal 56 × 56 attention crop. Pixels are clustered in OKLab space, then grouped into editorial hue families. Shares are rounded and may not sum to exactly 100.",
  mainColors: colors.slice(0, 16),
  families,
  hueFamilies,
  featuredSourceFiles,
};

await writeFile(outputPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Wrote ${path.relative(root, outputPath)} from ${fileNames.length} source stills.`);
