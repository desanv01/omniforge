import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(new URL("../web/package.json", import.meta.url));
const { parse, isStructurallySame } = require("@formatjs/icu-messageformat-parser");
const read = (name) => JSON.parse(fs.readFileSync(new URL(`../web/messages/${name}.json`, import.meta.url), "utf8"));
function flatten(value, prefix = "", result = {}) {
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof child === "string") result[path] = child;
    else flatten(child, path, result);
  }
  return result;
}
const source = flatten(read("ko"));
const english = flatten(read("en"));
assert.deepEqual(Object.keys(english).sort(), Object.keys(source).sort(), "English message keys must be complete");
for (const [key, value] of Object.entries(english)) {
  assert.ok(!/[\u3400-\u9fff\uac00-\ud7af]/u.test(value), `Untranslated message: ${key}`);
  let original;
  try { original = parse(source[key]); } catch { continue; } // raw code examples are not ICU messages
  assert.ok(isStructurallySame(original, parse(value)).success, `Changed ICU arguments: ${key}`);
}
console.log(`Validated ${Object.keys(english).length} English messages and their ICU arguments.`);
