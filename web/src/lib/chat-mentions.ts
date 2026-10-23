export const mentionKinds = [
  { kind: "finding", label: "Vulnerability", alias: "finding", legacy: "漏洞" },
  { kind: "asset", label: "Asset", alias: "asset", legacy: "资产" },
  { kind: "company", label: "Company", alias: "company", legacy: "企业" },
  { kind: "endpoint", label: "Endpoint", alias: "api", legacy: "接口" },
  { kind: "ip", label: "IP", alias: "ip", legacy: "IP" },
  { kind: "app", label: "Application", alias: "app", legacy: "应用" },
  { kind: "root_domain", label: "Domain", alias: "domain", legacy: "域名" },
  { kind: "subdomain", label: "Subdomain", alias: "subdomain", legacy: "子域名" },
  { kind: "service", label: "Service", alias: "service", legacy: "服务" },
] as const;

export type MentionKind = (typeof mentionKinds)[number]["kind"];
export interface ChatMention {
  kind: MentionKind;
  id: number;
  label: string;
  description: string;
}

export function activeMention(value: string, caret: number) {
  const before = value.slice(0, caret);
  const start = before.lastIndexOf("@");
  if (start < 0 || (start > 0 && /[\w.+/-]/.test(before[start - 1]))) return null;
  const query = before.slice(start + 1);
  if (/[[\]\r\n@]/.test(query) || query.length > 220) return null;
  return { start, end: caret, query };
}

export function mentionSearch(query: string) {
  const text = query.trimStart().toLowerCase();
  for (const item of mentionKinds) {
    for (const alias of [item.label.toLowerCase(), item.alias, item.legacy]) {
      if (text === alias || text.startsWith(`${alias} `) || (/[^a-z]/.test(alias) && text.startsWith(alias))) {
        return { kind: item.kind, query: query.trimStart().slice(alias.length).trim(), categories: [] };
      }
    }
  }
  const categories = mentionKinds.filter(
    (item) => item.label.toLowerCase().startsWith(text) || item.alias.startsWith(text),
  );
  return { kind: "" as const, query: query.trim(), categories };
}

export function mentionToken(item: ChatMention) {
  const kind = mentionKinds.find((entry) => entry.kind === item.kind)?.label ?? "Asset";
  const label = item.label
    .replace(/[[\]]/g, (char) => (char === "[" ? "(" : ")"))
    .replace(/\s+/g, " ")
    .slice(0, 100);
  return `@[${kind}#${item.id} ${label}]`;
}

export interface SelectedMention {
  token: string;
  kind: MentionKind;
  id: string;
  text: string;
  start: number;
}

// 토큰의 분류 라벨(漏洞·资产…)은 백엔드 와이어 포맷이라 중국어로 고정한다
// (server/chat_mentions.go 의 chatMentionPattern 과 동일). 화면에 보이는 분류명은
// 여기서 영어 kind 로 되돌려 주고, 소비 컴포넌트가 mentionTextarea.kind 로 한국어화한다.
export function selectedMentions(value: string): SelectedMention[] {
  return [...value.matchAll(/@\[(Vulnerability|Asset|Company|Endpoint|IP|Application|Domain|Subdomain|Service|漏洞|资产|企业|接口|应用|域名|子域名|服务)#([0-9]+)(?: ([^\]\r\n]*))?\]/g)].map(
    (match) => ({
      token: match[0],
      kind: mentionKinds.find((entry) => entry.label === match[1] || entry.legacy === match[1])?.kind ?? "asset",
      id: match[2],
      text: match[3] ?? "",
      start: match.index,
    }),
  );
}
