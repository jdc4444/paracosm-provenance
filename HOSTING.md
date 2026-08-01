# Hosting

This repository contains the Paracosm application source and the data snapshots
required to build its interface. The production deployment keeps the large
browser media archive (images, videos, GIFs, and GLB models) in the managed
deployment artifact rather than Git history.

That separation is intentional:

- GitHub blocks ordinary files larger than 100 MiB.
- GitHub Pages limits a published site to 1 GiB.
- The Paracosm browser media set is several gigabytes.
- Editable production sources such as Blender, Cinema 4D, Houdini, Alembic, and
  cache files are local pipeline evidence and are not web assets.

For local UI work without the media archive, use:

```bash
npm ci
npm run build:code
```

The canonical working copy remains responsible for scans, Finder reveals,
creative-application launches, and regenerating the deployed media bundle.
