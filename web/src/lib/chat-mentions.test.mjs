import { activeMention, mentionSearch, mentionToken, selectedMentions } from "./chat-mentions.ts";
import assert from "node:assert/strict";
import test from "node:test";

test("mention trigger respects email, existing references, and cursor placement", () => {
  assert.equal(activeMention("user@example.com", 16), null);
  assert.equal(activeMention("Selected @[Vulnerability#1 X]", 28), null);
  assert.deepEqual(activeMention("View @finding rest", 13), { start: 5, end: 13, query: "finding" });
  assert.equal(activeMention("@finding\nnext", 13), null);
});

test("English categories and legacy aliases resolve to stable kinds", () => {
  assert.equal(mentionSearch("").categories.length, 9);
  assert.equal(mentionSearch("vulnerability").kind, "finding");
  assert.equal(mentionSearch("finding SQL injection").query, "SQL injection");
  assert.equal(mentionSearch("ip 192.0.2.1").kind, "ip");
  assert.equal(mentionSearch("Endpoint GET /api").query, "GET /api");
  assert.equal(mentionSearch("漏洞 SQL injection").kind, "finding");
  assert.equal(mentionSearch("acme.com").kind, "");
});

test("English tokens roundtrip labels and preserve adjacent references", () => {
  const first = mentionToken({ kind: "finding", id: 12, label: "title[1]\ndescription" });
  const second = mentionToken({ kind: "ip", id: 13, label: "192.0.2.1" });
  const value = `analyze ${first} and ${second}`;
  const selected = selectedMentions(value);
  assert.equal(selected.length, 2);
  assert.equal(selected[0].kind, "finding");
  assert.equal(selected[0].id, "12");
  assert.equal(selected[0].text, "title(1) description");
  assert.equal(selected[1].kind, "ip");
  assert.equal(selectedMentions("@[漏洞#12 historical]")[0].kind, "finding");
  const next = value.slice(0, selected[0].start) + value.slice(selected[0].start + selected[0].token.length);
  assert.equal(selectedMentions(next)[0].token, second);
});
