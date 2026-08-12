// Copies the pdf.js static asset directories (character maps, standard fonts, and
// wasm payloads) from the installed pdfjs-dist package into public/, where
// app/pdf-page.tsx points the viewer (cMapUrl, standardFontDataUrl, wasmUrl).
// Runs on postinstall so the served assets always track the installed package
// version instead of drifting into a stale or partial hand-copied snapshot.
import { cp, mkdir, readdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const packageRoot = join(frontendRoot, "node_modules", "pdfjs-dist");
const publicRoot = join(frontendRoot, "public");

const assetDirectories = ["cmaps", "standard_fonts", "wasm"];

for (const directory of assetDirectories) {
  const source = join(packageRoot, directory);
  const destination = join(publicRoot, directory);
  // Replace the destination wholesale so files removed upstream don't linger.
  await rm(destination, { recursive: true, force: true });
  await mkdir(destination, { recursive: true });
  await cp(source, destination, { recursive: true });
  const copied = await readdir(destination);
  if (!copied.length) {
    throw new Error(`No pdf.js assets were copied into public/${directory}.`);
  }
  console.log(`Copied ${copied.length} entries into public/${directory}.`);
}
