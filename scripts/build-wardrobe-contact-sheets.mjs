import fs from "node:fs/promises";
import path from "node:path";
import sharp from "sharp";

const sourceDirectory = path.resolve(
  "public/archive/objects/sources/wardrobe",
);
const outputDirectory = path.resolve("tmp/wardrobe-contact-sheets");
const tileSize = 360;
const labelHeight = 44;
const columns = 4;
const rows = 3;
const perSheet = columns * rows;

const files = (await fs.readdir(sourceDirectory))
  .filter((file) => /\.(jpe?g|png|webp)$/i.test(file))
  .sort((left, right) => left.localeCompare(right));

await fs.mkdir(outputDirectory, { recursive: true });

for (let offset = 0; offset < files.length; offset += perSheet) {
  const sheetFiles = files.slice(offset, offset + perSheet);
  const composites = [];

  for (const [index, file] of sheetFiles.entries()) {
    const image = await sharp(path.join(sourceDirectory, file))
      .rotate()
      .resize(tileSize, tileSize - labelHeight, {
        fit: "contain",
        background: "#151515",
      })
      .jpeg({ quality: 88 })
      .toBuffer();
    const label = Buffer.from(
      `<svg width="${tileSize}" height="${labelHeight}">
        <rect width="100%" height="100%" fill="#050505"/>
        <text x="14" y="29" fill="#ffffff" font-family="Arial, sans-serif" font-size="18">${file.replace(
          /&/g,
          "&amp;",
        )}</text>
      </svg>`,
    );
    const column = index % columns;
    const row = Math.floor(index / columns);
    composites.push({
      input: image,
      left: column * tileSize,
      top: row * tileSize,
    });
    composites.push({
      input: label,
      left: column * tileSize,
      top: row * tileSize + tileSize - labelHeight,
    });
  }

  const sheetNumber = Math.floor(offset / perSheet) + 1;
  await sharp({
    create: {
      width: columns * tileSize,
      height: rows * tileSize,
      channels: 3,
      background: "#151515",
    },
  })
    .composite(composites)
    .jpeg({ quality: 90 })
    .toFile(
      path.join(
        outputDirectory,
        `wardrobe-contact-${String(sheetNumber).padStart(2, "0")}.jpg`,
      ),
    );
}

console.log(
  `Created ${Math.ceil(files.length / perSheet)} sheets for ${files.length} references.`,
);
