# Paracosm

A local, read-only production atlas for the Paracosm film. The Pipeline view
traces each current shot back through Premiere, Resolve, After Effects, rendered
media, Cinema 4D projects, and cameras. The Feedback view attaches normalized
notes to those same shots.

Hosted library: <https://paracosm-provenance.josdiazcontreras.chatgpt.site>

The hosted build contains the browser-ready images, videos, GIFs, and GLB
models. Local-only production actions—Finder reveals, creative-application
launches, rescans, and access to editable scene/cache files—remain in the
canonical Mac working copy.

Creative files and Dropbox are read-only. Generated state, thumbnails, proxies,
and the feedback working copy live inside this app.

## Launch

Project Launcher discovers `.plrc` and opens the UI on port `3497`.

```bash
npm run dev
```

The local archive service binds only to `127.0.0.1:3498`.

## Canonical shot system

`data/canonical/paracosm-current.edl` is the only authority for:

- current picture order;
- exact 24 fps record and source In/Out;
- explicit `BL` picture gaps;
- the current number of shots;
- the six chapter record ranges.

`data/canonical/shot-registry.json` is the authority for durable shot identity.
Each picture event has a persistent source-derived `shotId`. `CUT-001`,
`CUT-002`, and so on are current display ordinals only.

Both Pipeline and Feedback render `public/data/state.json` and join records
through `shotId`. Feedback never stores a `CUT-###` foreign key. A rescan always
applies the canonical EDL before publishing state, so the two views cannot
receive different shot lists.

When the EDL changes:

- an unchanged or trimmed source keeps its `shotId`;
- insertion, deletion, or reordering only changes displayed `CUT-###` labels;
- a different source gets a new `shotId`;
- work attached to a removed source remains on a retired registry entry;
- retired work is visible as such and is never silently transferred to a new
  source occupying the same record range.

User-facing shot ranges have inclusive ends. `recordOutTimecode` retains the
exclusive CMX3600 value for duration/export math.

The current import contains 87 picture-track events: 85 sources and 2 explicit
blanks. It includes:

- `CUT-019`, `00:01:15:11–00:01:22:15`, the
  `2C_mountains_Abby-Walking_v001_0036_Sub_01` replacement;
- `CUT-043`, `00:03:09:14–00:03:12:08`, the
  `3m_horse cu_i46_0780.png` close-up.

New sources receive local per-shot thumbnails and scrub proxies under
`public/archive/shots/`. Unchanged sources retain their known proxy range, so
scrubbing follows the source shot even after its record position changes.

## Import a revised EDL

Copy or export the new CMX3600 one-track picture EDL, then run:

```bash
npm run shotlist:sync -- --edl "/absolute/path/to/revised.edl"
```

The command copies it to `data/canonical/paracosm-current.edl`, reconciles the
registry, migrates Pipeline and Feedback attachments, and creates media for new
shots.

A normal evidence refresh also reapplies the current canonical EDL:

```bash
npm run scan
```

The faster scan reuses existing evidence where possible:

```bash
npm run scan:quick
```

## Feedback

The working feedback model preserves all original spreadsheet columns and
normalizes the notes into:

- Parent
- Tier
- Note
- Note Description
- Dependency

Note names, descriptions, and dependencies are editable. One record may apply
to several shots. Dragging it onto another shot adds that shot to the same
record; the × action detaches only the selected shot.

## Generated storage

- `public/data/state.json` — the single UI snapshot used by both views;
- `data/canonical/paracosm-current.edl` — current shot-list authority;
- `data/canonical/shot-registry.json` — persistent active and retired shot IDs;
- `data/feedback.json` — editable normalized feedback plus full source context;
- `data/provenance.sqlite` — normalized provenance graph;
- `public/archive/shots/` — stable shot thumbnails and local scrub proxies;
- `public/archive/reference/` — shared reference proxy;
- `public/archive/conform/` — final/source comparison pairs;
- `public/archive/exports/` — shot-specific lineage frames;
- `data/premiere/` — read-only Premiere exports and conform evidence;
- `data/resolve-export.json` — Resolve archive;
- `data/after-effects-export.json` — AE composition/layer archive;
- `data/c4d-camera-export.json` — C4D camera evidence;
- `data/c4d-dependency-export.json` — C4D dependency health.

## Verification

```bash
npm test
```

The tests build the UI, verify the exact replacement and missing-shot ranges,
assert Pipeline/Feedback registry parity, and simulate insertion, reorder, and
source replacement against the persistent identity registry.

## Optional creative-app probes

```bash
npm run resolve:export
npm run ae:export
npm run camera:probe -- "/absolute/path/to/project.c4d"
npm run camera:probe-candidates
npm run c4d:dependencies
npm run frames:verify
```

These read creative projects and write evidence only inside the app.
