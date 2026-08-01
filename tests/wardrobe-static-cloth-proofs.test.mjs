import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function json(path) {
  return JSON.parse(await readFile(new URL(path, import.meta.url), "utf8"));
}

test("wardrobe cloth proofs use high-resolution stills without generic loops", async () => {
  const [manifest, audit, inspectorSource, styles] = await Promise.all([
    json("../data/object-3d-versions.json"),
    json("../data/wardrobe-reviewed-cloth-proofs-20260728.json"),
    readFile(
      new URL("../app/object-asset-inspector.tsx", import.meta.url),
      "utf8",
    ),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);

  assert.equal(audit.total, 66);
  assert.equal(audit.promisingCount, 44);
  assert.equal(audit.needsPrepCount, 22);
  assert.equal(audit.generatedVideoCount, 0);
  assert.ok(
    audit.proofs.every(
      (proof) =>
        proof.resolution === "1280 × 1280" &&
        proof.image.endsWith(".png") &&
        proof.closeupImage.endsWith(".png") &&
        !("video" in proof),
    ),
  );

  assert.equal(
    manifest.objects.filter((item) => item.clothProofs?.length).length,
    66,
  );
  assert.equal(
    manifest.objects.flatMap((item) => item.simulations || []).filter(
      (simulation) => simulation.id === "material-aware-sphere-v1",
    ).length,
    0,
  );
  assert.equal(
    manifest.objects.find((item) => item.objectId === "red-corset-top")
      ?.simulations?.length,
    2,
  );

  await Promise.all(
    audit.proofs.flatMap((proof) => [
      access(new URL(`../public${proof.image}`, import.meta.url)),
      access(new URL(`../public${proof.closeupImage}`, import.meta.url)),
      access(new URL(`../public${proof.scene}`, import.meta.url)),
    ]),
  );

  assert.match(inspectorSource, />Cloth proof</);
  assert.match(inspectorSource, /High-res static/);
  assert.match(inspectorSource, /proof\.image/);
  assert.match(inspectorSource, /proof\.closeupImage/);
  assert.match(inspectorSource, />Closeup</);
  assert.match(inspectorSource, /Needs mesh prep/);
  assert.match(styles, /\.object-cloth-proof-image-list\s*\{/);
  assert.match(styles, /\.object-cloth-proof-image img\s*\{/);
  assert.match(styles, /\.object-cloth-proof-links\.has-closeup\s*\{/);
  assert.match(styles, /\.object-cloth-proof-status\.is-promising\s*\{/);
});
