import { cp, mkdir, readdir } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const publicDirectory = resolve(root, "public");
const clientDirectory = resolve(root, "dist", "client");
const hostedArchiveDirectories = [
  "c4d-local-recovery-20260814/CUT-041",
  "c4d-local-recovery-20260814/CUT-066",
];

await mkdir(clientDirectory, { recursive: true });
await cp(
  resolve(publicDirectory, "data"),
  resolve(clientDirectory, "data"),
  { recursive: true },
);

for (const entry of await readdir(publicDirectory, { withFileTypes: true })) {
  if (!entry.isFile()) continue;
  await cp(
    resolve(publicDirectory, entry.name),
    resolve(clientDirectory, entry.name),
  );
}

for (const relativeDirectory of hostedArchiveDirectories) {
  await cp(
    resolve(publicDirectory, "archive", relativeDirectory),
    resolve(clientDirectory, "archive", relativeDirectory),
    { recursive: true },
  );
}

console.log("Staged hosted public data, root assets, and current proof media.");
