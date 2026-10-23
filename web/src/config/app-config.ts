import { resolveLocale } from "@/i18n/config";

import packageJson from "../../package.json";

const currentYear = new Date().getFullYear();

// 브라우저 탭 제목·검색엔진 메타 설명. layout.tsx 의 정적 metadata 로 들어가 모든
// 페이지의 <title>·<meta name="description"> 에 렌더되므로, 활성 locale 에 맞춰
// 한국어(ko)·중국어(zh)를 분기한다. zh 는 상류 대조를 위해 원문을 그대로 보존한다.
// ko 제목은 엠대시 대신 콜론을 써서 "제품명: 설명" 형태로 둔다.
const META_BY_LOCALE = {
  en: {
    title: "OmniForge: Security Testing and Investigation",
    description: "AI-assisted security testing, incident investigation, and detection validation",
  },
  ko: {
    title: "OmniForge: Offensive and defensive security operations",
    description: "ARTEX-based vulnerability diagnosis, infringement investigation, and attack defense improvement console",
  },
  zh: {
    title: "OmniForge — Offensive and defensive security operations",
    description: "Vulnerability diagnosis, incident investigation and attack and defense improvement console based on ARTEX",
  },
} as const;

export const APP_CONFIG = {
  name: "OmniForge",
  version: packageJson.version,
  copyright: `© ${currentYear}, OmniForge contributors.`,
  meta: META_BY_LOCALE[resolveLocale()],
};
