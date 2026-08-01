import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function json(path) {
  return JSON.parse(await readFile(new URL(path, import.meta.url), "utf8"));
}

test("the complete reviewed Houdini rescue batch is published as static proofs", async () => {
  const [batch, review, registry, sheets] = await Promise.all([
    json("../data/houdini-wardrobe-rescue-batch-20260728.json"),
    json("../data/houdini-wardrobe-rescue-reviewed-20260728.json"),
    json("../data/object-3d-versions.json"),
    json(
      "../public/archive/objects/3d/simulations/houdini-rescue-review/review-sheets.json",
    ),
  ]);

  assert.equal(batch.total, 22);
  assert.equal(batch.succeeded, 22);
  assert.equal(batch.failed, 0);
  assert.equal(batch.pending, 0);
  assert.equal(batch.running, 0);

  assert.equal(review.total, 22);
  assert.equal(review.records.length, 22);
  assert.equal(review.generatedVideoCount, 0);
  assert.equal(review.promisingCount + review.needsPrepCount, 22);
  assert.equal(sheets.recordCount, 22);
  assert.equal(sheets.sheetCount, 6);
  assert.equal(sheets.generatedVideoCount, 0);

  for (const decision of review.records) {
    const record = registry.objects.find(
      (candidate) => candidate.objectId === decision.objectId,
    );
    assert.ok(record, `missing registry record for ${decision.objectId}`);
    const blenderProof = record.clothProofs.find(
      (proof) => proof.id === "construction-static-proof-v1",
    );
    const houdiniProof = record.clothProofs.find(
      (proof) => proof.id === "houdini-vellum-pilot-v1",
    );
    assert.equal(blenderProof.status, "needs-prep");
    assert.equal(houdiniProof.status, decision.status);
    assert.match(houdiniProof.solver, /Houdini 22 Vellum/);
    assert.match(houdiniProof.license, /Apprentice · non-commercial/);
    assert.equal(houdiniProof.resolution, "1280 × 1280");
    assert.equal(houdiniProof.proofFrame, 28);
    assert.ok(!("video" in houdiniProof));
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
  }
});
