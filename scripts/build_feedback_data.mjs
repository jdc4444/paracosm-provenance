import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const sourcePath = resolve(
  process.argv[2] ||
    "/Users/alphaone/Documents/Code/fin_v1/.codex-tmp/paracosm-feedback-019f9c7d/working-sheet.json",
);
const outputPath = resolve(process.argv[3] || "data/feedback.json");
const workbook = JSON.parse(readFileSync(sourcePath, "utf8"));
const state = JSON.parse(
  readFileSync(resolve("public/data/state.json"), "utf8"),
);
const shotRegistry = JSON.parse(
  readFileSync(resolve("data/canonical/shot-registry.json"), "utf8"),
);

const columns = [
  "Source ID",
  "Timestamp",
  "Song",
  "Issue",
  "Ask",
  "Acceptance Criterion",
  "Dependencies",
  "Abby's Notes",
  "Beez / Maddy notes",
  "Scope",
  "Priority Tier",
  "Episodes affected",
  "Headline",
  "Solution",
  "Downstream",
];

const sourceRows = workbook.values.slice(2).map((values) => ({
  id: String(values[0]),
  values: Object.fromEntries(
    columns.map((column, index) => [column, values[index] ?? null]),
  ),
}));

const range = (start, end) =>
  Array.from(
    { length: end - start + 1 },
    (_, index) => `CUT-${String(start + index).padStart(3, "0")}`,
  );

const generalNotes = [
  {
    id: "general-facial-expression",
    title: "More Facial Expression",
    parentIds: ["facial-expression"],
    tier: "B",
    noteDescription:
      "Big Abby and Little Abby each maintain a single facial expression across the entire film, despite the narrative moving through fear, sweetness, discovery, frustration, wonder, and recognition. The character's face doesn't yet register the emotional arc the score and choreography are delivering.\n\nAcross the film, the character's eyes do not move. There is minimal blinking, no shifts in eye shape, no subtle motion in the eye area at all. The eyes are static in a way that makes the character read as inanimate during any held shot. Note: a previously-approved eye mockup exists from earlier in the project and may not have been implemented yet; some of this may resolve in final passes.",
    dependency:
      "Abby to provide expression reference for each emotional beat (format TBD pending studio input on preferred method, see Meeting Agenda).\n\nConfirm whether the previously-approved eye design has been implemented and whether the absence of eye motion is a rig limitation or an animation choice.",
    cutIds: [],
    sourceIds: ["2", "1"],
  },
  {
    id: "general-character-motion",
    title: "New Motion",
    parentIds: ["character-motion"],
    tier: "A",
    noteDescription:
      "The character's full-body movement throughout the film doesn't match how Abby moves. The current performance comes from a different performer (a dancer) in the mocap suit, and that performer's physical vocabulary is present in every scene. This affects how Abby feels about the characters embodying her story across the film",
    dependency: "Abby to attend re-mocap session in studio.",
    cutIds: [],
    sourceIds: ["3"],
  },
];

const parents = [
  {
    id: "facial-expression",
    name: "Facial Expression",
    tier: "B",
    noteDescription:
      "Make Big and Little Abby feel alive and emotionally legible through eye motion, blinking, changing eye shape, eyelids, and distinct expressions.",
    dependency:
      "Confirm the approved eye design and rig capability; use Abby expression references for specific emotional beats.",
    cutIds: [],
    sourceIds: ["1", "2"],
  },
  {
    id: "character-motion",
    name: "Character Motion",
    tier: "A",
    noteDescription:
      "Keep Abby's movement authentic, grounded, and physically believable rather than generic or weightless.",
    dependency:
      "Abby performance reference or mocap session; downstream cloth, hair, and final renders follow approved motion.",
    cutIds: [],
    sourceIds: ["3"],
  },
  {
    id: "hair",
    name: "Hair",
    tier: "A",
    noteDescription:
      "Keep Abby's hair long, flowing, vibrant, voluminous, root-driven, and visually consistent across the film.",
    dependency:
      "Approve the intended hair design, then create new hair simulations and rerender affected shots.",
    cutIds: ["CUT-002", "CUT-026"],
    sourceIds: ["4", "7", "12"],
  },
  {
    id: "environment",
    name: "Environment",
    tier: "A",
    noteDescription:
      "Make each environment communicate the story state. The house stays muted, adult, and pre-imagination until the transformation.",
    dependency:
      "Coraline references, Abby's prop and wardrobe archive, and confirmation of transformation timing.",
    cutIds: [],
    sourceIds: ["6", "23", "36"],
  },
  {
    id: "camera",
    name: "Camera",
    tier: "C",
    noteDescription:
      "Use framing, composition, and camera movement to direct attention and reveal each world with intention.",
    dependency:
      "Approved framing references or storyboards for shots whose camera direction changes.",
    cutIds: [],
    sourceIds: ["17", "18", "30"],
  },
];

