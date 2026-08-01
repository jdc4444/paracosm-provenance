# Paracosm worker conventions

## Pipeline camera-proof status

- Derive the Pipeline card's C4D color from the selected canonical C4D lineage node plus the cut's camera-verification evidence.
- Show C4D in green only when the selected C4D file is confirmed, its exact cut/take/frame passes the save/reopen dependency audit, the camera result is a positive match, and the newly rendered proof is explicitly verified as a full-color, production-material Redshift visual match.
- Show C4D in yellow when the selected C4D file is confirmed and a newly rendered grey or neutral Redshift proof, or a Cinema 4D Hardware Preview, visually matches the camera. Yellow confirms the camera but does not claim full-color materials or complete render dependencies.
- Show C4D in black when the selected C4D file is confirmed but there is no usable matching visual camera proof.
- Treat frames pulled from historical or canonical production render sequences as comparison references only. They must never populate `c4dVerification.cameraProof`, create a `camera_proof` lineage node, or qualify a C4D button as green or yellow; only a newly rendered full-color production-material Redshift match, grey or neutral Redshift camera match, or matching Hardware Preview camera test from the identified project can do that.
- Show C4D in grey when the selected C4D file is absent or its lineage evidence is not confirmed. A missing source remains disabled; an unconfirmed candidate may still open in Finder.
- Do not infer green or yellow from project linkage, dependency health, or the presence of an image alone.
- Keep Pipeline cards and the right inspector attached to the same canonical cut data so their evidence state cannot drift.
- Render Pipeline and Feedback card source links through the shared `SourceApplicationLinks` component. Do not reproduce its application lookup or status logic inside either page.
