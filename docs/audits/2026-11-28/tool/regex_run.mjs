import fs from "node:fs";
const [, , sitesFile, wordsFile] = process.argv;
const sites = JSON.parse(fs.readFileSync(sitesFile, "utf8"));
const words = JSON.parse(fs.readFileSync(wordsFile, "utf8"));
const out = sites.map((s) => {
  let rx;
  try { rx = new RegExp(s.pattern, (s.flags || "").replace(/[gy]/g, "")); } catch (e) { return { id: s.id, error: String(e.message) }; }
  return { id: s.id, matches: words.filter(([w]) => rx.test(w)).map(([w, k]) => [w, k]) };
});
process.stdout.write(JSON.stringify(out));