const notes = [
  {
    id: "note-005",
    title: "Refine swollen eyelids",
    parentIds: ["facial-expression"],
    tier: "C",
    noteDescription:
      "Smooth the eyelids into the eye and remove the puffy, swollen appearance.",
    dependency: "Eye design and rig check.",
    cutIds: ["CUT-001"],
    sourceIds: ["5"],
  },
  {
    id: "note-006",
    title: "Remove opening glow",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Remove the glowing teacup and keep the opening house muted, rational, and non-magical.",
    dependency: "Shared pre-transformation house references.",
    cutIds: ["CUT-001"],
    sourceIds: ["6"],
  },
  {
    id: "note-008",
    title: "Hold the teacup",
    parentIds: ["character-motion"],
    tier: "C",
    noteDescription:
      "Have Abby grip the rim and peek over it instead of waving wildly or appearing to drown.",
    dependency: "Abby motion reference or mocap.",
    cutIds: ["CUT-014"],
    sourceIds: ["8"],
  },
  {
    id: "note-009",
    title: "Explore instead of run",
    parentIds: ["character-motion"],
    tier: "B",
    noteDescription:
      "Replace the urgent mechanical run with cautious walking and active observation of the world.",
    dependency: "Abby motion reference or mocap.",
    cutIds: range(19, 25),
    sourceIds: ["9"],
  },
  {
    id: "note-010",
    title: "Make the mountains feel like Abby's clothes",
    parentIds: ["environment"],
    tier: "C",
    noteDescription:
      "Give the laundry mountains believable cloth weight and use garments that plausibly belong to Big Abby.",
    dependency: "Big Abby wardrobe references and new cloth simulations.",
    cutIds: range(17, 31),
    sourceIds: ["10"],
  },
  {
    id: "note-011",
    title: "Ground the laundry mountains",
    parentIds: ["environment"],
    tier: "C",
    noteDescription:
      "Resolve the mountain-to-ground contact so the piles neither float nor clip.",
    dependency: "Confirm whether the current contact is final or in progress.",
    cutIds: ["CUT-017", "CUT-018"],
    sourceIds: ["11"],
  },
  {
    id: "note-013",
    title: "Give the jump believable weight",
    parentIds: ["character-motion"],
    tier: "B",
    noteDescription:
      "Adjust the rise, fall, landing, and gravity so the jump has convincing physical weight.",
    dependency: "Mocap or focused hand animation.",
    cutIds: ["CUT-025"],
    sourceIds: ["13"],
  },
  {
    id: "note-014a",
    title: "Big Abby is frustrated",
    parentIds: ["facial-expression"],
    tier: "B",
    noteDescription:
      "Build a clear frustrated, fed-up, and disappointed expression for Big Abby.",
    dependency: "Abby expression reference.",
    cutIds: ["CUT-031"],
    sourceIds: ["14"],
  },
  {
    id: "note-014b",
    title: "Make the throw feel like Abby",
    parentIds: ["character-motion"],
    tier: "B",
    noteDescription:
      "Replace the generic throw with a specific performance that feels like Abby.",
    dependency: "Abby throw reference or mocap.",
    cutIds: range(28, 31),
    sourceIds: ["14"],
  },
  {
    id: "note-014c",
    title: "Make the dress behave like cloth",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Remove the rigid bust shape and let the dress deform like real cloth during the throw.",
    dependency: "New cloth simulation after motion is approved.",
    cutIds: range(28, 31),
    sourceIds: ["14"],
  },
  {
    id: "note-015",
    title: "Put Big Abby inside the house",
    parentIds: ["environment"],
    tier: "C",
    noteDescription:
      "Add an interior wall and indoor lighting so Big Abby reads as being inside the house.",
    dependency: "",
    cutIds: ["CUT-031"],
    sourceIds: ["15"],
  },
  {
    id: "note-016",
    title: "Redesign the freezer world",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Use freezer-burned food, boxes, and frosty puffs instead of a knitted or generic snow world.",
    dependency: "Abby's freezer images and approved storyboards.",
    cutIds: range(32, 46),
    sourceIds: ["16"],
  },
  {
    id: "note-017",
    title: "Start close, then reveal the world",
    parentIds: ["camera"],
    tier: "C",
    noteDescription:
      "Begin tighter on Abby, then reveal the larger freezer world after her point of view is established.",
    dependency: "Abby storyboard; source note 18 is treated as supporting framing context.",
    cutIds: ["CUT-034"],
    sourceIds: ["17", "18"],
  },
  {
    id: "note-019",
    title: "Focus the gingerbread sequence on windows",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Shorten the bridge and snow traversal, emphasize the windows, and clarify what the village means to Abby.",
    dependency: "Decide the window interiors and their story purpose.",
    cutIds: ["CUT-037", "CUT-038"],
    sourceIds: ["19", "20"],
  },
  {
    id: "note-021",
    title: "Make the horse encounter gentle and continuous",
    parentIds: ["character-motion"],
    tier: "B",
    noteDescription:
      "Slow the horses, let them notice Abby, and resolve the carousel encounter as one continuous emotional beat.",
    dependency: "Narrative decision on horse and carousel continuity.",
    cutIds: range(41, 46),
    sourceIds: ["21"],
  },
  {
    id: "note-022",
    title: "Big Abby discovers the carousel",
    parentIds: ["facial-expression", "character-motion"],
    tier: "B",
    noteDescription:
      "Start with an ordinary search, then make the carousel discovery land through surprise and curiosity.",
    dependency: "Expression and performance reference.",
    cutIds: ["CUT-046"],
    sourceIds: ["22"],
  },
  {
    id: "note-023",
    title: "Keep the room pre-transformation",
    parentIds: ["environment"],
    tier: "A",
    noteDescription:
      "Desaturate the room and remove books, pictures, and lively decor before the transformation.",
    dependency: "Confirm which props and pictures belong after the transformation.",
    cutIds: ["CUT-053"],
    sourceIds: ["23"],
  },
  {
    id: "note-024",
    title: "Float ceiling pieces outward",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Use smaller ceiling debris and move it outward, away from Abby.",
    dependency: "New destruction simulation.",
    cutIds: ["CUT-054"],
    sourceIds: ["24"],
  },
  {
    id: "note-025",
    title: "Make the beat drop visible",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Synchronize the house breakup to the musical beat drop so the transformation is unmistakable.",
    dependency: "New shot timing and destruction simulation.",
    cutIds: ["CUT-057"],
    sourceIds: ["25"],
  },
  {
    id: "note-026",
    title: "Positive wonder during levitation",
    parentIds: ["facial-expression"],
    tier: "C",
    noteDescription:
      "Give Abby a joyful sense of discovery during levitation rather than a neutral floating expression.",
    dependency: "Abby expression reference.",
    cutIds: ["CUT-059"],
    sourceIds: ["26"],
  },
  {
    id: "note-027",
    title: "Remove mouth artifacts",
    parentIds: ["facial-expression"],
    tier: "A",
    noteDescription:
      "Diagnose and remove the bright spherical or bubble-like artifacts near the mouth.",
    dependency: "Confirm whether the current texture is final or a placeholder.",
    cutIds: ["CUT-066"],
    sourceIds: ["27"],
  },
  {
    id: "note-028",
    title: "Fix awkward floating",
    parentIds: ["character-motion"],
    tier: "B",
    noteDescription:
      "Correct the spine, weight, and articulation so the floating pose feels natural.",
    dependency: "Studio diagnosis followed by clothing and hair resimulation.",
    cutIds: ["CUT-070"],
    sourceIds: ["28"],
  },
  {
    id: "note-029",
    title: "Preserve the line-of-light transition",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Match the glowing line in the grey world to the backlit wardrobe opening across the transition.",
    dependency: "Review and align both boundary cuts together.",
    cutIds: ["CUT-072", "CUT-074"],
    sourceIds: ["29"],
  },
  {
    id: "note-030",
    title: "Keep the yarn ball incidental",
    parentIds: ["camera"],
    tier: "C",
    noteDescription:
      "Remove the close-up and keep the yarn ball as a quiet detail in a wider composition.",
    dependency: "Reframe or recut the sequence.",
    cutIds: ["CUT-078", "CUT-079"],
    sourceIds: ["30"],
  },
  {
    id: "note-031",
    title: "Fill the wardrobe with Abby's real history",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Use Abby's real belongings and avoid generic or duplicated wardrobe objects.",
    dependency: "Personal-object photo archive.",
    cutIds: range(74, 81),
    sourceIds: ["31"],
  },
  {
    id: "note-032",
    title: "Let color originate from objects",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Let saturated objects emit color that pools and blooms into the transformed room.",
    dependency: "Object archive and color references.",
    cutIds: range(80, 85),
    sourceIds: ["32"],
  },
  {
    id: "note-033",
    title: "Place belongings with care",
    parentIds: ["character-motion", "environment"],
    tier: "A",
    noteDescription:
      "Make Abby explore and place belongings deliberately and with grounded care rather than dancing.",
    dependency: "Personal-object archive and Abby performance reference.",
    cutIds: range(82, 87),
    sourceIds: ["33"],
  },
  {
    id: "note-034",
    title: "Begin with a sparse room",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Remove existing trinkets and decor so the room begins sparse before Abby fills it.",
    dependency: "",
    cutIds: range(74, 82),
    sourceIds: ["34"],
  },
  {
    id: "note-035",
    title: "Settle objects after transformation",
    parentIds: ["environment"],
    tier: "B",
    noteDescription:
      "Stop objects from floating or bobbing once the transformation is complete.",
    dependency: "",
    cutIds: range(85, 87),
    sourceIds: ["35"],
  },
  {
    id: "note-036",
    title: "Match the house's pre-transformation tone",
    parentIds: ["environment"],
    tier: "A",
    noteDescription:
      "Match this house view to the earlier muted, pre-transformation environment.",
    dependency: "Earlier-house comparison frames.",
    cutIds: ["CUT-084"],
    sourceIds: ["36"],
  },
];

