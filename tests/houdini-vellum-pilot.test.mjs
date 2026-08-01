import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function json(path) {
  return JSON.parse(await readFile(new URL(path, import.meta.url), "utf8"));
}

test("Navy Bubble Skirt publishes the reviewed Houdini Vellum pilot", async () => {
  const [registry, audit, source] = await Promise.all([
    json("../data/object-3d-versions.json"),
    json("../data/houdini-navy-bubble-vellum-pilot-20260728.json"),
    readFile(
      new URL("../app/object-asset-inspector.tsx", import.meta.url),
      "utf8",
    ),
  ]);

  const record = registry.objects.find(
    (candidate) => candidate.objectId === "navy-bubble-skirt",
  );
  assert.ok(record);
  assert.equal(record.clothProofs.length, 2);

  const blenderProof = record.clothProofs.find(
    (proof) => proof.id === "construction-static-proof-v1",
  );
  const houdiniProof = record.clothProofs.find(
    (proof) => proof.id === "houdini-vellum-pilot-v1",
  );
  assert.equal(blenderProof.status, "needs-prep");
  assert.equal(houdiniProof.status, "promising");
  assert.match(houdiniProof.solver, /Houdini 22 Vellum/);
  assert.match(houdiniProof.license, /non-commercial/);
  assert.equal(audit.generatedVideoCount, 0);

  await Promise.all(
    [
      houdiniProof.image,
      houdiniProof.closeupImage,
      houdiniProof.scene,
      houdiniProof.model,
    ].map((assetPath) =>
      access(new URL(`../public${assetPath}`, import.meta.url)),
    ),
  );

  assert.match(source, /proof\.license/);
  assert.match(source, /proof\.model/);
  assert.match(source, />\s*Geometry\s*</);
  assert.match(source, />\s*Scene\s*</);
});
