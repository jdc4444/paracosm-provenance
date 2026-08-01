import { cp, mkdir, readdir } from "node:fs/promises";
import { resolve } from "node:path";

const root = process.cwd();
const publicDirectory = resolve(root, "public");
const clientDirectory = resolve(root, "dist", "client");

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

console.log("Staged hosted public data and root assets.");