const activeShotIds = new Set(state.cuts.map((cut) => cut.shotId));
const shotIdByLegacyCut = new Map();
for (const cut of state.cuts) {
  shotIdByLegacyCut.set(cut.id, cut.shotId);
  if (cut.legacyCutId) shotIdByLegacyCut.set(cut.legacyCutId, cut.shotId);
}
for (const shot of shotRegistry.shots) {
  if (shot.legacyCutId) {
    shotIdByLegacyCut.set(shot.legacyCutId, shot.shotId);
  }
}
const attachStableShotIds = ({ cutIds = [], ...record }) => {
  const shotIds = [
    ...new Set(cutIds.map((cutId) => shotIdByLegacyCut.get(cutId)).filter(Boolean)),
  ];
  return {
    ...record,
    shotIds,
    retiredShotIds: shotIds.filter((shotId) => !activeShotIds.has(shotId)),
  };
};

const feedback = {
  schemaVersion: 4,
  assignmentIdentity: "shotId",
  updatedAt: new Date().toISOString(),
  sourceWorkbook: "Copy of Paracosm May Notes - INT Copy 060326.xlsx",
  sourceSheet: "Working sheet",
  sourceColumns: columns,
  generalNotes: generalNotes.map(attachStableShotIds),
  parents: parents.map(attachStableShotIds),
  notes: notes.map(attachStableShotIds),
  sourceRows,
};

writeFileSync(outputPath, `${JSON.stringify(feedback, null, 2)}\n`);
console.log(
  `Wrote ${generalNotes.length} general notes, ${parents.length} parents, ${notes.length} normalized notes, and ${sourceRows.length} source rows to ${outputPath}`,
);
