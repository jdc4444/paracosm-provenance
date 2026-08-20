import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function text(path) {
  return readFile(new URL(path, import.meta.url), "utf8");
}

async function json(path) {
  return JSON.parse(await text(path));
}

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the Paracosm shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>Paracosm<\/title>/i);
  assert.match(html, />PARACOSM</);
  assert.match(html, /Reading the evidence archive/);
  assert.match(html, /provenance-atlas-[^"]+\.js/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape/);
});

test("Palette leads with the ANIMATION shades and retains the archive range", async () => {
  const [basePalette, deckPalette, paletteSource] = await Promise.all([
    json("../data/instagram-palette.json"),
    json("../data/animation-deck-palette.json"),
    text("../app/instagram-palette.tsx"),
  ]);

  assert.equal(deckPalette.sourceDeck.endsWith("/ANIMATION.key"), true);
  assert.equal(deckPalette.slideCount, 18);
  assert.equal(deckPalette.sampledPixels, 18 * 320 * 180);
  assert.equal(deckPalette.addedShades.length, 8);
  assert.equal(
    new Set(deckPalette.addedShades.map((shade) => shade.hex)).size,
    deckPalette.addedShades.length,
  );
  assert.deepEqual(
    deckPalette.addedShades.map((shade) => shade.hex),
    [
      "#7f0d02",
      "#da6001",
      "#f1b34e",
      "#f4e495",
      "#b48175",
      "#0e2546",
      "#6e1528",
      "#5b7d77",
    ],
  );
  assert.equal(basePalette.schemaVersion, 1);
  assert.equal(
    basePalette.mainColors.reduce((sum, color) => sum + color.share, 0),
    92.5,
  );
  assert.match(paletteSource, /Storybook warmth leads/);
  assert.match(paletteSource, /every measured archive color/);
  assert.doesNotMatch(paletteSource, /palette-version-tabs/);
  assert.doesNotMatch(paletteSource, /useState/);
  assert.doesNotMatch(paletteSource, /\bV1\b/);
  assert.doesNotMatch(paletteSource, /\bV2\b/);
  assert.doesNotMatch(paletteSource, /V3/);
});

test("Avatar guide uses curated face references and excludes rejected diagnostics", async () => {
  const [guide, guideSource] = await Promise.all([
    json("../data/abby-avatar-guide.json"),
    text("../app/avatar-guide.tsx"),
  ]);
  const renderIds = guide.renders.map((render) => render.id);

  assert.equal(guide.summary.renderCount, guide.renders.length);
  assert.ok(!renderIds.includes("blender-front"));
  assert.ok(!renderIds.includes("blender-three-quarter"));
  assert.ok(!renderIds.includes("c4d-front"));
  assert.ok(renderIds.includes("approved-front-closeup-20260729"));
  assert.ok(renderIds.includes("final-avatar-deck-slide-04"));
  assert.ok(renderIds.includes("final-avatar-deck-slide-06"));
  assert.ok(
    guide.renders
      .filter((render) => render.id.startsWith("final-avatar-deck-slide-"))
      .every(
        (render) =>
          render.sourcePath.endsWith("Absolutely 3D - Final Avatar.pptx") &&
          render.sourceUrl.includes("docs.google.com/presentation/"),
      ),
  );
  await Promise.all(
    guide.renders.map((render) =>
      access(new URL(`../public${render.image}`, import.meta.url)),
    ),
  );
  assert.match(guideSource, /CURATED FACE SOURCES/);
  assert.match(guideSource, /Open deck slide|sourceUrlLabel/);
  assert.doesNotMatch(guideSource, /4K diagnostics retain real geometry/);
});

