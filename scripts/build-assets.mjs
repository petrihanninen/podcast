import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const outDir = path.join(root, "src", "generated");
fs.mkdirSync(outDir, { recursive: true });

const templatesDir = path.join(root, "templates");
const templates = {};
for (const file of fs.readdirSync(templatesDir).sort()) {
  if (file.endsWith(".html")) {
    templates[file] = fs.readFileSync(path.join(templatesDir, file), "utf8");
  }
}
fs.writeFileSync(
  path.join(outDir, "templates.ts"),
  `export const templates: Record<string, string> = ${JSON.stringify(templates, null, 2)};\n`
);

const voiceDir = path.join(root, "voice_refs");
const voices = {};
for (const file of fs.readdirSync(voiceDir).sort()) {
  if (file.endsWith(".wav")) {
    voices[file] = fs.readFileSync(path.join(voiceDir, file)).toString("base64");
  }
}
fs.writeFileSync(
  path.join(outDir, "voice-refs.ts"),
  `export const voiceRefs: Record<string, string> = ${JSON.stringify(voices)};\n`
);

console.log(`Bundled ${Object.keys(templates).length} templates and ${Object.keys(voices).length} voice refs`);