test("the Mockup view keeps Blue Steel Pass 01 separate from canonical thumbnails", async () => {
  const [
    manifest,
    state,
    feedback,
    houseBloomAllocation,
    nthWardrobePlan,
    objectInventory,
    atlasSource,
    gallerySource,
    styles,
  ] = await Promise.all([
    json("../data/mockup-passes.json"),
    json("../public/data/state.json"),
    json("../data/feedback.json"),
    json("../data/house-bloom-object-allocation.json"),
    json("../data/nth-wardrobe-mockup-plan.json"),
    json("../data/object-inventory.json"),
    text("../app/provenance-atlas.tsx"),
    text("../app/mockup-gallery.tsx"),
    text("../app/globals.css"),
  ]);
  const blueSteel = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-01",
  );
  const freezerCarnival = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-02",
  );
  const subtleCarnival = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-03",
  );
  const wideCarnival = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-04",
  );
  const entranceCarnival = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-05",
  );
  const centeredCarnival = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-06",
  );
  const breadHouseWindow = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-07",
  );
  const rearBreadHouseWindow = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-08",
  );
  const blueSteelObjectContinuity = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-09",
  );
  const blueSteelCartonFinishRevision = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-10",
  );
  const blueSteelCleanTubRevision = manifest.passes.find(
    (pass) => pass.id === "blue-steel-th-pass-11",
  );
  const blueSteelPasses = manifest.passes.filter(
    (pass) => pass.styleId === "blue-steel",
  );
  const houseBloom = manifest.passes.find(
    (pass) => pass.id === "house-bloom-pass-01",
  );
  const houseBloomPasses = manifest.passes.filter(
    (pass) => pass.styleId === "house-bloom",
  );
  const houseBloomChronologyRevision = manifest.passes.find(
    (pass) => pass.id === "house-bloom-pass-03",
  );
  const houseBloomLatest = manifest.passes.find(
    (pass) => pass.id === "house-bloom-pass-08",
  );
  const nthWardrobe = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-01",
  );
  const nthWardrobeRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-02",
  );
  const nthWardrobeActionRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-03",
  );
  const nthWardrobeCanonicalActionRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-04",
  );
  const nthWardrobeGarmentEndsRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-15",
  );
  const nthWardrobeOrangeSweaterRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-16",
  );
  const nthWardrobeCanonicalScaleRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-17",
  );
  const nthWardrobeSubtleHorizonRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-18",
  );
  const nthWardrobeWhisperedHorizonRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-19",
  );
  const nthWardrobeMessyPileRevisions = [20, 21, 22].map((passNumber) =>
    manifest.passes.find(
      (pass) => pass.id === `nth-wardrobe-pass-${passNumber}`,
    ),
  );
  const nthWardrobeSourceMatchRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-23",
  );
  const nthWardrobeReadableSourceMatchRevision = manifest.passes.find(
    (pass) => pass.id === "nth-wardrobe-pass-24",
  );
  const nthWardrobePasses = manifest.passes.filter(
    (pass) => pass.styleId === "nth-wardrobe",
  );
  const thCuts = state.cuts.filter((cut) => cut.sectionCode === "TH");
  const blueSteelCuts = thCuts.filter((cut) => cut.id !== "CUT-047");

  assert.equal(manifest.schemaVersion, 2);
  assert.equal(blueSteel?.title, "Blue Steel");
  assert.equal(blueSteel?.passNumber, 1);
  assert.equal(blueSteel?.chapter, "TH");
  assert.equal(blueSteel?.scrubMode, "original-shot");
  assert.equal(blueSteel?.items.length, 15);
  assert.equal(thCuts.length, 16);
  assert.deepEqual(
    blueSteel?.items.map((item) => item.cutId),
    blueSteelCuts.map((cut) => cut.id),
  );
  assert.ok(!blueSteel?.items.some((item) => item.cutId === "CUT-047"));
  assert.ok(
    thCuts.every(
      (cut) =>
        typeof cut.thumbnail === "string" &&
        !cut.thumbnail.includes("/blue-steel/"),
    ),
  );
  await Promise.all(
    blueSteel.items.map((item) =>
      access(new URL(`../public${item.image}`, import.meta.url)),
    ),
  );
  assert.equal(freezerCarnival?.styleId, "blue-steel");
  assert.equal(freezerCarnival?.title, "Blue Steel r2");
  assert.equal(freezerCarnival?.passNumber, 2);
  assert.equal(freezerCarnival?.scrubMode, "original-shot");
  assert.deepEqual(
    freezerCarnival?.items.map((item) => item.cutId),
    ["CUT-033"],
  );
  await Promise.all(
    freezerCarnival.items.map((item) =>
      access(new URL(`../public${item.image}`, import.meta.url)),
    ),
  );
  assert.equal(subtleCarnival?.styleId, "blue-steel");
  assert.equal(subtleCarnival?.title, "Blue Steel r3");
  assert.equal(subtleCarnival?.passNumber, 3);
  assert.deepEqual(
    subtleCarnival?.items.map((item) => item.cutId),
    ["CUT-032", "CUT-034", "CUT-035", "CUT-036"],
  );
  assert.ok(!subtleCarnival?.items.some((item) => item.cutId === "CUT-033"));
  await Promise.all(
    subtleCarnival.items.map((item) =>
      access(new URL(`../public${item.image}`, import.meta.url)),
    ),
  );
  assert.equal(wideCarnival?.styleId, "blue-steel");
  assert.equal(wideCarnival?.title, "Blue Steel r4");
  assert.equal(wideCarnival?.passNumber, 4);
  assert.deepEqual(wideCarnival?.items.map((item) => item.cutId), ["CUT-036"]);
  assert.notEqual(
    wideCarnival?.items[0]?.image,
    subtleCarnival?.items.find((item) => item.cutId === "CUT-035")?.image,
  );
  await access(new URL(`../public${wideCarnival.items[0].image}`, import.meta.url));
  assert.equal(entranceCarnival?.styleId, "blue-steel");
  assert.equal(entranceCarnival?.title, "Blue Steel r5");
  assert.equal(entranceCarnival?.passNumber, 5);
  assert.deepEqual(entranceCarnival?.items.map((item) => item.cutId), [
    "CUT-035",
  ]);
  assert.notEqual(
    entranceCarnival?.items[0]?.image,
    wideCarnival?.items[0]?.image,
  );
  await access(
    new URL(`../public${entranceCarnival.items[0].image}`, import.meta.url),
  );
  assert.equal(centeredCarnival?.styleId, "blue-steel");
  assert.equal(centeredCarnival?.title, "Blue Steel r6");
  assert.equal(centeredCarnival?.passNumber, 6);
  assert.deepEqual(centeredCarnival?.items.map((item) => item.cutId), [
    "CUT-036",
  ]);
  assert.notEqual(
    centeredCarnival?.items[0]?.image,
    wideCarnival?.items[0]?.image,
  );
  await access(
    new URL(`../public${centeredCarnival.items[0].image}`, import.meta.url),
  );
  assert.equal(breadHouseWindow?.styleId, "blue-steel");
  assert.equal(breadHouseWindow?.title, "Blue Steel r7");
  assert.equal(breadHouseWindow?.passNumber, 7);
  assert.equal(breadHouseWindow?.chapter, "TH");
  assert.equal(breadHouseWindow?.scrubMode, "original-shot");
  assert.deepEqual(
    breadHouseWindow?.items.map((item) => item.cutId),
    ["CUT-035"],
  );
  assert.equal(
    breadHouseWindow?.items[0]?.image,
    "/archive/blue-steel/versions/CUT-035-r4-ots-bread-house.png",
  );
  assert.equal(
    breadHouseWindow?.items[0]?.mockupName,
    "Discover The Bread House",
  );
  assert.match(
    breadHouseWindow?.items[0]?.mockupDescription,
    /Over Abby's snow-dusted shoulder/i,
  );
  assert.match(
    breadHouseWindow?.items[0]?.mockupDescription,
    /no bridge or walking action/i,
  );
  const blueSteelCut35Versions = blueSteelPasses.flatMap((pass) =>
    pass.items.filter((item) => item.cutId === "CUT-035"),
  );
  await access(
    new URL(`../public${breadHouseWindow.items[0].image}`, import.meta.url),
  );
  assert.equal(rearBreadHouseWindow?.styleId, "blue-steel");
  assert.equal(rearBreadHouseWindow?.title, "Blue Steel r8");
  assert.equal(rearBreadHouseWindow?.passNumber, 8);
  assert.equal(rearBreadHouseWindow?.chapter, "TH");
  assert.equal(rearBreadHouseWindow?.scrubMode, "original-shot");
  assert.deepEqual(
    rearBreadHouseWindow?.items.map((item) => item.cutId),
    ["CUT-035"],
  );
  assert.equal(
    rearBreadHouseWindow?.items[0]?.image,
    "/archive/blue-steel/versions/CUT-035-r5-rear-ots-bread-house.png",
  );
  assert.equal(
    rearBreadHouseWindow?.items[0]?.mockupName,
    "Discover The Bread House — Rear OTS",
  );
  assert.match(
    rearBreadHouseWindow?.items[0]?.mockupDescription,
    /almost directly behind Abby/i,
  );
  assert.match(
    rearBreadHouseWindow?.items[0]?.mockupDescription,
    /minimizing her profile/i,
  );
  const blueSteelPassNumbers = blueSteelPasses.map((pass) => pass.passNumber);
  assert.deepEqual(
    blueSteelPassNumbers,
    Array.from(
      { length: blueSteelPassNumbers.at(-1) || 0 },
      (_, index) => index + 1,
    ),
  );
  assert.ok(blueSteelPassNumbers.length >= 11);
  assert.equal(blueSteelCut35Versions.length, 5);
  assert.equal(
    new Set(blueSteelCut35Versions.map((item) => item.image)).size,
    5,
  );
  await access(
    new URL(`../public${rearBreadHouseWindow.items[0].image}`, import.meta.url),
  );
  assert.equal(blueSteelObjectContinuity?.styleId, "blue-steel");
  assert.equal(blueSteelObjectContinuity?.title, "Blue Steel r9");
  assert.equal(blueSteelObjectContinuity?.passNumber, 9);
  assert.equal(blueSteelObjectContinuity?.chapter, "TH");
  assert.equal(blueSteelObjectContinuity?.scrubMode, "original-shot");
  assert.deepEqual(
    blueSteelObjectContinuity?.items.map((item) => item.cutId),
    ["CUT-033", "CUT-034", "CUT-038"],
  );
  assert.equal(
    blueSteelObjectContinuity?.items[0]?.image,
    "/archive/blue-steel/versions/CUT-033-r3-finish-match.png",
  );
  assert.match(
    blueSteelObjectContinuity?.items[0]?.mockupDescription,
    /CUT-034, CUT-036, and CUT-038/i,
  );
  assert.equal(
    blueSteelObjectContinuity?.items[1]?.image,
    "/archive/blue-steel/versions/CUT-034-r3-ice-cream-shop.png",
  );
  assert.match(
    blueSteelObjectContinuity?.items[1]?.mockupDescription,
    /exact stepped ice-cream-shop model/i,
  );
  assert.equal(
    blueSteelObjectContinuity?.items[2]?.image,
    "/archive/blue-steel/versions/CUT-038-r2-white-house-village.png",
  );
  assert.match(
    blueSteelObjectContinuity?.items[2]?.mockupDescription,
    /exact asymmetrical White House design/i,
  );
  const blueSteelCut33Versions = blueSteelPasses.flatMap((pass) =>
    pass.items.filter((item) => item.cutId === "CUT-033"),
  );
  const blueSteelCut34Versions = blueSteelPasses.flatMap((pass) =>
    pass.items.filter((item) => item.cutId === "CUT-034"),
  );
  const blueSteelCut38Versions = blueSteelPasses.flatMap((pass) =>
    pass.items.filter((item) => item.cutId === "CUT-038"),
  );
  assert.equal(blueSteelCut33Versions.length, 5);
  assert.equal(blueSteelCut34Versions.length, 3);
  assert.equal(blueSteelCut38Versions.length, 2);
  assert.equal(
    new Set(blueSteelCut33Versions.map((item) => item.image)).size,
    5,
  );
  assert.equal(
    new Set(blueSteelCut34Versions.map((item) => item.image)).size,
    3,
  );
  assert.equal(
    new Set(blueSteelCut38Versions.map((item) => item.image)).size,
    2,
  );
  await Promise.all(
    blueSteelObjectContinuity.items.map((item) =>
      access(new URL(`../public${item.image}`, import.meta.url)),
    ),
  );
  assert.equal(blueSteelCartonFinishRevision?.styleId, "blue-steel");
  assert.equal(blueSteelCartonFinishRevision?.title, "Blue Steel r10");
  assert.equal(blueSteelCartonFinishRevision?.passNumber, 10);
  assert.equal(blueSteelCartonFinishRevision?.chapter, "TH");
  assert.equal(blueSteelCartonFinishRevision?.scrubMode, "original-shot");
  assert.deepEqual(
    blueSteelCartonFinishRevision?.items.map((item) => item.cutId),
    ["CUT-033"],
  );
  assert.equal(
    blueSteelCartonFinishRevision?.items[0]?.image,
    "/archive/blue-steel/versions/CUT-033-r4-carton-cubes-finish-match.png",
  );
  assert.match(
    blueSteelCartonFinishRevision?.items[0]?.mockupDescription,
    /Mockup 2's open freezer-burned ice-cream carton/i,
  );
  assert.match(
    blueSteelCartonFinishRevision?.items[0]?.mockupDescription,
    /loose translucent ice cubes/i,
  );
  await access(
    new URL(
      `../public${blueSteelCartonFinishRevision.items[0].image}`,
      import.meta.url,
    ),
  );
  assert.equal(blueSteelCleanTubRevision?.styleId, "blue-steel");
  assert.equal(blueSteelCleanTubRevision?.title, "Blue Steel r11");
  assert.equal(blueSteelCleanTubRevision?.passNumber, 11);
  assert.equal(blueSteelCleanTubRevision?.chapter, "TH");
  assert.equal(blueSteelCleanTubRevision?.scrubMode, "original-shot");
  assert.deepEqual(
    blueSteelCleanTubRevision?.items.map((item) => item.cutId),
    ["CUT-033"],
  );
  assert.equal(
    blueSteelCleanTubRevision?.items[0]?.image,
    "/archive/blue-steel/versions/CUT-033-r5-clean-ice-cream-tub.png",
  );
  assert.match(
    blueSteelCleanTubRevision?.items[0]?.mockupDescription,
    /clean low rectangular lid/i,
  );
  assert.match(
    blueSteelCleanTubRevision?.items[0]?.mockupDescription,
    /tall folded flaps are gone/i,
  );
  await access(
    new URL(
      `../public${blueSteelCleanTubRevision.items[0].image}`,
      import.meta.url,
    ),
  );
  const drabPasses = manifest.passes.filter((pass) => pass.styleId === "drab");
  const drabItems = drabPasses.flatMap((pass) => pass.items);
  assert.deepEqual(
    drabPasses.map((pass) => pass.title),
    [
      "Drab r1",
      "Drab r2",
      "Drab r3",
      "Drab r4",
      "Drab r5",
      "Drab r6",
      "Drab r7",
    ],
  );
  assert.equal(drabItems.length, 24);
  const requiredDrabShotIds = new Set(
    feedback.notes
      .filter(
        (note) =>
          note.title === "Undecorate House" ||
          note.title === "Keep the room pre-transformation",
      )
      .flatMap((note) => note.shotIds),
  );
  const requiredDrabCutIds = state.cuts
    .filter((cut) => requiredDrabShotIds.has(cut.shotId))
    .map((cut) => cut.id);
  const completedDrabPass = drabPasses.find(
    (pass) => pass.id === "drab-pass-06",
  );
  const cut16DrabPass = drabPasses.find(
    (pass) => pass.id === "drab-pass-07",
  );
  assert.deepEqual(
    completedDrabPass?.items.map((item) => item.cutId),
    requiredDrabCutIds,
  );
  assert.deepEqual(cut16DrabPass?.items.map((item) => item.cutId), [
    "CUT-016",
  ]);
  assert.equal(
    cut16DrabPass?.items[0]?.sourceImage,
    "/archive/mockup-sources/CUT-016-selected-f1646.jpg",
  );
  assert.equal(cut16DrabPass?.items[0]?.sourceTime, 68.67277083333333);
  assert.ok(
    drabItems
      .filter((item) => item.cutId === "CUT-053")
      .every((item) => item.sourceFrame === "canonical"),
  );
  await Promise.all(
    drabItems.flatMap((item) => [
      access(new URL(`../public${item.image}`, import.meta.url)),
      ...(item.sourceImage
        ? [
            access(
              new URL(`../public${item.sourceImage}`, import.meta.url),
            ),
          ]
        : []),
    ]),
  );
  assert.equal(houseBloom?.styleId, "house-bloom");
  assert.equal(houseBloom?.title, "House Bloom");
  assert.equal(houseBloom?.passNumber, 1);
  assert.equal(houseBloom?.chapter, "IJDKYY");
  assert.match(houseBloom?.description, /daylight/i);
  assert.match(houseBloom?.description, /all 89 current non-wardrobe Objects/);
  assert.deepEqual(
    houseBloom?.items.map((item) => item.cutId),
    Array.from(
      { length: 13 },
      (_, index) => `CUT-${String(index + 75).padStart(3, "0")}`,
    ),
  );
  assert.ok(
    houseBloom?.items.every(
      (item) =>
        item.mockupName?.length > 0 &&
        item.mockupDescription?.length > 0,
    ),
  );
  assert.ok(
    houseBloom?.items.every((item) =>
      /day|sun|window light|airy|bright/i.test(item.mockupDescription),
    ),
  );
  const houseBloomCut77 = houseBloomChronologyRevision?.items.find(
    (item) => item.cutId === "CUT-077",
  );
  assert.equal(houseBloomCut77?.mockupName, "The Piano Wakes");
  assert.match(houseBloomCut77?.mockupDescription, /playing by itself/i);
  assert.match(houseBloomCut77?.mockupDescription, /top remains empty/i);
  assert.deepEqual(
    houseBloomPasses.map((pass) => pass.passNumber),
    [1, 2, 3, 4, 5, 6, 7, 8, 9],
  );
  const houseBloomCut82Versions = houseBloomPasses.flatMap((pass) =>
    pass.items.filter((item) => item.cutId === "CUT-082"),
  );
  assert.equal(houseBloomCut82Versions.length, 7);
  assert.equal(
    new Set(houseBloomCut82Versions.map((item) => item.image)).size,
    7,
  );
  const latestHouseBloomCut82 = houseBloomLatest?.items.find(
    (item) => item.cutId === "CUT-082",
  );
  assert.equal(
    latestHouseBloomCut82?.image,
    "/archive/house-bloom/versions/CUT-082-r7-blue-walls.png",
  );
  assert.equal(latestHouseBloomCut82?.sourceFrame, "first");
  assert.match(latestHouseBloomCut82?.mockupDescription, /Drab r4/i);
  assert.match(latestHouseBloomCut82?.mockupDescription, /pale dusty blue/i);
  const houseBloomCut85Versions = houseBloomPasses.flatMap((pass) =>
    pass.items.filter((item) => item.cutId === "CUT-085"),
  );
  assert.equal(houseBloomCut85Versions.length, 2);
  assert.equal(
    new Set(houseBloomCut85Versions.map((item) => item.image)).size,
    2,
  );
  const latestHouseBloomCut85 = manifest.passes
    .find((pass) => pass.id === "house-bloom-pass-09")
    ?.items.find((item) => item.cutId === "CUT-085");
  assert.equal(
    latestHouseBloomCut85?.image,
    "/archive/house-bloom/versions/CUT-085-r2-character-refine.png",
  );
  assert.match(latestHouseBloomCut85?.mockupDescription, /refined cloth/i);
  assert.match(latestHouseBloomCut85?.mockupDescription, /hand anatomy/i);
  assert.match(latestHouseBloomCut82?.mockupDescription, /CUT-079/i);
  assert.match(latestHouseBloomCut82?.mockupDescription, /white house/i);
  const currentNonWardrobeObjectIds = [
    ...objectInventory.objects.map((item) => item.id),
    ...objectInventory.generatedGroups
      .filter((group) => group.category !== "Wardrobe")
      .flatMap((group) => group.objects.map((item) => item.id)),
  ];
  const assignedHouseBloomObjectIds = houseBloomAllocation.shots.flatMap(
    (shot) => shot.objectIds,
  );
  assert.equal(houseBloomAllocation.objectCount, 89);
  assert.equal(assignedHouseBloomObjectIds.length, 89);
  assert.equal(new Set(assignedHouseBloomObjectIds).size, 89);
  assert.deepEqual(
    new Set(assignedHouseBloomObjectIds),
    new Set(currentNonWardrobeObjectIds),
  );
  assert.ok(
    houseBloomAllocation.shots.every(
      (shot) => shot.objectIds.length > 0,
    ),
  );
  assert.deepEqual(
    houseBloomAllocation.shots.find((shot) => shot.cutId === "CUT-077")
      ?.objectIds,
    ["piano"],
  );
  const houseBloomCut79ObjectIds = houseBloomAllocation.shots.find(
    (shot) => shot.cutId === "CUT-079",
  )?.objectIds;
  assert.deepEqual(houseBloomCut79ObjectIds, [
    "ice-cream-shop",
    "white-house",
    "cafe-model",
  ]);
  const houseBloomCut86ObjectIds = houseBloomAllocation.shots.find(
    (shot) => shot.cutId === "CUT-086",
  )?.objectIds;
  assert.equal(houseBloomCut86ObjectIds?.length, 22);
  assert.ok(houseBloomCut86ObjectIds?.includes("blue-oval-goblet"));
  assert.ok(houseBloomCut86ObjectIds?.includes("purple-cordial-glass"));
  assert.ok(
    !houseBloomAllocation.shots
      .find((shot) => shot.cutId === "CUT-082")
      ?.objectIds.includes("piano"),
  );
  assert.equal(houseBloomAllocation.continuityShots.length, 1);
  assert.equal(houseBloomAllocation.continuityShots[0].cutId, "CUT-087");
  assert.deepEqual(
    houseBloomAllocation.continuityShots[0].newObjectIds,
    [],
  );
  assert.ok(
    houseBloomAllocation.continuityShots[0].representativeObjectIds.every(
      (objectId) => assignedHouseBloomObjectIds.includes(objectId),
    ),
  );
  await Promise.all(
    houseBloomPasses.flatMap((pass) => pass.items).map((item) =>
      access(new URL(`../public${item.image}`, import.meta.url)),
    ),
  );
  assert.equal(nthWardrobe?.styleId, "nth-wardrobe");
  assert.equal(nthWardrobe?.title, "NTH Wardrobe");
  assert.equal(nthWardrobe?.passNumber, 1);
  assert.equal(nthWardrobe?.chapter, "NTH");
  assert.equal(nthWardrobe?.scrubMode, "original-shot");
  assert.deepEqual(
    nthWardrobe?.items.map((item) => item.cutId),
    Array.from(
      { length: 8 },
      (_, index) => `CUT-${String(index + 24).padStart(3, "0")}`,
    ),
  );
  assert.ok(
    nthWardrobe?.items.every(
      (item) =>
        item.sourceFrame === "canonical" &&
        item.mockupName?.length > 0 &&
        item.mockupDescription?.length > 0,
    ),
  );
  assert.match(nthWardrobe?.description, /Big Abby.*gray Drab top/i);
  assert.match(nthWardrobe?.description, /no IJDKYY Objects Wardrobe/i);
  assert.deepEqual(
    nthWardrobePlan.cuts,
    nthWardrobe.items.map((item) => item.cutId),
  );
  assert.equal(nthWardrobeRevision?.title, "NTH Wardrobe r2");
  assert.equal(nthWardrobeRevision?.passNumber, 2);
  assert.equal(nthWardrobeRevision?.chapter, "NTH");
  assert.equal(nthWardrobeRevision?.scrubMode, "original-shot");
  assert.deepEqual(
    nthWardrobePasses.map((pass) => pass.passNumber),
    [
      1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
      20, 21, 22, 23, 24,
    ],
  );
  assert.deepEqual(
    nthWardrobeRevision?.items.map((item) => item.cutId),
    ["CUT-022", "CUT-023", "CUT-024", "CUT-026", "CUT-031"],
  );
  assert.match(nthWardrobeRevision?.description, /clothes to the horizon/i);
  assert.match(nthWardrobeRevision?.description, /blue polka-dot blouse/i);
  assert.equal(nthWardrobeActionRevision?.title, "NTH Wardrobe r3");
  assert.equal(nthWardrobeActionRevision?.passNumber, 3);
  assert.equal(nthWardrobeActionRevision?.chapter, "NTH");
  assert.equal(nthWardrobeActionRevision?.scrubMode, "original-shot");
  assert.deepEqual(
    nthWardrobeActionRevision?.items.map((item) => item.cutId),
    ["CUT-028", "CUT-031"],
  );
  assert.equal(
    nthWardrobeActionRevision?.items[0]?.image,
    "/archive/nth-wardrobe/versions/CUT-028-r2-red-corset-fall.png",
  );
  assert.match(
    nthWardrobeActionRevision?.items[0]?.mockupDescription,
    /exact striped red corset top/i,
  );
  assert.equal(
    nthWardrobeActionRevision?.items[1]?.image,
    "/archive/nth-wardrobe/versions/CUT-031-r3-blue-polka-lens-wipe.png",
  );
  assert.match(
    nthWardrobeActionRevision?.items[1]?.mockupDescription,
    /flies face-first into the lens/i,
  );
  assert.match(
    nthWardrobeActionRevision?.items[1]?.mockupDescription,
    /almost the entire frame/i,
  );
  assert.equal(nthWardrobeCanonicalActionRevision?.title, "NTH Wardrobe r4");
  assert.equal(nthWardrobeCanonicalActionRevision?.passNumber, 4);
  assert.equal(nthWardrobeCanonicalActionRevision?.chapter, "NTH");
  assert.equal(
    nthWardrobeCanonicalActionRevision?.scrubMode,
    "original-shot",
  );
  assert.deepEqual(
    nthWardrobeCanonicalActionRevision?.items.map((item) => item.cutId),
    ["CUT-028", "CUT-031"],
  );
  assert.equal(
    nthWardrobeCanonicalActionRevision?.items[0]?.image,
    "/archive/nth-wardrobe/versions/CUT-028-r3-red-corset-side-up.png",
  );
  assert.match(
    nthWardrobeCanonicalActionRevision?.items[0]?.mockupDescription,
    /front facing upward/i,
  );
  assert.equal(
    nthWardrobeCanonicalActionRevision?.items[1]?.image,
    "/archive/nth-wardrobe/versions/CUT-031-r4-blue-polka-canonical-wipe.png",
  );
  assert.match(
    nthWardrobeCanonicalActionRevision?.items[1]?.mockupDescription,
    /canonical low composition/i,
  );
  assert.match(
    nthWardrobeCanonicalActionRevision?.items[1]?.mockupDescription,
    /Little Abby stands clearly on the burgundy heap/i,
  );
  assert.equal(nthWardrobeGarmentEndsRevision?.title, "NTH Wardrobe r15");
  assert.equal(nthWardrobeGarmentEndsRevision?.passNumber, 15);
  assert.equal(nthWardrobeGarmentEndsRevision?.chapter, "NTH");
  assert.equal(
    nthWardrobeGarmentEndsRevision?.scrubMode,
    "original-shot",
  );
  assert.deepEqual(
    nthWardrobeGarmentEndsRevision?.items.map((item) => item.cutId),
    ["CUT-023"],
  );
  assert.equal(
    nthWardrobeGarmentEndsRevision?.items[0]?.image,
    "/archive/nth-wardrobe/versions/CUT-023-r3-realistic-garment-ends.png",
  );
  assert.match(
    nthWardrobeGarmentEndsRevision?.items[0]?.mockupDescription,
    /ribbed cuffs/i,
  );
  assert.match(
    nthWardrobeGarmentEndsRevision?.items[0]?.mockupDescription,
    /separate every garment cleanly/i,
  );
  assert.equal(nthWardrobeOrangeSweaterRevision?.title, "NTH Wardrobe r16");
  assert.equal(nthWardrobeOrangeSweaterRevision?.passNumber, 16);
  assert.equal(nthWardrobeOrangeSweaterRevision?.chapter, "NTH");
  assert.equal(
    nthWardrobeOrangeSweaterRevision?.scrubMode,
    "original-shot",
  );
  assert.deepEqual(
    nthWardrobeOrangeSweaterRevision?.items.map((item) => item.cutId),
    ["CUT-023"],
  );
  assert.equal(
    nthWardrobeOrangeSweaterRevision?.items[0]?.image,
    "/archive/nth-wardrobe/versions/CUT-023-r4-orange-sweater-background-shoe.png",
  );
  assert.match(
    nthWardrobeOrangeSweaterRevision?.items[0]?.mockupDescription,
    /pumpkin and burnt orange/i,
  );
  assert.match(
    nthWardrobeOrangeSweaterRevision?.items[0]?.mockupDescription,
    /lies naturally on its side farther back/i,
  );
  assert.equal(nthWardrobeCanonicalScaleRevision?.title, "NTH Wardrobe r17");
  assert.equal(nthWardrobeCanonicalScaleRevision?.passNumber, 17);
  assert.equal(nthWardrobeCanonicalScaleRevision?.chapter, "NTH");
  assert.equal(
    nthWardrobeCanonicalScaleRevision?.scrubMode,
    "original-shot",
  );
  assert.deepEqual(
    nthWardrobeCanonicalScaleRevision?.items.map((item) => item.cutId),
    ["CUT-023"],
  );
  assert.equal(
    nthWardrobeCanonicalScaleRevision?.items[0]?.image,
    "/archive/nth-wardrobe/versions/CUT-023-r5-canonical-scale-sideways-shoe.png",
  );
  assert.match(
    nthWardrobeCanonicalScaleRevision?.items[0]?.mockupDescription,
    /lies on its outer side/i,
  );
  assert.match(
    nthWardrobeCanonicalScaleRevision?.items[0]?.mockupDescription,
    /canonical CUT-023 framing/i,
  );
  assert.equal(nthWardrobeSubtleHorizonRevision?.title, "NTH Wardrobe r18");
  assert.equal(nthWardrobeSubtleHorizonRevision?.passNumber, 18);
  assert.equal(nthWardrobeSubtleHorizonRevision?.chapter, "NTH");
  assert.equal(
    nthWardrobeSubtleHorizonRevision?.scrubMode,
    "original-shot",
  );
  assert.deepEqual(
    nthWardrobeSubtleHorizonRevision?.items.map((item) => item.cutId),
    ["CUT-026"],
  );
  assert.equal(
    nthWardrobeSubtleHorizonRevision?.items[0]?.image,
    "/archive/nth-wardrobe/versions/CUT-026-r5-subtle-sweater-horizon.png",
  );
  assert.match(
    nthWardrobeSubtleHorizonRevision?.items[0]?.mockupDescription,
    /Mockup 1 remains intact/i,
  );
  assert.match(
    nthWardrobeSubtleHorizonRevision?.items[0]?.mockupDescription,
    /rather than turning it into a still life/i,
  );
  assert.equal(
    nthWardrobeWhisperedHorizonRevision?.title,
    "NTH Wardrobe r19",
  );
  assert.equal(nthWardrobeWhisperedHorizonRevision?.passNumber, 19);
  assert.equal(nthWardrobeWhisperedHorizonRevision?.chapter, "NTH");
  assert.equal(
    nthWardrobeWhisperedHorizonRevision?.scrubMode,
    "original-shot",
  );
  assert.deepEqual(
    nthWardrobeWhisperedHorizonRevision?.items.map((item) => item.cutId),
    ["CUT-026"],
  );
  assert.equal(
    nthWardrobeWhisperedHorizonRevision?.items[0]?.image,
    "/archive/nth-wardrobe/versions/CUT-026-r6-whispered-knit-horizon.png",
  );
  assert.match(
    nthWardrobeWhisperedHorizonRevision?.items[0]?.mockupDescription,
    /original mountain silhouettes remain intact/i,
  );
  assert.match(
    nthWardrobeWhisperedHorizonRevision?.items[0]?.mockupDescription,
    /amber atmospheric blur/i,
  );
  assert.deepEqual(
    nthWardrobeMessyPileRevisions.map((pass) => pass?.passNumber),
    [20, 21, 22],
  );
  assert.ok(
    nthWardrobeMessyPileRevisions.every(
      (pass) =>
        pass?.chapter === "NTH" &&
        pass.scrubMode === "original-shot" &&
        pass.items.length === 1 &&
        pass.items[0]?.cutId === "CUT-026",
    ),
  );
  assert.deepEqual(
    nthWardrobeMessyPileRevisions.map((pass) => pass?.items[0]?.image),
    [
      "/archive/nth-wardrobe/versions/CUT-026-r7-collapsed-saddle-pile.png",
      "/archive/nth-wardrobe/versions/CUT-026-r8-diagonal-clothes-avalanche.png",
      "/archive/nth-wardrobe/versions/CUT-026-r9-walkable-clothing-canyon.png",
    ],
  );
  assert.match(
    nthWardrobeMessyPileRevisions[0]?.items[0]?.mockupDescription,
    /compressed saddle instead of through a product display/i,
  );
  assert.match(
    nthWardrobeMessyPileRevisions[1]?.items[0]?.mockupDescription,
    /gravity-driven heap/i,
  );
  assert.match(
    nthWardrobeMessyPileRevisions[2]?.items[0]?.mockupDescription,
    /one continuous messy pile/i,
  );
  assert.equal(nthWardrobeSourceMatchRevision?.title, "NTH Wardrobe r23");
  assert.equal(nthWardrobeSourceMatchRevision?.passNumber, 23);
  assert.equal(nthWardrobeSourceMatchRevision?.chapter, "NTH");
  assert.equal(
    nthWardrobeSourceMatchRevision?.scrubMode,
    "original-shot",
  );
  assert.deepEqual(
    nthWardrobeSourceMatchRevision?.items.map((item) => item.cutId),
    ["CUT-026"],
  );
  assert.equal(
    nthWardrobeSourceMatchRevision?.items[0]?.image,
    "/archive/nth-wardrobe/versions/CUT-026-r10-source-matched-clothes-avalanche.png",
  );
  assert.match(
    nthWardrobeSourceMatchRevision?.items[0]?.mockupDescription,
    /source frame's scale and position/i,
  );
  assert.match(
    nthWardrobeSourceMatchRevision?.items[0]?.mockupDescription,
    /original distant mountain silhouettes/i,
  );
  assert.equal(
    nthWardrobeReadableSourceMatchRevision?.title,
    "NTH Wardrobe r24",
  );
  assert.equal(nthWardrobeReadableSourceMatchRevision?.passNumber, 24);
  assert.equal(nthWardrobeReadableSourceMatchRevision?.chapter, "NTH");
  assert.equal(
    nthWardrobeReadableSourceMatchRevision?.scrubMode,
    "original-shot",
  );
  assert.deepEqual(
    nthWardrobeReadableSourceMatchRevision?.items.map((item) => item.cutId),
    ["CUT-026"],
  );
  assert.equal(
    nthWardrobeReadableSourceMatchRevision?.items[0]?.image,
    "/archive/nth-wardrobe/versions/CUT-026-r11-bright-readable-source-match.png",
  );
  assert.match(
    nthWardrobeReadableSourceMatchRevision?.items[0]?.mockupDescription,
    /Brighter midtones and narrow edge highlights/i,
  );
  assert.match(
    nthWardrobeReadableSourceMatchRevision?.items[0]?.mockupDescription,
    /partially buried/i,
  );
  const nthCut28Versions = nthWardrobePasses.flatMap((pass) =>
    pass.items.filter((item) => item.cutId === "CUT-028"),
  );
  const nthCut31Versions = nthWardrobePasses.flatMap((pass) =>
    pass.items.filter((item) => item.cutId === "CUT-031"),
  );
  assert.equal(nthCut28Versions.length, 3);
  assert.equal(nthCut31Versions.length, 4);
  assert.equal(
    new Set(nthCut28Versions.map((item) => item.image)).size,
    3,
  );
  assert.equal(
    new Set(nthCut31Versions.map((item) => item.image)).size,
    4,
  );
  await Promise.all(
    [
      ...nthWardrobeActionRevision.items,
      ...nthWardrobeCanonicalActionRevision.items,
      ...nthWardrobeGarmentEndsRevision.items,
      ...nthWardrobeOrangeSweaterRevision.items,
      ...nthWardrobeCanonicalScaleRevision.items,
      ...nthWardrobeSubtleHorizonRevision.items,
      ...nthWardrobeWhisperedHorizonRevision.items,
      ...nthWardrobeMessyPileRevisions.flatMap((pass) => pass?.items ?? []),
      ...nthWardrobeSourceMatchRevision.items,
      ...nthWardrobeReadableSourceMatchRevision.items,
    ].map((item) => access(new URL(`../public${item.image}`, import.meta.url))),
  );
  assert.equal(nthWardrobePlan.revisionPassId, "nth-wardrobe-pass-02");
  assert.deepEqual(nthWardrobePlan.selectedWardrobe, [
    "Burgundy Orange Circle Dress",
    "Red Corset Top",
    "Silver Over-Ear Headphones",
    "Striped Short-Sleeve Top",
    "Pink Ruffle Trousers",
    "Olive Crochet Bag",
    "Multicolor Ribbed Top",
    "Lime Open-Knit Scarf",
    "Burgundy Button Corset",
    "Gray Opera Gloves",
    "Crystal Tiara",
    "Red Knee Boots",
    "Red Beret",
    "Blue Polka-Dot Blouse",
    "Blue Striped Fuzzy Sweater",
    "Pink Striped Shag Sweater",
  ]);
  assert.deepEqual(
    nthWardrobePlan.revisionCoverage.find((entry) =>
      entry.cuts.includes("CUT-026"),
    )?.items,
    [
      "Red Corset Top",
      "Silver Over-Ear Headphones",
      "Burgundy Button Corset",
      "Gray Opera Gloves",
      "Crystal Tiara",
      "Red Knee Boots",
    ],
  );
  assert.deepEqual(
    nthWardrobePlan.revisionCoverage.find((entry) =>
      entry.cuts.includes("CUT-031"),
    )?.items,
    ["Blue Polka-Dot Blouse"],
  );
  for (const [cutId, expectedVersionCount] of [
    ["CUT-023", 5],
    ["CUT-024", 8],
    ["CUT-026", 11],
  ]) {
    const cutVersions = nthWardrobePasses.flatMap((pass) =>
      pass.items.filter((item) => item.cutId === cutId),
    );
    assert.equal(cutVersions.length, expectedVersionCount);
    assert.equal(
      new Set(cutVersions.map((item) => item.image)).size,
      expectedVersionCount,
    );
  }
  assert.match(
    nthWardrobePlan.sourceRules.littleAbbyWardrobe,
    /burgundy puff-sleeve patchwork/i,
  );
  assert.match(
    nthWardrobePlan.sourceRules.bigAbbyWardrobe,
    /heather-gray Drab long-sleeve top/i,
  );
  assert.match(
    nthWardrobePlan.sourceRules.excludedWardrobe,
    /Do not add unselected Objects Wardrobe pieces/i,
  );
  assert.ok(
    nthWardrobePlan.feedbackApplied.some(
      (note) =>
        note.title === "Put Big Abby inside the house" &&
        note.cuts.includes("CUT-031"),
    ),
  );
  await Promise.all(
    nthWardrobePasses
      .flatMap((pass) => pass.items)
      .map((item) =>
        access(new URL(`../public${item.image}`, import.meta.url)),
      ),
  );

  assert.match(atlasSource, />\s*Mockup\s*</);
  assert.match(atlasSource, /siteView === "mockup"/);
  assert.match(gallerySource, /poster=\{cut\.thumbnail\}/);
  assert.match(gallerySource, /src=\{cut\.scrubProxy \|\| hoverProxy\}/);
  assert.doesNotMatch(gallerySource, /Scrub original/i);
  assert.doesNotMatch(gallerySource, /mockup-version-hint/);
  assert.match(gallerySource, /const \[mockupScope, setMockupScope\]/);
  assert.match(gallerySource, /mockupScope === "all"\s*\?\s*cuts\.map/);
  assert.match(gallerySource, /latestMockupByCutId\.get\(cut\.id\)/);
  assert.match(gallerySource, /candidate\.pass\?\.styleId === mockupScope/);
  assert.match(gallerySource, /mockupLooks\.map\(\(look\) =>/);
  assert.match(
    gallerySource,
    /styleId === "nth-wardrobe"\) return "NTH Wardrobe"/,
  );
  assert.match(gallerySource, /version\.pass\?\.styleId === mockupScope/);
  assert.match(
    gallerySource,
    /src=\{selectedVersion\?\.image \|\| cut\.thumbnail\}/,
  );
  assert.match(gallerySource, /const versionsByCutId = useMemo/);
  assert.match(gallerySource, /persistedFrame\?\.sourceImage/);
  assert.match(gallerySource, /persistedFrame\?\.sourceTime/);
  assert.match(gallerySource, /Mockup \{selectedVersion\.ordinal\}/);
  assert.match(gallerySource, /OriginalFrameCard/);
  assert.match(gallerySource, /aria-haspopup="listbox"/);
  assert.match(gallerySource, /<RightInspectorPanel/);
  assert.match(
    gallerySource,
    /panelClassName="mockup-version-inspector"/,
  );
  assert.match(gallerySource, /className="mockup-version-list"/);
  assert.match(gallerySource, /role="option"/);
  assert.match(gallerySource, /aria-selected=\{selected\}/);
  assert.match(gallerySource, /setSelectedVersionByCutId/);
  assert.match(
    gallerySource,
    /paracosm:mockup-thumbnail-selections:v1/,
  );
  assert.match(gallerySource, /readMockupThumbnailSelections/);
  assert.match(gallerySource, /window\.localStorage\.getItem/);
  assert.match(gallerySource, /window\.localStorage\.setItem/);
  assert.match(
    gallerySource,
    /persistMockupThumbnailSelection\(\s*versionPanelCut\.id,\s*version\.id/,
  );
  assert.match(gallerySource, /Current pick/);
  assert.match(gallerySource, /className="feedback-sticky-nav mockup-sticky-nav"/);
  assert.match(gallerySource, /aria-label="Search mockups"/);
  assert.match(gallerySource, /aria-label="Mockup chapter"/);
  assert.match(gallerySource, /selectedVersion\.mockupName/);
  assert.match(gallerySource, /selectedVersion\.mockupDescription/);
  assert.match(gallerySource, /const \[cardScrub, setCardScrub\]/);
  assert.match(gallerySource, /const cardScrubVideoRef = useRef/);
  assert.match(gallerySource, /onPointerMove=\{\(event\) => updateCardScrub\(event, cut\)\}/);
  assert.match(gallerySource, /src=\{cut\.scrubProxy \|\| hoverProxy\}/);
  assert.match(gallerySource, /name=\{cut\.shotName\}/);
  assert.match(gallerySource, /description=\{cut\.description\}/);
  assert.match(gallerySource, /className="mockup-card-caption"/);
  assert.match(styles, /\.mockup-frame\.scrub-previewing > video\.ready/);
  assert.match(styles, /\.mockup-card-scrub-track\s*\{/);
  assert.doesNotMatch(gallerySource, /className="mockup-header"/);
  assert.doesNotMatch(gallerySource, />MOCKUP LIBRARY</);
});

test("Pipeline, Feedback, Mockup, and Objects share one resizable inspector shell", async () => {
  const [atlas, feedback, mockup, objects3D, objects, objectAssets, panel, styles] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/feedback-tracker.tsx"),
    text("../app/mockup-gallery.tsx"),
    text("../app/object-3d-gallery.tsx"),
    text("../app/object-inventory.tsx"),
    text("../app/object-asset-inspector.tsx"),
    text("../app/right-inspector-panel.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(atlas, /<RightInspectorPanel/);
  assert.match(feedback, /<RightInspectorPanel/);
  assert.match(mockup, /<RightInspectorPanel/);
  assert.match(objects3D, /<ObjectAssetInspector/);
  assert.match(objects, /<ObjectAssetInspector/);
  assert.match(objectAssets, /<RightInspectorPanel/);
  assert.match(panel, /PANEL_WIDTH_STORAGE_KEY/);
  assert.match(panel, /paracosm:right-inspector-width/);
  assert.match(panel, /role="separator"/);
  assert.match(panel, /aria-orientation="vertical"/);
  assert.match(panel, /onPointerDown=\{startResize\}/);
  assert.match(panel, /onPointerMove=\{resize\}/);
  assert.match(panel, /onKeyDown=\{resizeFromKeyboard\}/);
  assert.match(panel, /onWheel=\{containPanelWheel\}/);
  assert.match(panel, /event\.preventDefault\(\)/);
  assert.match(panel, /scrollTarget\.scrollTop \+= pixelDelta/);
  assert.match(styles, /\.right-inspector-panel\s*\{/);
  assert.match(styles, /\.right-inspector-resize\s*\{/);
  assert.match(styles, /cursor:\s*col-resize/);
  assert.match(styles, /overscroll-behavior-y:\s*none/);
});

test("Mockup scrubs frame-centered source cards and preserves frame threads", async () => {
  const [gallery, styles] = await Promise.all([
    text("../app/mockup-gallery.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(gallery, /className="mockup-thread-source-media"/);
  assert.match(gallery, /data-testid=\{`source-frame-\$\{cut\.id\}-\$\{thread\.id\}`\}/);
  assert.match(
    gallery,
    /data-testid=\{`source-frame-region-\$\{cut\.id\}-\$\{thread\.id\}`\}/,
  );
  assert.match(gallery, /onPointerMove=\{updateScrub\}/);
  assert.match(gallery, /onPointerLeave=\{handleRegionLeave\}/);
  assert.match(gallery, /setScrub\(initialScrub\)/);
  assert.match(gallery, /onPointerEnter=\{startScrub\}/);
  assert.match(gallery, /setReady\(false\);\s*updateScrub\(event\)/);
  assert.doesNotMatch(gallery, /const regionRef/);
  assert.doesNotMatch(gallery, /window\.addEventListener\("pointermove"/);
  assert.doesNotMatch(gallery, /resetOutsideCard/);
  assert.doesNotMatch(gallery, /HOVER_EXIT_GRACE_MS/);
  assert.doesNotMatch(gallery, /resetTimerRef/);
  assert.match(gallery, /previewing \? "scrub-previewing" : ""/);
  assert.doesNotMatch(gallery, /hasScrubbed/);
  assert.doesNotMatch(gallery, /scrub-has-frame/);
  assert.match(
    gallery,
    /className=\{ready && \(previewing \|\| expanded\) \? "ready" : ""\}/,
  );
  assert.doesNotMatch(gallery, /Hover to scrub/);
  assert.doesNotMatch(gallery, /type="range"/);
  assert.doesNotMatch(gallery, /mockup-thumbnail-picker/);
  assert.match(gallery, /src=\{cut\.scrubProxy \|\| hoverProxy\}/);
  assert.match(gallery, /cut\.scrubStart \?\? cut\.start/);
  assert.match(gallery, /Math\.round\(scrubStart \* fps\)/);
  assert.match(gallery, /\(frame \+ 0\.5\) \/ fps/);
  assert.match(gallery, /context\.drawImage\(video/);
  assert.match(gallery, /canvas\.toDataURL\("image\/jpeg", 0\.9\)/);
  assert.match(gallery, /setSessionFramesByCutId/);
  assert.match(gallery, /`source:\$\{threadId\}`/);
  assert.match(gallery, /key=\{`\$\{versionPanelCut\.id\}:\$\{thread\.id\}`\}/);
  assert.match(
    gallery,
    /if \(threadKinds\.length === 0\) threadKinds\.push\("canonical"\)/,
  );
  assert.match(gallery, /className="mockup-thread-capture-overlay"/);
  assert.match(gallery, /aria-label="Confirm make thumbnail"/);
  assert.match(gallery, /aria-label="Cancel thumbnail"/);
  assert.match(gallery, /Make thumbnail\?/);
  assert.match(gallery, /className="mockup-frame-thread"/);
  assert.match(styles, /\.mockup-thread-source-media\s*\{/);
  assert.match(
    styles,
    /\.mockup-thread-source\.scrub-previewing[\s\S]*\.mockup-thread-source-media[\s\S]*> video\.ready/,
  );
  assert.match(styles, /\.mockup-thread-capture-overlay\s*\{/);
  assert.doesNotMatch(styles, /\.mockup-thread-scrub-hint\s*\{/);
  assert.doesNotMatch(styles, /\.mockup-thumbnail-picker\s*\{/);
});

test("Palette assembles the past-year Instagram color system", async () => {
  const [palette, atlasSource, paletteSource, styles] = await Promise.all([
    json("../data/instagram-palette.json"),
    text("../app/provenance-atlas.tsx"),
    text("../app/instagram-palette.tsx"),
    text("../app/globals.css"),
  ]);

  assert.equal(palette.schemaVersion, 1);
  assert.equal(palette.account, "the.absolutely");
  assert.deepEqual(palette.auditRange, {
    from: "2025-07-27",
    to: "2026-07-27",
  });
  assert.equal(palette.postsReviewed, 45);
  assert.equal(palette.postsWithSavedStills, 36);
  assert.equal(palette.sourceImageCount, 66);
  assert.equal(palette.mainColors.length, 16);
  assert.equal(palette.families.length, 11);
  assert.ok(
    Math.abs(
      palette.hueFamilies.reduce((sum, family) => sum + family.share, 0) -
        100,
    ) <= 0.2,
  );
  assert.deepEqual(
    ["ink", "red", "copper", "blue", "teal", "violet", "mauve"].map((id) =>
      palette.families.some((family) => family.id === id),
    ),
    [true, true, true, true, true, true, true],
  );
  assert.ok(
    palette.mainColors.every(
      (color) => /^#[0-9a-f]{6}$/i.test(color.hex) && color.share > 0,
    ),
  );
  await Promise.all(
    palette.featuredSourceFiles.map((sourceFile) =>
      access(
        new URL(
          `../public/archive/objects/sources/wardrobe/${sourceFile}`,
          import.meta.url,
        ),
      ),
    ),
  );

  assert.match(atlasSource, />\s*Palette\s*</);
  assert.match(atlasSource, /siteView === "palette"/);
  assert.match(atlasSource, /<InstagramPalette/);
  assert.match(paletteSource, /Every measured color, retained/);
  assert.match(paletteSource, />Chromatic rhythm</);
  assert.match(paletteSource, />Working color families</);
  assert.match(styles, /\.palette-cover\s*\{/);
  assert.match(styles, /\.palette-family-grid\s*\{/);
});

test("the Objects view inventories deduplicated reference objects", async () => {
  const [
    inventory,
    wardrobeAudit,
    hollowMultiviewManifest,
    atlasSource,
    objectSource,
    objectDataSource,
  ] = await Promise.all([
    json("../data/object-inventory.json"),
    json("../data/object-wardrobe-sources.json"),
    json("../data/wardrobe-hollow-multiview-20260728.json"),
    text("../app/provenance-atlas.tsx"),
    text("../app/object-inventory.tsx"),
    text("../app/object-inventory-data.ts"),
  ]);
  const hollowMultiviewByObjectId = new Map(
    hollowMultiviewManifest.objects.map((item) => [
      item.objectId,
      [
        {
          id: "hollow-top-3d-input",
          image: item.assets.top,
        },
        {
          id: "hollow-side-3d-input",
          image: item.assets.side,
        },
        {
          id: "hollow-bottom-3d-input",
          image: item.assets.bottom,
        },
      ],
    ]),
  );
  const objects = [
    ...inventory.objects,
    ...inventory.generatedGroups.flatMap((group) =>
      group.objects.map((item) => ({
        ...item,
        category: group.category,
        image: item.image || `${group.imageDirectory}/${item.id}.png`,
        sourceFiles: item.sourceFiles || group.sourceFiles || [],
        alternateImages: [
          ...(item.alternateImages || []),
          ...(group.alternateImageDirectories || []).map((alternate) => ({
            id: alternate.id,
            label: alternate.label,
            image: `${alternate.directory}/${item.id}.png`,
            description: alternate.description,
          })),
          ...(hollowMultiviewByObjectId.get(item.id) || []),
        ],
      })),
    ),
  ];

  assert.equal(inventory.schemaVersion, 1);
  assert.equal(objects.length, 166);
  assert.equal(new Set(objects.map((item) => item.id)).size, 166);
  assert.equal(new Set(objects.map((item) => item.name)).size, 166);
  assert.equal(
    new Set(objects.flatMap((item) => item.sourceFiles)).size,
    89,
  );
  assert.ok(objects.every((item) => item.sourceFiles.length >= 1));
  assert.ok(
    objects.some((item) => item.sourceFiles.length > 1),
    "repeated source photos should roll up to a canonical object",
  );
  assert.equal(
    inventory.generatedGroups.find((group) => group.id === "glass-vessels")
      .objects.length,
    34,
  );
  assert.equal(
    inventory.generatedGroups.find((group) => group.id === "wall-plates")
      .objects.length,
    4,
  );
  const wardrobe = inventory.generatedGroups.find(
    (group) => group.id === "wardrobe",
  );
  assert.equal(wardrobe.objects.length, 29);
  assert.equal(wardrobe.alternateImageDirectories.length, 1);
  assert.deepEqual(
    wardrobe.alternateImageDirectories.map((alternate) => alternate.id),
    ["tossed-floor"],
  );
  const historicalWardrobe = inventory.generatedGroups.find(
    (group) => group.id === "wardrobe-historical",
  );
  assert.equal(historicalWardrobe.objects.length, 48);
  assert.equal(historicalWardrobe.alternateImageDirectories, undefined);
  const wardrobeObjects = objects.filter(
    (item) => item.category === "Wardrobe",
  );
  const originalWardrobeIds = new Set(wardrobe.objects.map((item) => item.id));
  const historicalWardrobeIds = new Set(
    historicalWardrobe.objects.map((item) => item.id),
  );
  assert.ok(
    wardrobeObjects
      .filter((item) => originalWardrobeIds.has(item.id))
      .every((item) =>
        item.alternateImages.some(
          (alternate) => alternate.label === "Casually tossed",
        ),
      ),
  );
  const burgundyCorset = wardrobeObjects.find(
    (item) => item.id === "burgundy-button-corset",
  );
  assert.ok(
    burgundyCorset.alternateImages.some(
      (alternate) => alternate.id === "three-quarter-3d-input",
    ),
  );
  assert.ok(
    [
      "hollow-top-3d-input",
      "hollow-side-3d-input",
      "hollow-bottom-3d-input",
    ].every((alternateId) =>
      burgundyCorset.alternateImages.some(
        (alternate) => alternate.id === alternateId,
      ),
    ),
  );
  assert.equal(hollowMultiviewManifest.objects.length, 56);
  assert.deepEqual(
    new Set(hollowMultiviewManifest.objects.map((item) => item.objectId)),
    new Set(hollowMultiviewByObjectId.keys()),
  );
  assert.ok(
    wardrobeObjects
      .filter((item) => hollowMultiviewByObjectId.has(item.id))
      .every((item) =>
        [
          "hollow-top-3d-input",
          "hollow-side-3d-input",
          "hollow-bottom-3d-input",
        ].every((alternateId) =>
          item.alternateImages.some(
            (alternate) => alternate.id === alternateId,
          ),
        ),
      ),
    "every generated hollow wardrobe angle set should appear in Objects",
  );
  assert.ok(
    wardrobeObjects.every(
      (item) =>
        !item.alternateImages.some(
          (alternate) => alternate.id === "hollow-multiview-3d-input",
        ),
    ),
    "combined hollow multiview sheets should stay out of the Objects panel",
  );
  assert.equal(
    hollowMultiviewManifest.objects.filter((item) =>
      item.assets.side.endsWith("-side-clean.png"),
    ).length,
    22,
  );
  assert.ok(
    wardrobeObjects
      .filter(
        (item) =>
          historicalWardrobeIds.has(item.id) &&
          !hollowMultiviewByObjectId.has(item.id),
      )
      .every((item) => {
        if (item.id === "teal-sculpted-corset") {
          return item.alternateImages.some(
            (alternate) => alternate.id === "three-quarter-3d-input",
          );
        }
        if (item.id === "navy-corset-vest") {
          return [
            "hollow-top-3d-input-v3",
            "hollow-side-3d-input-v3",
            "hollow-bottom-3d-input-v3",
          ].every((alternateId) =>
            item.alternateImages.some(
              (alternate) => alternate.id === alternateId,
            ),
          );
        }
        return item.alternateImages.length === 0;
      }),
    "historical garments without generated hollow views should stay unchanged",
  );
  assert.equal(wardrobeObjects.length, 77);
  assert.equal(
    new Set(wardrobeObjects.map((item) => item.id)).size,
    77,
  );
  assert.ok(
    wardrobeObjects.every(
      (item) =>
        originalWardrobeIds.has(item.id) || historicalWardrobeIds.has(item.id),
    ),
  );
  assert.equal(wardrobeAudit.account, "the.absolutely");
  assert.deepEqual(wardrobeAudit.auditRange, {
    from: "2024-02-07",
    to: "2026-07-27",
  });
  assert.equal(wardrobeAudit.postsReviewed, 87);
  assert.equal(wardrobeAudit.postsWithSavedStills, 54);
  assert.equal(wardrobeAudit.savedStillCount, 89);
  assert.equal(wardrobeAudit.reviewedPostUrls.length, 87);
  assert.equal(wardrobeAudit.objects.length, 77);
  assert.deepEqual(
    new Set(wardrobeAudit.objects.map((item) => item.objectId)),
    new Set(wardrobeObjects.map((item) => item.id)),
  );
  assert.ok(
    wardrobeAudit.objects
      .flatMap((item) => item.postUrls)
      .every((postUrl) => wardrobeAudit.reviewedPostUrls.includes(postUrl)),
  );
  assert.ok(
    wardrobeAudit.objects.some((item) => item.postUrls.length > 1),
    "repeated wardrobe appearances should remain attached to one object",
  );
  assert.ok(!objects.some((item) => item.id === "glassware-set"));
  assert.ok(!objects.some((item) => item.id === "plate-set"));
  assert.ok(objects.some((item) => item.id === "glass-window-display"));
  assert.equal(
    objects.find((item) => item.id === "bed").image,
    "/archive/objects/bed-v2.png",
  );
  const roof = objects.find((item) => item.id === "roof");
  assert.equal(roof.category, "Architecture");
  assert.equal(roof.sourceFiles.length, 6);
  assert.equal(roof.alternateImages.length, 2);
  const outdoorPlants = objects.find((item) => item.id === "outdoor-plants");
  assert.equal(outdoorPlants.category, "Architecture");
  assert.deepEqual(outdoorPlants.sourceFiles, [
    "E5D8BCF6-B66E-4ECC-973B-1B32BB464397.HEIC",
  ]);
  await Promise.all(
    objects.map((item) =>
      access(new URL(`../public${item.image}`, import.meta.url)),
    ),
  );
  await Promise.all(
    wardrobeObjects.flatMap((item) =>
      item.alternateImages.map((alternate) =>
        access(new URL(`../public${alternate.image}`, import.meta.url)),
      ),
    ),
  );
  await Promise.all(
    roof.alternateImages.map((alternate) =>
      access(new URL(`../public${alternate.image}`, import.meta.url)),
    ),
  );

  assert.match(atlasSource, />\s*Objects\s*</);
  assert.match(atlasSource, /siteView === "objects"/);
  assert.match(atlasSource, /<ObjectInventory/);
  assert.match(objectSource, /aria-label="Search objects"/);
  assert.match(objectSource, /Object inventory filters/);
  assert.match(objectSource, /item\.sourceFiles\.length/);
  assert.match(objectSource, /<ModelTurntable/);
  assert.match(objectSource, /<ObjectAssetInspector/);
  assert.match(objectSource, /className="object-name-button"/);
  assert.match(objectSource, /objectInventoryManifest as manifest/);
  assert.match(
    objectDataSource,
    /wardrobeHollowMultiviewData from "\.\.\/data\/wardrobe-hollow-multiview-20260728\.json"/,
  );
  assert.match(objectDataSource, /hollowMultiviewByObjectId\.get\(item\.id\)/);
  assert.doesNotMatch(objectDataSource, /label: "Hollow multiview"/);
  assert.doesNotMatch(objectSource, /3D Preview/);
  await Promise.all(
    objects.flatMap((item) =>
      item.sourceFiles.map((sourceFile) =>
        access(
          new URL(
            `../public/archive/objects/sources/${sourceFile.replace(/\.[^.]+$/, "")}.jpg`,
            import.meta.url,
          ),
        ),
      ),
    ),
  );
});

test("Objects tracks modeling cautions and assembly relationships", async () => {
  const [notes, inventorySource, inspectorSource, metadataSource, styles] =
    await Promise.all([
      json("../data/object-production-notes.json"),
      text("../app/object-inventory.tsx"),
      text("../app/object-asset-inspector.tsx"),
      text("../app/object-production-metadata.ts"),
      text("../app/globals.css"),
    ]);

  assert.equal(notes.schemaVersion, 1);
  const notedObjectIds = new Set(
    notes.objects.map((item) => item.objectId),
  );
  for (const objectId of [
    "bed",
    "wall-panel",
    "glass-window-display",
    "stair-railing",
    "books",
    "green-lamp",
    "roof",
    "outdoor-plants",
    "chimney",
  ]) {
    assert.ok(notedObjectIds.has(objectId));
  }
  const bedNote = notes.objects.find((item) => item.objectId === "bed").notes[0];
  const wallPanelNote = notes.objects.find(
    (item) => item.objectId === "wall-panel",
  ).notes[0];
  const glassDisplayNote = notes.objects.find(
    (item) => item.objectId === "glass-window-display",
  ).notes[0];
  const stairNote = notes.objects.find(
    (item) => item.objectId === "stair-railing",
  ).notes[0];
  const greenLampNote = notes.objects.find(
    (item) => item.objectId === "green-lamp",
  ).notes[0];

  assert.match(bedNote.detail, /mirror/i);
  assert.deepEqual(bedNote.relatedObjectIds, ["wall-panel"]);
  assert.equal(wallPanelNote.status, "separate-asset");
  assert.deepEqual(wallPanelNote.relatedObjectIds, ["bed"]);
  assert.equal(glassDisplayNote.kind, "relationship");
  assert.match(glassDisplayNote.proposedParts.join(" "), /34/);
  assert.ok(stairNote.proposedParts.length >= 7);
  assert.match(greenLampNote.detail, /mirror/i);
  const splitNotes = notes.objects.flatMap((record) =>
    record.notes.filter((note) => note.id === "split-shoe-pair"),
  );
  assert.equal(splitNotes.length, 10);
  assert.ok(
    splitNotes.every(
      (note) =>
        note.kind === "split-review" &&
        note.status === "complete" &&
        note.proposedParts.length === 2,
    ),
  );
  assert.ok(
    notes.objects.some((record) =>
      record.notes.some((note) => note.status === "complete"),
    ),
  );
  assert.ok(
    notes.objects.some((record) =>
      record.notes.some((note) => note.status === "review"),
    ),
  );

  assert.match(metadataSource, /productionNotesForObject/);
  assert.match(metadataSource, /productionNoteSummary/);
  assert.match(inventorySource, /productionNoteSummary\(productionNotes\)/);
  assert.match(inspectorSource, />Production notes</);
  assert.match(inspectorSource, /note\.relatedObjectIds/);
  assert.match(inspectorSource, /note\.proposedParts/);
  assert.match(styles, /\.object-production-note\.note-generation-caution/);
  assert.match(styles, /\.object-production-note\.note-relationship/);
  assert.match(styles, /\.object-production-note\.note-split-review/);
});

test("Objects carries a complete source audit and 3D reconstruction graph", async () => {
  const [plan, inventory, inspectorSource, metadataSource, styles] =
    await Promise.all([
      json("../data/object-reconstruction-plan.json"),
      json("../data/object-inventory.json"),
      text("../app/object-asset-inspector.tsx"),
      text("../app/object-reconstruction-metadata.ts"),
      text("../app/globals.css"),
    ]);
  const objects = [
    ...inventory.objects,
    ...inventory.generatedGroups.flatMap((group) =>
      group.objects.map((item) => ({
        ...item,
        category: group.category,
        image: item.image || `${group.imageDirectory}/${item.id}.png`,
        sourceFiles: item.sourceFiles || group.sourceFiles || [],
      })),
    ),
  ];
  const objectIds = new Set(objects.map((item) => item.id));
  const reconstructionObjects = objects.filter(
    (item) => item.category !== "Wardrobe",
  );
  const sourceFiles = new Set(
    reconstructionObjects.flatMap((item) => item.sourceFiles),
  );
  const assemblyIds = new Set(plan.assemblies.map((item) => item.id));

  assert.equal(plan.schemaVersion, 1);
  assert.equal(plan.sourceAudit.status, "complete");
  assert.equal(plan.sourceAudit.sourceCount, 37);
  assert.equal(plan.sourceAudit.sources.length, 37);
  assert.equal(
    new Set(plan.sourceAudit.sources.map((item) => item.sourceFile)).size,
    37,
  );
  assert.deepEqual(
    new Set(plan.sourceAudit.sources.map((item) => item.sourceFile)),
    sourceFiles,
  );
  assert.ok(
    plan.sourceAudit.sources
      .flatMap((item) => item.objectIds)
      .every((objectId) => objectIds.has(objectId)),
  );
  assert.ok(
    plan.sourceAudit.sources
      .flatMap((item) => item.assemblyIds)
      .every((assemblyId) => assemblyIds.has(assemblyId)),
  );
  assert.ok(
    plan.assetStrategies
      .flatMap((item) => item.objectIds)
      .every((objectId) => objectIds.has(objectId)),
  );
  assert.ok(
    plan.assemblies
      .flatMap((item) => item.componentObjectIds)
      .every((objectId) => objectIds.has(objectId)),
  );
  assert.deepEqual(
    [
      "bed-setup",
      "staircase",
      "house-exterior",
      "glass-window-display",
      "studio-display",
    ].map((id) => assemblyIds.has(id)),
    [true, true, true, true, true],
  );

  const glassAssembly = plan.assemblies.find(
    (item) => item.id === "glass-window-display",
  );
  assert.equal(glassAssembly.placements.length, 34);
  assert.equal(
    new Set(glassAssembly.placements.map((item) => item.objectId)).size,
    34,
  );
  assert.deepEqual(
    ["left", "center", "right"].map(
      (window) =>
        glassAssembly.placements.filter((item) => item.window === window)
          .length,
    ),
    [9, 14, 11],
  );

  const staircase = plan.assemblies.find((item) => item.id === "staircase");
  const house = plan.assemblies.find((item) => item.id === "house-exterior");
  const bedStrategy = plan.assetStrategies.find((item) =>
    item.objectIds.includes("bed"),
  );
  const roofStrategy = plan.assetStrategies.find((item) =>
    item.objectIds.includes("roof"),
  );
  const plantStrategy = plan.assetStrategies.find((item) =>
    item.objectIds.includes("outdoor-plants"),
  );
  assert.equal(staircase.sourceFiles.length, 2);
  assert.match(staircase.plannedParts.join(" "), /treads|risers/i);
  assert.equal(house.sourceFiles.length, 6);
  assert.ok(house.componentObjectIds.includes("roof"));
  assert.ok(house.componentObjectIds.includes("outdoor-plants"));
  assert.match(house.plannedParts.join(" "), /roof/i);
  assert.match(house.plannedParts.join(" "), /plant/i);
  assert.equal(bedStrategy.mode, "multi-image");
  assert.match(bedStrategy.cautions.join(" "), /mirror/i);
  assert.equal(roofStrategy.mode, "multi-image");
  assert.equal(roofStrategy.inputSourceFiles.length, 6);
  assert.match(roofStrategy.cautions.join(" "), /chimney/i);
  assert.equal(plantStrategy.mode, "assembly-component");
  assert.match(plantStrategy.cautions.join(" "), /one front view/i);

  assert.match(metadataSource, /reconstructionStrategyForObject/);
  assert.match(metadataSource, /reconstructionAssembliesForObject/);
  assert.match(inspectorSource, />3D reconstruction</);
  assert.match(inspectorSource, /Useful next angles/);
  assert.match(inspectorSource, /placement\.window/);
  assert.match(styles, /\.object-reconstruction-section/);
  assert.match(styles, /\.object-assembly-card/);
});

test("Objects contains a 3D subview with local models and shared version navigation", async () => {
  const [
    manifest,
    inventory,
    remainingWardrobeRun,
    atlasSource,
    gallerySource,
    objectSource,
    assetSource,
    pianoPerformance,
    styles,
  ] = await Promise.all([
      json("../data/object-3d-versions.json"),
      json("../data/object-inventory.json"),
      json("../data/meshy-remaining-wardrobe-run-20260728.json"),
      text("../app/provenance-atlas.tsx"),
      text("../app/object-3d-gallery.tsx"),
      text("../app/object-inventory.tsx"),
      text("../app/object-asset-inspector.tsx"),
      json("../data/piano-performance-vid5.json"),
      text("../app/globals.css"),
    ]);

  assert.equal(manifest.schemaVersion, 1);
  const expectedModelIds = new Set([
    ...inventory.objects.map((item) => item.id),
    ...inventory.generatedGroups.flatMap((group) =>
      group.objects.map((item) => item.id),
    ),
  ]);
  expectedModelIds.delete("roof");
  expectedModelIds.delete("outdoor-plants");
  const manifestModelIds = new Set(
    manifest.objects.map((item) => item.objectId),
  );
  assert.equal(manifest.objects.length, expectedModelIds.size);
  assert.ok(
    [...expectedModelIds].every((objectId) =>
      manifestModelIds.has(objectId),
    ),
  );
  assert.ok(manifest.objects.every((item) => item.versions.length >= 1));
  assert.equal(remainingWardrobeRun.objects.length, 56);
  assert.deepEqual(remainingWardrobeRun.summary, { succeeded: 56 });
  assert.equal(remainingWardrobeRun.initialBalance, 7600);
  assert.equal(remainingWardrobeRun.finalBalance, 5920);
  assert.ok(
    remainingWardrobeRun.objects.every(
      (item) =>
        item.status === "succeeded" &&
        item.taskId &&
        item.progress === 100 &&
        item.model &&
        item.thumbnail &&
        item.faces > 0 &&
        item.vertices > 0 &&
        !item.error,
    ),
  );
  assert.ok(
    manifest.objects.every((item) =>
      item.versions.every(
        (version) =>
          [
            "Meshy 6",
            "Meshy 6 Multi-Image",
            "Meshy 6 pose reconstruction",
            "Meshy 6 Retexture",
            "Blender 4.5",
          ].includes(version.provider) &&
          version.faces > 0 &&
          version.vertices > 0 &&
          ["ready", "review", "needs-fix"].includes(version.status),
      ),
    ),
  );
  const latestVersions = new Map(
    manifest.objects.map((item) => [item.objectId, item.versions.at(-1)]),
  );
  for (const objectId of [
    "lavender-check-fuzzy-shoes",
    "piano",
    "cafe-model",
    "ice-cream-shop",
    "green-wall-plate",
    "lavender-wall-plate",
    "purple-wall-plate",
    "black-knee-boots",
  ]) {
    assert.equal(latestVersions.get(objectId)?.status, "ready");
  }
  const burgundyCorsetRecord = manifest.objects.find(
    (item) => item.objectId === "burgundy-button-corset",
  );
  assert.equal(
    burgundyCorsetRecord?.primaryVersionId,
    "blender-hollow-repair-v5",
  );
  assert.equal(
    burgundyCorsetRecord?.versions.find(
      (version) => version.id === burgundyCorsetRecord.primaryVersionId,
    )?.status,
    "ready",
  );
  assert.equal(
    latestVersions.get("burgundy-button-corset")?.status,
    "review",
  );
  assert.equal(
    burgundyCorsetRecord?.versions.find(
      (version) => version.id === "meshy-hollow-multiview-v4",
    )?.status,
    "needs-fix",
  );
  assert.equal(latestVersions.get("teal-sculpted-corset")?.status, "review");
  assert.equal(latestVersions.get("orange-wall-plate")?.status, "ready");
  assert.equal(latestVersions.get("piano")?.id, "blender-performance-v4");
  const splitFootwear = manifest.objects.filter(
    (item) =>
      item.versions.some((version) => version.id === "blender-left-v3") &&
      item.versions.some((version) => version.id === "blender-right-v3"),
  );
  assert.equal(splitFootwear.length, 10);
  assert.ok(
    splitFootwear.every(
      (item) =>
        item.primaryVersionId === "meshy-v1" &&
        item.versions.some((version) => version.id === item.primaryVersionId),
    ),
  );
  const redCorset = manifest.objects.find(
    (item) => item.objectId === "red-corset-top",
  );
  const redCorsetSimulation = redCorset?.simulations?.find(
    (simulation) => simulation.id === "blender-cloth-stool-v1",
  );
  const redCorsetSphereSimulation = redCorset?.simulations?.find(
    (simulation) => simulation.id === "blender-cloth-sphere-v2",
  );
  assert.equal(redCorset?.simulations?.length, 2);
  assert.equal(redCorsetSphereSimulation?.label, "Invisible sphere drape");
  assert.equal(
    redCorsetSphereSimulation?.collisionObject,
    "Invisible sphere",
  );
  assert.equal(redCorsetSphereSimulation?.settledFrame, 80);
  await Promise.all(
    [
      redCorsetSphereSimulation.video,
      redCorsetSphereSimulation.poster,
      redCorsetSphereSimulation.settledModel,
      redCorsetSphereSimulation.scene,
    ].map((asset) => access(new URL(`../public${asset}`, import.meta.url))),
  );
  assert.equal(redCorsetSimulation?.label, "Piano stool drape");
  assert.equal(redCorsetSimulation?.collisionObject, "Piano stool");
  assert.equal(redCorsetSimulation?.settledFrame, 80);
  await Promise.all(
    [
      redCorsetSimulation.video,
      redCorsetSimulation.poster,
      redCorsetSimulation.settledModel,
      redCorsetSimulation.scene,
    ].map((asset) => access(new URL(`../public${asset}`, import.meta.url))),
  );
  assert.equal(pianoPerformance.schemaVersion, 2);
  assert.equal(pianoPerformance.summary.chordEvents, 8);
  assert.equal(pianoPerformance.summary.distinctKeys, 14);
  assert.deepEqual(pianoPerformance.summary.primaryChords, ["E", "D", "A"]);
  assert.ok(
    pianoPerformance.chords.every(
      ([, start, end, , midiNotes]) =>
        midiNotes.every((midi) => midi >= 21 && midi <= 108) &&
        start >= 0 &&
        end > start &&
        end <= pianoPerformance.durationSeconds,
    ),
  );
  assert.deepEqual(
    pianoPerformance.chords.map(([name]) => name),
    ["E", "D", "E", "A", "E", "D", "E", "A"],
  );
  assert.ok(
    !pianoPerformance.chords.some(([, , , , midiNotes]) =>
      midiNotes.includes(73),
    ),
  );
  await Promise.all(
    manifest.objects.flatMap((item) =>
      item.versions.flatMap((version) => [
        access(new URL(`../public${version.model}`, import.meta.url)),
        access(new URL(`../public${version.thumbnail}`, import.meta.url)),
      ]),
    ),
  );
  const pianoModel = latestVersions.get("piano");
  const pianoGlb = await readFile(
    new URL(`../public${pianoModel.model}`, import.meta.url),
  );
  const pianoGlbJsonLength = pianoGlb.readUInt32LE(12);
  const pianoGlbDocument = JSON.parse(
    pianoGlb
      .subarray(20, 20 + pianoGlbJsonLength)
      .toString("utf8")
      .trim(),
  );
  const pianoAnimation = pianoGlbDocument.animations.find(
    (animation) => animation.name === "VID_5 Performance",
  );
  assert.equal(pianoAnimation.channels.length, 14);
  assert.equal(
    pianoGlbDocument.asset.extras.pianoPerformance.id,
    "vid-5",
  );

  assert.match(atlasSource, /objectView === "3d"/);
  assert.doesNotMatch(
    atlasSource,
    /className=\{siteView === "3d" \? "active" : ""\}/,
  );
  assert.match(atlasSource, /<Object3DGallery/);
  assert.match(assetSource, /import\("@google\/model-viewer"\)/);
  assert.match(gallerySource, /className="three-d-model-viewer"/);
  assert.match(assetSource, /window\.requestAnimationFrame\(animate\)/);
  assert.match(assetSource, /Math\.sin\(time \/ 3100 \+ phase\) \* 11/);
  assert.match(assetSource, /selectedVersion\.status === "needs-fix"/);
  assert.match(assetSource, /viewer\.setAttribute\("camera-orbit"/);
  assert.match(assetSource, /"interaction-prompt": "none"/);
  assert.match(assetSource, /className="object-model-poster"/);
  assert.match(assetSource, /modelLoaded \? "model-loaded" : ""/);
  assert.doesNotMatch(assetSource, /onMouseEnter/);
  assert.match(gallerySource, />\s*Objects\s*</);
  assert.match(gallerySource, />\s*3D/);
  assert.match(gallerySource, /<ObjectAssetInspector/);
  assert.match(assetSource, /label="Object"/);
  assert.match(assetSource, /primaryObject3DVersion/);
  assert.match(gallerySource, /primaryObject3DVersion\(record\)/);
  assert.match(objectSource, /primaryObject3DVersion\(record\)/);
  assert.match(assetSource, /contentId="object-asset-panel"/);
  assert.match(assetSource, /White-background images/);
  assert.match(assetSource, />Cloth simulation</);
  assert.match(
    assetSource,
    /<video[\s\S]*autoPlay[\s\S]*loop[\s\S]*muted[\s\S]*playsInline/,
  );
  assert.doesNotMatch(
    assetSource,
    /<video[\s\S]*controls[\s\S]*simulation\.video/,
  );
  assert.match(assetSource, />● Cloth loop</);
  assert.match(assetSource, /simulation\.video/);
  assert.match(assetSource, /simulation\.settledModel/);
  assert.match(assetSource, /simulation\.scene/);
  assert.match(assetSource, /object\.alternateImages/);
  assert.match(assetSource, /Source image/);
  const primary3DIndex = assetSource.indexOf("<b>3D model</b>");
  const simulationIndex = assetSource.indexOf("<b>Cloth simulation</b>");
  const whiteBackgroundIndex = assetSource.indexOf(
    "<b>White-background images</b>",
  );
  const sourceImageIndex = assetSource.indexOf("<b>Source image</b>");
  const reconstructionIndex = assetSource.indexOf("<b>3D reconstruction</b>");
  assert.ok(primary3DIndex > 0);
  assert.ok(simulationIndex > primary3DIndex);
  assert.ok(simulationIndex < whiteBackgroundIndex);
  assert.ok(primary3DIndex < whiteBackgroundIndex);
  assert.ok(whiteBackgroundIndex < sourceImageIndex);
  assert.ok(sourceImageIndex < reconstructionIndex);
  assert.match(assetSource, /\{selectedVersion && \(/);
  assert.match(assetSource, /className="object-version-select"/);
  assert.match(assetSource, /aria-label=\{`3D version for \$\{object\.name\}`\}/);
  assert.doesNotMatch(assetSource, /className="object-version-list"/);
  assert.doesNotMatch(assetSource, /role="listbox"/);
  assert.doesNotMatch(assetSource, /<b>Versions<\/b>/);
  assert.match(styles, /\.object-version-select select/);
  assert.match(assetSource, /sourceImagePath\(sourceFile\)/);
  assert.match(assetSource, /function PianoPerformancePlayer/);
  assert.match(assetSource, /PIANO_ANIMATION_NAME = "VID_5 Performance"/);
  assert.match(assetSource, /MIDI sound \{soundEnabled \? "on" : "off"\}/);
  assert.match(assetSource, /viewer\.play\(\{ repetitions: 1, pingpong: false \}\)/);
  assert.match(assetSource, /viewer\.currentTime = nextTime/);
  assert.match(assetSource, /AudioContextConstructor/);
  assert.match(objectSource, /className="object-card-model-viewer"/);
  assert.match(objectSource, /className="object-name-button"/);
  assert.match(
    objectSource,
    /className=\{`object-frame object-thumbnail-button/,
  );
  assert.match(objectSource, /aria-label=\{`Open \$\{item\.name\} details`\}/);
  assert.match(
    gallerySource,
    /className=\{`three-d-frame object-thumbnail-button/,
  );
  assert.match(
    gallerySource,
    /aria-label=\{`Open \$\{object\.name\} details`\}/,
  );
  assert.doesNotMatch(objectSource, /object-3d-preview-button/);
  assert.doesNotMatch(gallerySource, /three-d-version-trigger/);
  assert.match(objectSource, />\s*Objects\s*</);
  assert.match(objectSource, />\s*3D/);
  assert.match(styles, /\.three-d-workspace\s*\{/);
  assert.match(styles, /\.three-d-inspector-viewer\s*\{/);
  assert.match(styles, /\.object-model-poster,\s*\n\.object-model-element\s*\{/);
  assert.match(styles, /\.object-name-button\s*\{/);
  assert.match(styles, /\.object-thumbnail-button\s*\{/);
  assert.match(styles, /\.object-alternate-image-list\s*\{/);
  assert.match(styles, /\.object-simulation-loop video\s*\{/);
  assert.match(styles, /\.object-simulation-links\s*\{/);
  assert.match(styles, /\.piano-performance-controls\s*\{/);
  assert.match(styles, /\.piano-performance-scrubber\s*\{/);
});

test("Feedback falls back to its bundled snapshot when the local API is offline", async () => {
  const tracker = await text("../app/feedback-tracker.tsx");

  assert.match(tracker, /import bundledFeedbackData from "\.\.\/data\/feedback\.json"/);
  assert.match(tracker, /const bundledFeedback = bundledFeedbackData as FeedbackData/);
  assert.match(tracker, /hydrateFeedback\(structuredClone\(bundledFeedback\)\)/);
  assert.doesNotMatch(tracker, /setLoadError\(\s*error instanceof Error/);
});

test("the clean Premiere V1/V2 conform is the shared shot-list authority", async () => {
  const state = await json("../public/data/state.json");

  assert.equal(state.readOnly, true);
  assert.equal(state.groundTruth.title, "Paracosm 050726");
  assert.ok(Math.abs(state.groundTruth.fps - 23.976) < 0.001);
  assert.equal(state.groundTruth.durationTimecode, "00:07:17:10");
  assert.equal(state.premiere.sequence, "Paracosm Conform Codex FRAME ALIGNED");
  assert.equal(state.revisedConform.authorityKind, "clean_v1_v2");
  assert.equal(state.revisedConform.sourceImageFrameRate, 24);
  assert.deepEqual(state.revisedConform.canonicalTracks, [1, 2]);
  assert.equal(state.revisedConform.chapterBoundaryTrack, 1);
  assert.equal(state.revisedConform.chapterCuts.length, 6);

  assert.equal(state.cuts.length, 88);
  assert.equal(state.cuts.filter((cut) => cut.isGap).length, 3);
  assert.equal(state.cuts.filter((cut) => !cut.isGap).length, 85);
  assert.ok(state.cuts.every((cut) => cut.sectionCode !== "GAP"));
  for (const [index, cut] of state.cuts.entries()) {
    if (cut.isGap) {
      const adjacentSections = new Set([
        state.cuts[index - 1]?.sectionCode,
        state.cuts[index + 1]?.sectionCode,
      ]);
      assert.ok(adjacentSections.has(cut.sectionCode));
    }
  }
  assert.equal(new Set(state.cuts.map((cut) => cut.id)).size, 88);
  assert.equal(new Set(state.cuts.map((cut) => cut.shotId)).size, 88);
  assert.equal(state.cuts[0].id, "CUT-001");
  assert.equal(state.cuts.at(-1).id, "CUT-088");
  assert.ok(
    state.cuts.every(
      (cut, index) =>
        cut.id === `CUT-${String(index + 1).padStart(3, "0")}` &&
        cut.pipelineAttachmentId === cut.shotId,
    ),
  );
  assert.ok(
    state.cuts
      .slice(1)
      .every((cut, index) => state.cuts[index].end === cut.start),
  );

  const corrected = state.cuts.filter((cut) =>
    ["CUT-019", "CUT-020"].includes(cut.id),
  );
  assert.equal(corrected.length, 2);
  assert.ok(
    corrected.every(
      (cut) =>
        cut.sourceSegments[0].renderDirectory.endsWith(
          "/0211/2C_mountains_Abby-Walking_v001",
        ) && cut.sourceCorrection,
    ),
  );
  assert.deepEqual(
    state.revisedConform.chapterCuts.map((chapter) => chapter.sectionCode),
    ["ND", "NTH", "TH", "NA", "GG", "IJDKYY"],
  );
});

test("feedback and the pipeline join only through persistent shot IDs", async () => {
  const [feedback, state, registry] = await Promise.all([
    json("../data/feedback.json"),
    json("../public/data/state.json"),
    json("../data/canonical/shot-registry.json"),
  ]);
  assert.equal(feedback.schemaVersion, 5);
  assert.equal(feedback.assignmentIdentity, "shotId");
  assert.equal(feedback.generalNotes.length, 2);
  assert.equal(feedback.parents.length, 5);
  assert.equal(feedback.notes.length, 30);
  assert.equal(feedback.editNotes.length, 2);
  assert.equal(feedback.sourceRows.length, 36);
  assert.deepEqual(
    feedback.generalNotes.map((note) => note.title),
    [
      "More Facial Expression",
      "New Motion",
    ],
  );
  assert.deepEqual(
    feedback.generalNotes.map((note) => note.sourceIds),
    [["2", "1"], ["3"]],
  );
  assert.deepEqual(
    feedback.parents.map((parent) => parent.name),
    ["Facial Expression", "Character Motion", "Hair", "Environment", "Camera"],
  );
  assert.doesNotMatch(JSON.stringify(feedback), /"cutIds"/);

  const records = [
    ...feedback.generalNotes,
    ...feedback.parents,
    ...feedback.notes,
    ...feedback.editNotes,
  ];
  const registryById = new Map(
    registry.shots.map((shot) => [shot.shotId, shot]),
  );
  const activeShotIds = new Set(state.cuts.map((cut) => cut.shotId));
  assert.ok(
    records.every((record) =>
      record.shotIds.every((shotId) => registryById.has(shotId)),
    ),
  );
  assert.ok(
    records.every((record) =>
      record.retiredShotIds.every(
        (shotId) =>
          !activeShotIds.has(shotId) &&
          registryById.get(shotId)?.active === false,
      ),
    ),
  );
  assert.ok(feedback.notes.some((note) => note.shotIds.length > 1));
  assert.deepEqual(
    registry.currentOrder,
    state.cuts.map((cut) => cut.shotId),
  );

  const replacedDirection = feedback.notes.find(
    (note) => note.title === "Explore instead of run",
  );
  assert.equal(replacedDirection.retiredShotIds.length, 0);
  assert.ok(
    replacedDirection.retiredShotIds.every(
      (shotId) => !activeShotIds.has(shotId),
    ),
  );
});

test("edit feedback previews shot-order changes without overriding canonical truth", async () => {
  const [feedback, state, registry, tracker, api, styles] = await Promise.all([
    json("../data/feedback.json"),
    json("../public/data/state.json"),
    json("../data/canonical/shot-registry.json"),
    text("../app/feedback-tracker.tsx"),
    text("../scripts/local-api.mjs"),
    text("../app/globals.css"),
  ]);
  const edit = feedback.editNotes.find((note) => note.id === "edit-001");
  const flipBackEdit = feedback.editNotes.find(
    (note) => note.id === "edit-002",
  );
  const canonicalWindow = state.cuts.filter((cut) =>
    ["CUT-035", "CUT-036", "CUT-037"].includes(cut.id),
  );

  assert.equal(edit.title, "Swap CUT-035 and CUT-037");
  assert.equal(edit.status, "to-incorporate");
  assert.equal(edit.operation, "swap");
  assert.deepEqual(edit.shotIds, [
    "SHOT-ABE5DCD3DA6A",
    "SHOT-08C2B3387DC3",
  ]);
  assert.equal(flipBackEdit.title, "Flip CUT-037 and CUT-035 back");
  assert.equal(flipBackEdit.status, "to-incorporate");
  assert.equal(flipBackEdit.operation, "swap");
  assert.deepEqual(flipBackEdit.shotIds, [
    "SHOT-08C2B3387DC3",
    "SHOT-ABE5DCD3DA6A",
  ]);
  assert.match(flipBackEdit.noteDescription, /returns the feedback preview/i);
  assert.match(flipBackEdit.noteDescription, /preserving both editorial decisions/i);
  assert.deepEqual(
    canonicalWindow.map((cut) => cut.id),
    ["CUT-035", "CUT-036", "CUT-037"],
  );
  assert.deepEqual(
    registry.currentOrder.slice(34, 37),
    canonicalWindow.map((cut) => cut.shotId),
  );

  const firstPreviewWindow = [...canonicalWindow];
  [firstPreviewWindow[0], firstPreviewWindow[2]] = [
    firstPreviewWindow[2],
    firstPreviewWindow[0],
  ];
  assert.deepEqual(
    firstPreviewWindow.map((cut) => cut.id),
    ["CUT-037", "CUT-036", "CUT-035"],
  );
  const previewWindow = [...canonicalWindow];
  for (const note of feedback.editNotes.filter(
    (item) => item.status === "to-incorporate",
  )) {
    const firstIndex = previewWindow.findIndex(
      (cut) => cut.shotId === note.shotIds[0],
    );
    const secondIndex = previewWindow.findIndex(
      (cut) => cut.shotId === note.shotIds[1],
    );
    [previewWindow[firstIndex], previewWindow[secondIndex]] = [
      previewWindow[secondIndex],
      previewWindow[firstIndex],
    ];
  }
  assert.deepEqual(
    previewWindow.map((cut) => cut.id),
    ["CUT-035", "CUT-036", "CUT-037"],
  );
  assert.doesNotMatch(JSON.stringify(feedback.editNotes), /cutIds/);
  assert.match(tracker, /function applyEditFeedbackOrder/);
  assert.match(tracker, /feedbackScope === "edit" \? editOrderedCuts : cuts/);
  assert.match(tracker, /setFeedbackScope\("edit"\)/);
  assert.match(tracker, /EDIT PREVIEW/);
  assert.match(tracker, /Working order only/);
  assert.match(tracker, /Canonical cut IDs, timecodes, thumbnails, and provenance/);
  assert.match(tracker, /Edit position \{editPosition\}/);
  assert.match(tracker, /aria-label="Edit status"/);
  assert.match(api, /\["note", "parent", "general", "edit"\]/);
  assert.match(api, /feedback\.editNotes/);
  assert.match(api, /A swap edit must keep exactly two shot assignments/);
  assert.match(styles, /\.feedback-edit-preview\s*\{/);
  assert.match(styles, /\.feedback-cut-card\.edit-order-changed\s*\{/);
});

test("both UIs and the API use the same shot identity contract", async () => {
  const [atlas, feedback, api, scanner] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/feedback-tracker.tsx"),
    text("../scripts/local-api.mjs"),
    text("../scripts/scan.py"),
  ]);

  assert.match(atlas, /shotId: cut\.shotId/);
  assert.match(atlas, /pipelineAttachmentId\?: string/);
  assert.match(atlas, /cut\.shotId === selectedId/);
  assert.match(feedback, /record\.shotIds/);
  assert.match(feedback, /shotIds: nextShotIds/);
  assert.match(feedback, /data-shot-id=\{cut\.shotId\}/);
  assert.doesNotMatch(feedback, /\bcutIds\b/);
  assert.match(api, /SHOT_REGISTRY_PATH/);
  assert.match(api, /record\.shotIds = shotIds/);
  assert.match(api, /feedback\.generalNotes/);
  assert.match(api, /feedback\.editNotes/);
  assert.doesNotMatch(api, /record\.cutIds/);
  assert.match(scanner, /sync_generated_state\(state\)/);
  assert.ok(
    scanner.lastIndexOf("state = apply_source_corrections(state)") >
      scanner.indexOf("as_finishing_counts = apply_as_finishing_chronology("),
  );
});

test("dragging duplicates one shared feedback record onto another shot", async () => {
  const [tracker, styles] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    text("../app/globals.css"),
  ]);
  assert.match(tracker, /application\/x-paracosm-feedback-record/);
  assert.match(tracker, /dropRecordOnCut/);
  assert.match(tracker, /\/api\/feedback\/update/);
  assert.match(tracker, /shotIds: nextShotIds/);
  assert.doesNotMatch(tracker, /\/api\/feedback\/(create|duplicate)/);
  assert.match(
    styles,
    /\.feedback-cut-card\.drop-target \.feedback-cut-frame::after,[\s\S]*background:\s*rgba\(213, 213, 207, 0\.9\)/,
  );
});

test("the compact Notes index groups film-wide and specific directions by parent", async () => {
  const [tracker, styles] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(tracker, /className="feedback-notes-index"/);
  assert.match(tracker, /className="feedback-scope-tabs"/);
  assert.match(tracker, /setFeedbackScope\("notes"\)/);
  assert.match(tracker, /notesIndexCategories/);
  assert.match(tracker, /feedback-notes-index-contents/);
  assert.match(tracker, /openIndexedRecord\(item, cut\?\.shotId\)/);
  assert.match(tracker, /function scrollToFeedbackShot\(shotId: string\)/);
  assert.match(tracker, /window\.scrollTo\(\{/);
  assert.match(tracker, /frameTop - stickyBottom - 12/);
  assert.match(tracker, /kind: "general"/);
  assert.match(tracker, /openGeneralNote/);
  assert.match(
    tracker,
    /feedback\.generalNotes[\s\S]*filter\(\(note\) => note\.parentIds\.includes\(parent\.id\)\)/,
  );
  assert.doesNotMatch(tracker, /label:\s*"General"/);
  assert.match(tracker, /Drag \$\{recordTitle\(item\)\} onto a shot/);
  assert.match(tracker, /function splitShotName/);
  assert.doesNotMatch(tracker, /feedback-notes-index-drag/);
  assert.match(tracker, /Not attached to any shots/);
  assert.doesNotMatch(tracker, /className="feedback-hero"/);
  assert.doesNotMatch(tracker, /className="parent-tier-grid"/);
  assert.match(styles, /\.feedback-notes-index-bar\s*\{/);
  assert.match(styles, /\.feedback-notes-index-list\s*\{[^}]*max-height:/s);
});

test("one Feedback scope drives both the note list and thumbnail grid", async () => {
  const [tracker, feedback] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    json("../data/feedback.json"),
  ]);
  const hair = feedback.parents.find((parent) => parent.id === "hair");

  assert.equal(hair.shotIds.length, 4);
  assert.match(tracker, /const \[feedbackScope, setFeedbackScope\]/);
  assert.match(
    tracker,
    /const \[feedbackNavExpanded, setFeedbackNavExpanded\] = useState\(false\)/,
  );
  assert.match(tracker, /setFeedbackScope\("all"\);/);
  assert.match(
    tracker,
    /className=\{feedbackScope === "notes" \? "active" : ""\}[\s\S]*?onClick=\{\(\) => \{\s*setFeedbackNavPinned\(false\);\s*setFeedbackScope\("notes"\);/,
  );
  assert.match(
    tracker,
    /className=\{feedbackScope === "edit" \? "active" : ""\}[\s\S]*?setFeedbackScope\("edit"\)/,
  );
  assert.match(
    tracker,
    /\{feedbackNavExpanded && expandedIndexCategory && \(/,
  );
  assert.match(tracker, /className="feedback-nav-collapse"/);
  assert.match(tracker, /Collapse feedback navigation/);
  assert.match(tracker, /Expand feedback navigation/);
  assert.match(tracker, /feedbackScope === "notes" && !records\.length/);
  assert.match(
    tracker,
    /key=\{category\.id\}[\s\S]*?onClick=\{\(\) => \{\s*setFeedbackNavPinned\(false\);\s*setFeedbackScope\(category\.id\);/,
  );
  assert.match(
    tracker,
    /feedbackScope === "all"[\s\S]*className="feedback-nav-count"[\s\S]*filteredCuts\.length/,
  );
  assert.match(
    tracker,
    /feedbackScope === "notes"[\s\S]*className="feedback-nav-count"[\s\S]*filteredCuts\.length/,
  );
  assert.match(
    tracker,
    /feedbackScope === category\.id[\s\S]*className="feedback-nav-count"[\s\S]*filteredCuts\.length/,
  );
  assert.match(tracker, /filteredCuts[\s\S]*feedbackScope/);
  assert.match(tracker, /parent\.shotIds\.length[\s\S]*kind: "parent"/);
  assert.match(tracker, /visibleIndexRows/);
  assert.doesNotMatch(tracker, /All cuts/);
  assert.doesNotMatch(tracker, /With feedback/);
  assert.doesNotMatch(tracker, /feedback-notes-index-total/);
  assert.doesNotMatch(tracker, /Edit category/);
  assert.match(
    await text("../app/globals.css"),
    /\.feedback-nav-count\s*\{[^}]*font-variant-numeric:\s*tabular-nums/s,
  );
});

test("Feedback navigation pins only for indexed shot jumps", async () => {
  const [tracker, styles] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    text("../app/globals.css"),
  ]);
  const stickyNav = tracker.indexOf("feedback-sticky-nav");
  const search = tracker.indexOf(
    'className="feedback-search feedback-top-search"',
  );
  const chapter = tracker.indexOf(
    'className="feedback-section-filter feedback-top-chapter"',
  );
  const list = tracker.indexOf('className="feedback-notes-index"');
  const noteTitle = tracker.indexOf("<strong>{recordTitle(item)}</strong>");
  const badge = tracker.indexOf("<i>{recordBadge(item)}</i>", noteTitle);
  const duration = tracker.indexOf("cut.duration.toFixed(1)", badge);

  assert.ok(stickyNav >= 0);
  assert.ok(search > stickyNav);
  assert.ok(chapter > search);
  assert.ok(list > chapter);
  assert.ok(noteTitle >= 0);
  assert.ok(badge > noteTitle);
  assert.ok(duration > badge);
  assert.match(
    tracker,
    /feedback-sticky-nav[\s\S]*className="feedback-notes-index"[\s\S]*className="feedback-cut-grid"/,
  );
  assert.match(tracker, /const \[feedbackNavPinned, setFeedbackNavPinned\]/);
  assert.match(tracker, /setFeedbackNavPinned\(true\);[\s\S]*openCut\(shotId\)/);
  assert.match(tracker, /toggleCutNotes[\s\S]*setFeedbackNavPinned\(false\)/);
  assert.match(tracker, /openAppliedShot[\s\S]*setFeedbackNavPinned\(false\)/);
  assert.doesNotMatch(tracker, /className="feedback-controls"/);
  assert.match(
    styles,
    /Keep the complete Feedback navigation[\s\S]*\.feedback-sticky-nav\s*\{[^}]*position:\s*static[^}]*top:\s*auto[^}]*margin-bottom:\s*16px/s,
  );
  assert.match(
    styles,
    /Keep the complete Feedback navigation[\s\S]*\.feedback-sticky-nav\.pinned\s*\{[^}]*position:\s*sticky[^}]*top:\s*64px/s,
  );
  assert.match(
    styles,
    /Feedback navigation and note index[\s\S]*\.feedback-notes-index-list\s*\{[^}]*max-height:\s*224px/s,
  );
  assert.match(
    styles,
    /Feedback navigation and note index[\s\S]*\.feedback-notes-index-row > button\s*\{[^}]*min-height:\s*32px/s,
  );
  assert.match(
    styles,
    /Feedback navigation and note index[\s\S]*\.feedback-nav-collapse\s*\{[^}]*width:\s*24px[^}]*min-height:\s*40px/s,
  );
  assert.match(
    styles,
    /\.feedback-sticky-nav \.feedback-notes-index\s*\{[^}]*margin:\s*0/s,
  );
  assert.match(
    styles,
    /\.feedback-main:has\(\.feedback-sticky-nav\.pinned \.feedback-notes-index\)[\s\S]*scroll-margin-top:\s*330px/,
  );
  assert.match(tracker, /placeholder="Search"/);
  assert.match(tracker, /<option value="ALL">Chapter<\/option>/);
  assert.doesNotMatch(tracker, />FILM WIDE</);
  assert.doesNotMatch(tracker, />Unassigned</);
  assert.match(
    tracker,
    /aria-current=\{\s*selectedShotId === cut\.shotId \? "true" : undefined/,
  );
  assert.match(
    styles,
    /Indexed Feedback destinations[\s\S]*\.feedback-cut-card\.selected \.shot-card-primary > strong\s*\{[^}]*text-decoration-line:\s*underline/,
  );
  assert.doesNotMatch(
    styles,
    /\.feedback-cut-card\.selected \.feedback-cut-frame::before/,
  );
});

test("camera directions are a first-class category with no orphan notes", async () => {
  const feedback = await json("../data/feedback.json");
  const cameraNotes = feedback.notes.filter((note) =>
    note.parentIds.includes("camera"),
  );

  assert.deepEqual(
    cameraNotes.map((note) => note.title),
    ["Start close, then reveal the world", "Keep the yarn ball incidental"],
  );
  assert.ok(feedback.parents.some((parent) => parent.name === "Camera"));
  assert.ok(feedback.notes.every((note) => note.parentIds.length > 0));
});

test("the two film-wide facial directions remain one lossless shared note", async () => {
  const feedback = await json("../data/feedback.json");
  const note = feedback.generalNotes.find(
    (item) => item.id === "general-facial-expression",
  );

  assert.equal(note.title, "More Facial Expression");
  assert.deepEqual(note.sourceIds, ["2", "1"]);
  assert.match(note.noteDescription, /single facial expression across the entire film/);
  assert.match(note.noteDescription, /character's eyes do not move/);
  assert.match(note.dependency, /expression reference for each emotional beat/);
  assert.match(note.dependency, /previously-approved eye design/);
  assert.ok(
    !feedback.generalNotes.some((item) => item.id === "general-eye-motion"),
  );
});

test("note names and descriptions remain editable on the shared record", async () => {
  const [tracker, api] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    text("../scripts/local-api.mjs"),
  ]);
  assert.match(tracker, /className="feedback-note-editor-head"/);
  assert.match(tracker, /<span>Note :<\/span>/);
  assert.match(tracker, /<textarea[\s\S]*rows=\{1\}[\s\S]*wrap="soft"/);
  assert.match(tracker, /aria-label="Note headline"/);
  assert.match(tracker, /<i>\{selectedRecordCategory\}<\/i>/);
  assert.match(tracker, /className="feedback-note-parent"/);
  assert.match(tracker, /aria-label="Parent"/);
  assert.doesNotMatch(tracker, /<span>Parent<\/span>/);
  assert.match(
    tracker,
    /setDraftParentIds\(\s*initial\.kind === "note" \? initial\.record\.parentIds : \[\],?\s*\)/,
  );
  assert.match(
    tracker,
    /selectedRecord\.kind === "note" && !draftParentIds\.length/,
  );
  assert.match(tracker, /const effectiveDraftParentIds =/);
  assert.match(tracker, /setDraftParentIds\(\[event\.target\.value\]\)/);
  assert.match(tracker, /parentIds:\s*selectedRecord\.kind === "note"/);
  assert.match(tracker, /<b>\{recordBadge\(selectedRecord\)\}<\/b>/);
  assert.match(tracker, /<span>Note Description<\/span>/);
  assert.match(tracker, /<span>Dependency<\/span>/);
  assert.match(tracker, /title:\s*selectedRecord\.kind !== "parent"/);
  assert.doesNotMatch(tracker, /className="feedback-identity-fields"/);
  assert.doesNotMatch(tracker, />Auto-save</);
  assert.doesNotMatch(tracker, />Saved</);
  assert.match(tracker, /saveState === "error"/);
  assert.match(api, /record\.title = body\.title\.trim\(\)/);
  assert.match(api, /record\.parentIds = parentIds/);
  assert.match(api, /Unknown feedback parent/);
  assert.doesNotMatch(api, /feedback\.notes\.push/);
});

test("the Feedback inspector uses compact self-sizing note fields", async () => {
  const [tracker, styles] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(tracker, /<span>Notes<\/span>/);
  assert.doesNotMatch(tracker, /Notes on this cut/);
  assert.doesNotMatch(tracker, /Drag a note onto another cut/);
  assert.match(styles, /\.feedback-edit-field textarea\s*\{[^}]*field-sizing:\s*content/s);
  assert.match(styles, /\.feedback-edit-field textarea\s*\{[^}]*max-height:\s*220px/s);
  assert.match(
    styles,
    /Right-panel Notes navigation[\s\S]*\.feedback-record-list \.feedback-inspector-heading\s*\{[^}]*min-height:\s*40px/,
  );
  assert.match(
    styles,
    /Right-panel Notes navigation[\s\S]*\.feedback-record-row,[\s\S]*min-height:\s*32px/,
  );
  assert.match(
    styles,
    /Right-panel Notes navigation[\s\S]*\.feedback-record-row \.feedback-record-select span\s*\{[^}]*font:\s*440 10\.5px/,
  );
  assert.match(
    styles,
    /Right-panel Notes navigation[\s\S]*\.feedback-record-row \.feedback-record-select i\s*\{[^}]*font:\s*600 7\.5px/,
  );
  assert.match(
    styles,
    /Feedback note editor[\s\S]*\.feedback-note-editor-head\s*\{[^}]*grid-template-columns:\s*auto minmax\(0, 1fr\) auto/,
  );
  assert.match(
    styles,
    /Feedback note editor[\s\S]*\.feedback-note-editor-head > textarea,[\s\S]*font:\s*450 12px/,
  );
  assert.match(
    styles,
    /\.feedback-note-editor-head > textarea\s*\{[^}]*field-sizing:\s*content[^}]*resize:\s*none/s,
  );
  assert.match(
    styles,
    /\.feedback-note-editor-head > i\s*\{[^}]*max-width:\s*none[^}]*overflow:\s*visible[^}]*text-overflow:\s*clip/s,
  );
  assert.match(
    styles,
    /\.feedback-note-parent > select\s*\{[^}]*width:\s*max-content[^}]*border-bottom:\s*1px solid var\(--line\)/s,
  );
});

test("Feedback edits auto-save and shot assignments are directly interactive", async () => {
  const [tracker, styles] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(tracker, /autoSaveQueueRef/);
  assert.match(tracker, /window\.setTimeout\(\(\) =>/);
  assert.match(tracker, /\/api\/feedback\/update/);
  assert.match(tracker, /Saved automatically/);
  assert.match(tracker, /function openAppliedShot\(shotId: string\)/);
  assert.match(tracker, /className="feedback-assigned-shot-open"[\s\S]*openAppliedShot\(shotId\)/);
  assert.match(tracker, /className="feedback-assigned-shot-remove"[\s\S]*toggleShotAssignment\(shotId\)/);
  assert.match(tracker, /title=\{`Remove \$\{cut \? cut\.id : shotId\}`\}/);
  assert.match(tracker, /placeholder="Search shots"/);
  assert.match(
    tracker,
    /className="feedback-assignment-picker"[\s\S]*src=\{cut\.thumbnail\}[\s\S]*loading="lazy"/,
  );
  assert.doesNotMatch(tracker, /Cut, shot, chapter, timecode/);
  assert.doesNotMatch(
    tracker.slice(
      tracker.indexOf('className="feedback-assignment-picker"'),
      tracker.indexOf('className="feedback-source-context"'),
    ),
    /cut\.timecode/,
  );
  assert.doesNotMatch(tracker, />Save changes</);
  assert.doesNotMatch(tracker, /Change shots/);
  assert.doesNotMatch(tracker, /Original spreadsheet context/);
  assert.doesNotMatch(tracker, /Unabridged fields from/);
  assert.match(tracker, /<summary>Source note \{row\.id\}<\/summary>/);
  assert.match(styles, /\.feedback-assigned-shot-open\s*\{/);
  assert.match(styles, /\.feedback-assigned-shot-remove\s*\{/);
  assert.match(styles, /\.feedback-assignment-add\s*\{/);
  assert.match(styles, /\.feedback-assignment-picker > div > button\s*\{/);
  assert.match(
    styles,
    /\.feedback-assignment-picker > div > button > img\s*\{[^}]*width:\s*64px[^}]*aspect-ratio:\s*16 \/ 9/s,
  );
});

test("Feedback keeps the large scrubber in the inspector", async () => {
  const [tracker, styles] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    text("../app/globals.css"),
  ]);
  assert.doesNotMatch(tracker, /expandedShotId|toggleExpandedCut/);
  assert.match(tracker, /feedback-inspector-frame/);
  assert.match(tracker, /inspectorScrubVideoRef/);
  assert.match(tracker, /updateInspectorScrub/);
  assert.match(tracker, /selectedCut\.scrubProxy/);
  assert.match(styles, /\.feedback-inspector-frame\s*\{/);
  assert.match(styles, /\.feedback-inspector-frame\.scrubbable/);
  assert.doesNotMatch(styles, /\.feedback-cut-card\.expanded/);
});

test("Feedback cards put the note count left and categories right", async () => {
  const [tracker, styles] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    text("../app/globals.css"),
  ]);
  const noteCount = tracker.indexOf('className="note-total"');
  const categories = tracker.indexOf('className="feedback-card-categories"');

  assert.ok(noteCount >= 0);
  assert.ok(categories > noteCount);
  assert.match(styles, /\.feedback-card-categories\s*\{[^}]*margin-left:\s*auto/s);
  assert.match(styles, /\.feedback-card-categories\s*\{[^}]*justify-content:\s*flex-end/s);
});

test("Feedback shot cards expand a compact name and tier note list", async () => {
  const [tracker, styles] = await Promise.all([
    text("../app/feedback-tracker.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(tracker, /expandedNotesShotId/);
  assert.match(tracker, /toggleCutNotes/);
  assert.match(
    tracker,
    /const \[inspectorOpen, setInspectorOpen\] = useState\(false\)/,
  );
  assert.match(
    tracker,
    /function toggleCutNotes[\s\S]*const first = recordsByShot\.get\(shotId\)\?\.\[0\];[\s\S]*selectFeedbackRecord\(first \|\| null\);[\s\S]*setExpandedNotesShotId/,
  );
  const toggleCutNotes = tracker.slice(
    tracker.indexOf("function toggleCutNotes"),
    tracker.indexOf("function openGeneralNote"),
  );
  assert.doesNotMatch(toggleCutNotes, /setInspectorOpen/);
  assert.match(tracker, /className="feedback-card-note-drawer"/);
  assert.match(
    tracker,
    /className="feedback-card-note"[\s\S]*openCut\(cut\.shotId\);[\s\S]*selectFeedbackRecord\(item\)/,
  );
  assert.match(tracker, /<span>\{recordTitle\(item\)\}<\/span>/);
  assert.match(tracker, /<i>\{recordBadge\(item\)\}<\/i>/);
  assert.match(styles, /\.feedback-card-note-drawer\s*\{/);
  assert.match(styles, /\.feedback-card-note\s*\{/);
});

test("Pipeline and Feedback share the editorial shot-card hierarchy", async () => {
  const [atlas, feedback, mockup, card, styles, naming] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/feedback-tracker.tsx"),
    text("../app/mockup-gallery.tsx"),
    text("../app/shot-card-details.tsx"),
    text("../app/globals.css"),
    import("../app/shot-card-name.ts"),
  ]);

  assert.match(atlas, /<ShotCardDetails/);
  assert.match(feedback, /<ShotCardDetails/);
  assert.match(mockup, /<ShotCardDetails/);
  assert.match(card, /className="shot-card-primary"/);
  assert.match(card, /className="shot-card-secondary"/);
  assert.match(card, /duration\.toFixed\(1\)/);
  assert.match(styles, /--black:\s*#ffffff/);
  assert.match(styles, /\.cut-card,\s*\n\.feedback-cut-card\s*\{/);

  assert.equal(
    naming.deriveShotDisplayName({
      chapter: "TH",
      plannedShotId: "3THB",
      sourceClipName: "3B_Walk_i40_0400.png",
      plannedFileName: "3A 1121 intro walk jd",
    }),
    "3B Walk",
  );
  assert.equal(
    naming.deriveShotDisplayName({
      chapter: "ND",
      plannedShotId: "1NDB1",
      plannedFileName: "1B 1121 intro AS CU",
      plannedAction: "Leans at sink, eyes welling up",
      plannedDescription:
        "ABBY at the sink. Tears slowly form in her eyes. Can extend to :27 if works as one shot.",
    }),
    "1B1 Intro CU",
  );
});

test("Pipeline can filter by authoritative C4D states and switch to a thumbnail list", async () => {
  const [atlas, styles] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(atlas, /const \[c4dStatusFilter, setC4dStatusFilter\]/);
  assert.match(atlas, /resolveC4DEvidenceStatus\(cut\)\.tone === c4dStatusFilter/);
  assert.match(atlas, /aria-label="Filter cuts by C4D state"/);
  assert.match(atlas, /<option value="all">ALL<\/option>/);
  assert.match(atlas, /<option value="redshift-verified">GREEN<\/option>/);
  assert.match(atlas, /<option value="camera-verified">YELLOW<\/option>/);
  assert.match(atlas, /<option value="file-confirmed">BLACK<\/option>/);
  assert.match(atlas, /<option value="unconfirmed">GRAY<\/option>/);
  assert.match(atlas, /<option value="preview">PREVIEW<\/option>/);
  assert.match(atlas, /useState<C4DNavMode>\("preview"\)/);
  assert.match(
    atlas,
    /c4dStatusFilter === "preview" \|\|[\s\S]*resolveC4DEvidenceStatus\(cut\)\.tone === c4dStatusFilter/,
  );
  assert.match(atlas, /bestC4DPreviewImage\(cut\)/);
  assert.match(
    atlas,
    /authoritativeCameraProof[\s\S]*cameraProofRendered === true[\s\S]*publicEvidenceImagePath\(cut\.c4dVerification\.cameraProof\)/,
  );
  assert.match(
    atlas,
    /authoritativeCameraProof[\s\S]*!isCompositeEvidenceImage\(authoritativeCameraProof\)[\s\S]*return authoritativeCameraProof/,
  );
  assert.match(atlas, /data-c4d-preview=/);
  assert.match(
    atlas,
    /alt=\{`Authoritative C4D proof for \$\{cut\.id\}`\}/,
  );
  assert.match(atlas, /\? "authoritative"[\s\S]*: "best-available"/);
  assert.match(atlas, /eligibleColorPreview/);
  assert.match(atlas, /isFreshFullColorEvidence/);
  assert.ok(atlas.includes("/(?:^|[._-])pair(?:[._-]|$)/i"));
  assert.ok(
    atlas.includes(
      "/(?:^|[._-])(?:vs|side[-_]by[-_]side|split[-_]screen)(?:[._-]|$)/i",
    ),
  );
  assert.match(atlas, /browserEvidenceImageOverrides/);
  assert.doesNotMatch(
    atlas,
    /\(\?:contact\|comparison\|composite\|pair\|sheet\)/,
  );
  assert.match(atlas, /key=\{previewImage\}/);
  assert.doesNotMatch(
    atlas,
    /eligibleColorPreview[\s\S]*proofStatus\?\.[\s\S]*includes\("rejected"\)/,
  );
  assert.match(atlas, /className="c4d-preview-missing"/);
  assert.match(
    atlas,
    /setC4dStatusFilter\([\s\S]*setScrub\(null\);[\s\S]*setScrubReadyShotId\(""\)/,
  );
  assert.match(
    atlas,
    /Move left to right to reveal and scrub the original shot/,
  );
  assert.match(
    atlas,
    /!node\.productionSourceReference[\s\S]*!node\.historicalProductionReference[\s\S]*!isCompositeEvidenceImage/,
  );
  assert.doesNotMatch(atlas, /Green first|Yellow first|Black first|Grey first/);
  assert.match(atlas, /setView\("list"\)/);
  assert.match(atlas, /aria-label="List view"/);
  assert.match(styles, /\.cut-grid\.cut-list\s*\{[\s\S]*grid-template-columns:\s*1fr/);
  assert.match(styles, /\.cut-list \.cut-card-trigger[\s\S]*grid-template-columns:\s*112px minmax\(0, 1fr\)/);
  assert.match(styles, /\.cut-list \.cut-frame[\s\S]*aspect-ratio:\s*16\s*\/\s*9/);
  assert.match(styles, /\.c4d-preview-missing\s*\{/);
});

test("Pipeline cards open the right inspector without a thumbnail drawer", async () => {
  const [atlas, feedback, styles] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/feedback-tracker.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(atlas, /selectedShotName/);
  assert.match(feedback, /feedback-cut-inspector-head[\s\S]*<ShotCardDetails/);
  assert.doesNotMatch(atlas, /expandedShotId|className="cut-proof-drawer"/);
  assert.match(
    atlas,
    /className="cut-card-trigger"[\s\S]*setSelectedId\(cut\.shotId\);[\s\S]*setDetailOpen\(true\)/,
  );
  assert.match(
    styles,
    /\.pipeline-inspector \.detail-evidence-thumb,[\s\S]*width:\s*100%/,
  );
  assert.doesNotMatch(styles, /\.cut-source-links button::before/);
  assert.doesNotMatch(styles, /content:\s*"— "/);
});

test("Pipeline C4D color follows confirmed file and proof renderer", async () => {
  const [atlas, feedback, links, styles, workerRules] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/feedback-tracker.tsx"),
    text("../app/source-application-links.tsx"),
    text("../app/globals.css"),
    text("../AGENTS.md"),
  ]);

  assert.match(atlas, /<SourceApplicationLinks/);
  assert.match(feedback, /<SourceApplicationLinks/);
  assert.match(
    atlas,
    /<FeedbackTracker[\s\S]*lineage:\s*cut\.lineage,[\s\S]*c4dVerification:\s*cut\.c4dVerification/,
  );
  assert.match(
    atlas,
    /preservedCameraProofRendered[\s\S]*cameraProofRendered:\s*preservedCameraProofRendered/,
  );
  assert.doesNotMatch(atlas, /function c4dCameraProofTone/);
  assert.doesNotMatch(feedback, /function c4dCameraProofTone/);
  assert.match(
    links,
    /function c4dCameraProofTone\(\s*cut: SourceApplicationCut/,
  );
  assert.match(
    links,
    /verification\?\.checks\?\.cameraProofRendered === true/,
  );
  assert.match(
    links,
    /c4dNode\?\.evidence === "confirmed"/,
  );
  assert.match(links, /cameraResult\.startsWith\("match_"\)/);
  assert.match(
    links,
    /node\.comparisonImage === verification\?\.cameraProof/,
  );
  assert.match(links, /activeProof\?\.evidence === "confirmed"/);
  assert.match(links, /activeProof\.proofStatus\?\.startsWith\("rendered"\)/);
  assert.doesNotMatch(
    links,
    /verification\.cameraName,[\s\S]*hasRedshiftProof/,
  );
  assert.match(links, /activeProof\?\.redshiftProof === true/);
  assert.match(links, /activeProof\?\.fullColorProof === true/);
  assert.match(links, /hasFullColorRedshiftProof/);
  assert.match(links, /hasHardwareProof/);
  assert.match(links, /proofSupportsCameraMatch/);
  assert.match(links, /`c4d-camera-\$\{application\.proofTone\}`/);
  assert.match(links, /data-camera-proof=\{application\.proofTone\}/);
  assert.match(links, />\s*\{application\.label\}\s*<\/button>/);
  assert.doesNotMatch(feedback, /No feedback/i);
  assert.match(
    styles,
    /\.c4d-camera-redshift-verified[\s\S]*color:\s*#2f7d4d/,
  );
  assert.match(
    styles,
    /\.c4d-camera-camera-verified[\s\S]*color:\s*#9a6200/,
  );
  assert.match(
    workerRules,
    /green only when the selected C4D file is confirmed[\s\S]*Redshift/,
  );
  assert.match(
    workerRules,
    /yellow when the selected C4D file is confirmed[\s\S]*grey or neutral Redshift[\s\S]*Hardware Preview/,
  );
  assert.match(
    workerRules,
    /shared `SourceApplicationLinks` component/,
  );
});

test("all C4D button states pass the shared evidence contract", async () => {
  const [audit, state, atlas] = await Promise.all([
    json("../data/c4d-status-consistency-audit-20260728.json"),
    json("../public/data/state.json"),
    text("../app/provenance-atlas.tsx"),
  ]);

  assert.equal(audit.summary.pictureCuts, 85);
  assert.equal(audit.summary.inconsistentCuts, 0);
  assert.deepEqual(audit.inconsistentCutIds, []);
  const pictureToneCounts = audit.cuts
    .filter((cut) => cut.pictureCut)
    .reduce(
      (counts, cut) => {
        counts[cut.expectedTone] = (counts[cut.expectedTone] || 0) + 1;
        return counts;
      },
      {},
    );
  assert.deepEqual(audit.summary.countsByTone, pictureToneCounts);
  assert.equal(
    Object.values(audit.summary.countsByTone).reduce(
      (sum, count) => sum + count,
      0,
    ),
    85,
  );
  assert.ok(
    audit.cuts.every((cut) => cut.inconsistencies.length === 0),
  );

  const cut16Audit = audit.cuts.find((cut) => cut.cutId === "CUT-016");
  assert.equal(cut16Audit?.expectedTone, "unconfirmed");
  assert.equal(cut16Audit?.cameraImageRole, "nonqualifying_camera_test");
  assert.equal(cut16Audit?.processImageCount, 18);
  const cut16 = state.cuts.find((cut) => cut.id === "CUT-016");
  assert.equal(
    cut16?.lineage.filter((node) => node.kind === "process_image").length,
    16,
  );
  assert.match(
    cut16?.c4dVerification?.materialCompatibilityAudit?.outputPath || "",
    /redshift-material\.png$/,
  );
  assert.match(atlas, />Process images</);
  assert.match(atlas, /SOURCE FILE UNCONFIRMED/);
  assert.match(atlas, /FULL-COLOR REDSHIFT MATCH/);
  assert.match(
    atlas,
    /FULL-COLOR REDSHIFT CAMERA MATCH · STRICT GATE INCOMPLETE/,
  );
  assert.match(
    atlas,
    /GREY REDSHIFT CAMERA MATCH · \$\{selectedFreshFullColorRenderLabel\}/,
  );
  assert.match(
    atlas,
    /HARDWARE CAMERA MATCH · \$\{selectedFreshFullColorRenderLabel\}/,
  );
  assert.match(
    atlas,
    /GREY CAMERA MATCH · \$\{selectedFreshFullColorRenderLabel\}/,
  );
  assert.match(
    atlas,
    /Camera match confirmed; full-color materials and render-critical dependencies are not yet verified\./,
  );
  assert.match(atlas, /publicEvidenceImagePath/);

  const greenCuts = audit.cuts.filter(
    (cut) => cut.expectedTone === "redshift-verified",
  );
  assert.ok(greenCuts.every((cut) => cut.fullColorProof === true));
  for (const cutId of ["CUT-033", "CUT-034"]) {
    const cutAudit = audit.cuts.find((cut) => cut.cutId === cutId);
    assert.equal(cutAudit?.expectedTone, "camera-verified");
    assert.equal(cutAudit?.reason, "redshift_grey_camera_match");
    assert.equal(cutAudit?.fullColorProof, false);
    assert.equal(cutAudit?.cameraImageRole, "qualifying_camera_proof");
  }
  for (const cutId of ["CUT-019", "CUT-020"]) {
    const cutAudit = audit.cuts.find((cut) => cut.cutId === cutId);
    const cut = state.cuts.find((item) => item.id === cutId);
    assert.equal(cutAudit?.expectedTone, "camera-verified");
    assert.equal(cutAudit?.reason, "redshift_grey_camera_match");
    assert.equal(cutAudit?.fullColorProof, false);
    assert.equal(cutAudit?.cameraImageRole, "qualifying_camera_proof");
    assert.match(
      cut?.sourceSegments?.[0]?.renderDirectory || "",
      /_renders\/0211\/2C_mountains_Abby-Walking_v001$/,
    );
    assert.equal(
      cut?.lineage.some(
        (node) =>
          String(node.projectPath || node.path || "").includes(
            "2D_A_MTNS_Abby-Running_v002.c4d",
          ),
      ),
      false,
    );
    assert.equal(
      cut?.lineage.some(
        (node) =>
          node.kind === "camera_proof" &&
          node.cameraObjectPath === "2B abby walking" &&
          node.primaryRecoveryProof === true,
      ),
      true,
    );
  }
  const cut33 = state.cuts.find((cut) => cut.id === "CUT-033");
  const cut33Audit = audit.cuts.find((cut) => cut.cutId === "CUT-033");
  assert.equal(
    cut33?.c4dVerification?.cameraProof,
    cut33Audit?.cameraImage,
  );
  assert.equal(
    cut33?.lineage.some(
      (node) =>
        node.kind === "process_image" &&
        node.proofStatus === "rejected_cross_shot_or_added_hair_evidence",
    ),
    true,
  );
  const cut46Audit = audit.cuts.find((cut) => cut.cutId === "CUT-046");
  assert.equal(cut46Audit?.expectedTone, "camera-verified");
  assert.equal(cut46Audit?.fullColorProof, false);
  assert.equal(
    cut46Audit?.cameraImageRole,
    "qualifying_camera_proof",
  );
});

test("retained production frames are references, never camera proofs", async () => {
  const state = await json("../public/data/state.json");
  const isRetainedProductionFrame = (path) => {
    const normalized = String(path || "");
    return (
      normalized.startsWith("/archive/c4d-source-frames-20260726/") ||
      normalized.includes("__historical-redshift.")
    );
  };
  const productionReferences = state.cuts.flatMap((cut) =>
    cut.lineage.filter((node) => node.productionSourceReference),
  );

  assert.ok(productionReferences.length > 0);
  assert.ok(
    productionReferences.every(
      (node) =>
        node.kind === "render_reference" &&
        isRetainedProductionFrame(node.comparisonImage),
    ),
  );
  assert.deepEqual(
    state.cuts
      .filter((cut) =>
        isRetainedProductionFrame(cut.c4dVerification?.cameraProof),
      )
      .map((cut) => cut.id),
    [],
  );
  assert.deepEqual(
    state.cuts
      .filter((cut) =>
        cut.lineage.some(
          (node) =>
            node.kind === "camera_proof" &&
            isRetainedProductionFrame(node.comparisonImage),
        ),
      )
      .map((cut) => cut.id),
    [],
  );
  const cut5 = state.cuts.find((cut) => cut.id === "CUT-005");
  assert.match(
    cut5?.c4dVerification?.cameraProof || "",
    /\/archive\/redshift-mainframe-recovery-20260730\/CUT-005\//,
  );
  assert.equal(cut5?.c4dVerification?.checks?.cameraProofRendered, true);
  assert.equal(cut5?.c4dVerification?.checks?.cameraProofMatched, true);
  assert.equal(
    isRetainedProductionFrame(cut5?.c4dVerification?.cameraProof),
    false,
  );
});

test("Pipeline inspector follows the compact review hierarchy", async () => {
  const [atlas, styles, localApi] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/globals.css"),
    text("../scripts/local-api.mjs"),
  ]);
  const hero = atlas.indexOf('className="pipeline-detail-hero"');
  const shotlist = atlas.indexOf(
    'className="planned-shot pipeline-flow-section"',
  );
  const camera = atlas.indexOf(
    'className="pipeline-camera-proof pipeline-flow-section"',
  );
  const processImages = atlas.indexOf(
    'className="pipeline-process-images pipeline-flow-section"',
  );
  const source = atlas.indexOf(
    'className="pipeline-canonical-source pipeline-flow-section"',
  );
  const c4d = atlas.indexOf("c4d-linkage-panel");

  assert.ok(hero >= 0);
  assert.ok(shotlist > hero);
  assert.ok(camera > shotlist);
  assert.ok(processImages > camera);
  assert.ok(source > processImages);
  assert.ok(c4d > source);
  assert.match(atlas, /detailScrubVideoRef/);
  assert.match(atlas, /updateDetailScrub/);
  assert.match(atlas, /detail-panel pipeline-inspector/);
  assert.match(atlas, /pipeline-detail-hero[\s\S]*<ShotCardDetails/);
  assert.match(atlas, /className="pipeline-c4d-dependency"/);
  assert.match(atlas, /className="c4d-deep-audit"/);
  assert.match(
    atlas,
    /async function revealAndCopyPath[\s\S]*post\("\/api\/reveal", \{ path, copyPath: true \}\)/,
  );
  assert.match(
    atlas,
    /className="path-button canonical-source-path"[\s\S]*revealAndCopyPath\(segment\.sourcePath\)/,
  );
  assert.match(
    atlas,
    /canonical-source-path"[\s\S]*sourcePathParts\.leading[\s\S]*sourcePathParts\.ending/,
  );
  assert.doesNotMatch(atlas, /expandedDetailImages/);
  assert.doesNotMatch(atlas, /toggleDetailImage/);
  assert.doesNotMatch(atlas, /className="detail-media-preview"/);
  assert.match(atlas, /compactC4DElementLabel\(key\)/);
  assert.match(styles, /\.pipeline-detail-hero\s*\{[^}]*order:\s*0/s);
  assert.match(styles, /\.c4d-linkage-panel\s*\{[^}]*order:\s*40/s);
  assert.match(
    styles,
    /\.pipeline-source-summary article\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/s,
  );
  assert.match(
    styles,
    /\.pipeline-source-summary \.path-button\s*\{[^}]*width:\s*100%[^}]*max-width:\s*none/s,
  );
  assert.match(
    styles,
    /\.canonical-source-path > span\s*\{[^}]*direction:\s*rtl[^}]*text-overflow:\s*ellipsis/s,
  );
  assert.match(
    localApi,
    /spawn\("open", \["-R", body\.path\][\s\S]*body\.copyPath[\s\S]*copyToClipboard\(clipboardValue\)/,
  );
  assert.match(
    styles,
    /\.pipeline-inspector \.pipeline-proof-row\s*\{[\s\S]*display:\s*block/,
  );
  assert.match(
    styles,
    /\.pipeline-inspector \.detail-evidence-thumb,[\s\S]*width:\s*100%/,
  );
  assert.match(
    styles,
    /\.pipeline-inspector \.c4d-visual-grid\s*\{[\s\S]*display:\s*flex/,
  );
  assert.match(
    styles,
    /\.pipeline-inspector \.manual-trim-grid\s*\{[\s\S]*grid-template-columns:\s*1fr/,
  );
  assert.match(styles, /cursor:\s*zoom-in/);
  assert.doesNotMatch(styles, /\.detail-media-preview\s*\{/);
  assert.match(
    styles,
    /@media \(min-width: 761px\)[\s\S]*\.workspace\.left-open\.right-open\s*\{[\s\S]*height:\s*calc\(100vh - 64px\);[\s\S]*overflow:\s*hidden;/,
  );
  assert.match(
    styles,
    /@media \(min-width: 761px\)[\s\S]*\.cut-browser\s*\{[\s\S]*overflow-y:\s*auto;/,
  );
  assert.match(
    styles,
    /@media \(min-width: 761px\)[\s\S]*\.detail-panel\s*\{[\s\S]*height:\s*100%;[\s\S]*overflow:\s*hidden;/,
  );
  assert.match(
    styles,
    /@media \(min-width: 761px\)[\s\S]*\.detail-panel-content\s*\{[\s\S]*overflow-y:\s*auto;/,
  );
  assert.match(
    styles,
    /\.c4d-visual-grid article span,[\s\S]*text-overflow:\s*ellipsis/,
  );
});

test("right-inspector evidence images open a large transparent lightbox", async () => {
  const [atlas, styles] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(atlas, /function EvidenceImageButton/);
  assert.match(atlas, /aria-label=\{`Open large image:/);
  assert.match(atlas, /className="inspector-image-lightbox"/);
  assert.match(atlas, /role="dialog"/);
  assert.match(atlas, /aria-modal="true"/);
  assert.match(atlas, /event\.stopImmediatePropagation\(\)/);
  assert.doesNotMatch(atlas, /aria-label="Close large image"/);
  assert.match(
    atlas,
    /insideRenderedImage[\s\S]*if \(insideRenderedImage\) return;/,
  );
  assert.match(atlas, /target\.naturalWidth \* scale/);
  assert.match(
    styles,
    /\.pipeline-inspector \.detail-evidence-thumb,[\s\S]*background:\s*transparent/,
  );
  assert.match(
    styles,
    /\.pipeline-inspector \.detail-evidence-thumb img,[\s\S]*background:\s*transparent/,
  );
  assert.match(
    styles,
    /\.inspector-image-lightbox\s*\{[\s\S]*position:\s*fixed[\s\S]*inset:\s*0/,
  );
  assert.match(
    styles,
    /\.inspector-image-lightbox figure > img\s*\{[\s\S]*object-fit:\s*contain/,
  );
});

test("Ground Truth lives on the Paracosm title without a Reference rail", async () => {
  const [atlas, styles] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/globals.css"),
  ]);

  assert.match(atlas, /className="brand-ground-truth"/);
  assert.match(atlas, /href=\{data\.groundTruth\.frameIoUrl\}/);
  assert.doesNotMatch(atlas, /className=\{`source-rail/);
  assert.doesNotMatch(atlas, /railOpen|setRailOpen|setEvidence/);
  assert.match(
    styles,
    /\.workspace\.right-open,[\s\S]*grid-template-columns:\s*minmax\(520px,\s*1fr\)\s*500px/,
  );
});

test("hover scrubbers select media and seek ranges from the shot record", async () => {
  const [atlas, feedback] = await Promise.all([
    text("../app/provenance-atlas.tsx"),
    text("../app/feedback-tracker.tsx"),
  ]);
  for (const source of [atlas, feedback]) {
    assert.match(source, /Move left to right to scrub this cut/);
    assert.match(source, /cut\.scrubProxy/);
    assert.match(source, /cut\.scrubStart \?\? cut\.start/);
    assert.match(source, /cut\.scrubEnd \?\? cut\.end/);
    assert.match(
      source,
      /scrubStart \+ fraction \* \(lastFrame - scrubStart\)/,
    );
  }
});

test("Project Launcher contract and archive service stay local", async () => {
  const [plrc, api, scanner] = await Promise.all([
    json("../.plrc"),
    text("../scripts/local-api.mjs"),
    text("../scripts/scan.py"),
  ]);
  assert.equal(plrc.port, 3497);
  assert.deepEqual(plrc.startArgs, ["run", "dev"]);
  assert.match(api, /server\.listen\(PORT, "127\.0\.0\.1"/);
  assert.match(scanner, /readOnly/);
  assert.match(scanner, /provenance\.sqlite/);
  assert.doesNotMatch(scanner, /shutil\.(rmtree|copytree).*ABSOLUTELY/);
  assert.doesNotMatch(scanner, /\.unlink\(\).*ABSOLUTELY/);
  assert.ok(root);
});
