// Synthetic fixtures for the UX scenarios (UX-01 to UX-03, design/specs/ux-refresh-spec.md),
// including the audit's stress cases. Synthetic content only (CLAUDE.md): no real documents,
// queries, names or credentials.

export type Json = Record<string, unknown>;

export const NOW = "2026-10-19T10:00:00Z";
export const EXPIRES = "2026-11-18T10:00:00Z";

export const WS_MARKETS = {
  id: "aaaaaaaa-0000-4000-8000-000000000001",
  slug: "markets",
  name: "Synthetic Markets",
  default_mode: "corpus_only",
  default_model: "eu-standard",
  default_reasoning: false,
};
export const WS_POLICY = {
  id: "aaaaaaaa-0000-4000-8000-000000000002",
  slug: "policy",
  name: "Synthetic Trade Policy and Regulatory Horizon Scanning",
  default_mode: "corpus_only",
  default_model: "eu-standard",
  default_reasoning: true,
};

export const MODEL_EU = {
  id: "eu-standard",
  display_name: "Synthetic EU Standard",
  external: false,
  reasoning_switch: true,
  default: true,
};
export const MODEL_FAST = {
  id: "eu-fast",
  display_name: "Synthetic EU Fast",
  external: false,
  reasoning_switch: false,
  default: false,
};
export const MODEL_EXT = {
  id: "external-large",
  display_name: "Synthetic External Large",
  external: true,
  reasoning_switch: true,
  default: false,
};

const PUBLISHERS = [
  "Synthetic Institute",
  "Synthetic Commission for Agricultural Statistics",
  "Synthetic Trade Observatory",
  "Synthetic Food Systems Council",
  "Synthetic Development Bank",
];

export function citation(marker: number, overrides: Json = {}): Json {
  return {
    marker,
    source_id: `33333333-3333-4333-8333-${String(marker).padStart(12, "0")}`,
    chunk_id: `chunk-synthetic-${marker}`,
    page_or_slide: 3 + marker,
    excerpt: `Synthetic excerpt ${marker}: output in the synthetic region grew by ${marker + 2} percent year on year, driven by synthetic demand.`,
    publisher: PUBLISHERS[marker % PUBLISHERS.length],
    title: `Synthetic Outlook ${2020 + (marker % 7)}`,
    published_on: `2026-0${(marker % 9) + 1}-01`,
    canonical_url: "https://example.org/synthetic-outlook",
    type: marker % 4 === 0 ? "pptx" : "pdf",
    superseded: false,
    withdrawn: false,
    ...overrides,
  };
}

export const SHORT_ANSWER =
  "Synthetic capacity grew by 12% in 2025 [1], mainly in the synthetic north region [2].";
export const SHORT_CITATIONS = [
  citation(1, {
    title: "Synthetic Outlook 2026",
    publisher: "Synthetic Institute",
    page_or_slide: 4,
    published_on: "2026-03-01",
  }),
  citation(2, {
    title: "Synthetic Regional Capacity Review",
    publisher: "Synthetic Trade Observatory",
    page_or_slide: 12,
    published_on: "2025-11-15",
  }),
];

const LONG_TITLE =
  "Synthetic Global Agrifood Supply Chain Resilience Assessment: Fertiliser, Feed Grain and Oilseed Market Outlook with Regional Scenario Annexes, Second Revised Edition";

export const MANY_CITATIONS = Array.from({ length: 14 }, (_, i) => {
  const m = i + 1;
  const extra: Json = {};
  if (m === 2 || m === 9) extra.title = LONG_TITLE;
  if (m === 5)
    extra.publisher =
      "Synthetic Intergovernmental Organisation for Food, Agriculture and Rural Development Statistics";
  if (m === 6) {
    extra.superseded = true;
  }
  if (m === 7) {
    extra.withdrawn = true;
    extra.excerpt = "";
  }
  if (m === 11) {
    extra.canonical_url = null;
    extra.published_on = null;
    extra.page_or_slide = null;
  }
  return citation(m, extra);
});

export const LONG_ANSWER = `## Summary

Synthetic fertiliser prices eased through the second half of 2025 [1] but remain above the five-year average [2]. Three synthetic drivers stand out: energy input costs [3], export restrictions in two synthetic producer regions [4][5], and a shift in synthetic feed-grain demand [6].

## Market drivers

1. **Energy costs.** Synthetic natural gas benchmarks fell by 18% year on year [3], which lowered nitrogen production costs [7].
2. **Trade measures.** Two synthetic export licensing schemes were extended to mid-2026 [4]; analysts expect partial easing [8].
3. **Demand.** Synthetic planted area for maize rose by 4% [9], while oilseed area was flat [10].

## Regional view

- *Synthetic North:* stocks are adequate for the coming season [11].
- *Synthetic South:* import dependence remains high, at roughly 60% of use [12].
- *Synthetic East:* new capacity of 1.2 million synthetic tonnes is due in 2027 [13].

## Policy implications

Synthetic policy analysts point to targeted support rather than broad price caps [14], and to better stock transparency [2]. Evidence on long-run effects is limited in the synthetic sources; treat the 2027 capacity figures as indicative [13].

This answer is longer than most on purpose, to show how a long, structured answer with many citation markers reads at both widths. ${"Synthetic sentence padding for length. ".repeat(12)}`;

let nextMessage = 1;

export function message(role: "user" | "assistant", content: string, extra: Json = {}): Json {
  return {
    id: `44444444-0000-4000-8000-${String(nextMessage++).padStart(12, "0")}`,
    role,
    content,
    mode: "corpus_only",
    created_at: NOW,
    unsupported: false,
    abstained: false,
    partial: false,
    truncated: false,
    citations: [],
    ...extra,
  };
}

export function conversation(
  id: string,
  title: string | null,
  messages: Json[],
  extra: Json = {},
): Json & { title: string | null; messages: Json[] } {
  return {
    id,
    title,
    created_at: NOW,
    updated_at: NOW,
    expires_at: EXPIRES,
    workspace_id: WS_MARKETS.id,
    workspace_name: WS_MARKETS.name,
    mode: "corpus_only",
    model: MODEL_EU.id,
    model_display_name: MODEL_EU.display_name,
    reasoning: false,
    messages,
    ...extra,
  };
}

export const CONVERSATION_SUMMARIES = (
  [
    ["What drove synthetic fertiliser prices in 2025?", "2026-11-18T10:00:00Z"],
    [
      "Compare synthetic maize and wheat planted area across the three synthetic regions, with a focus on the policy measures announced since the last synthetic harvest and their expected effect on export volumes",
      "2026-11-15T10:00:00Z",
    ],
    [null, "2026-11-10T10:00:00Z"],
    ["Synthetic cocoa supply outlook", "2026-11-02T10:00:00Z"],
    ["Summarise the synthetic trade observatory's latest note", "2026-10-25T10:00:00Z"],
  ] as [string | null, string][]
).map(([title, expires], i): Json => ({
  id: `11111111-0000-4000-8000-00000000000${i + 1}`,
  title,
  created_at: NOW,
  updated_at: NOW,
  expires_at: expires,
  workspace_id: WS_MARKETS.id,
  mode: "corpus_only",
  model: MODEL_EU.id,
  reasoning: false,
}));

export function file(i: number, extra: Json = {}): Json {
  return {
    id: `66666666-0000-4000-8000-${String(i).padStart(12, "0")}`,
    type: ["pdf", "docx", "pptx", "html"][i % 4],
    title: `Synthetic Market Report ${i}`,
    publisher: PUBLISHERS[i % PUBLISHERS.length],
    published_on: `2026-0${(i % 9) + 1}-15`,
    canonical_url: i % 3 === 0 ? null : "https://example.org/synthetic-report",
    ingested_on: "2026-10-01",
    downloadable: i % 3 === 0,
    ...extra,
  };
}

export const FILES = [
  ...Array.from({ length: 9 }, (_, i) => file(i + 1)),
  file(10, {
    title: LONG_TITLE,
    publisher:
      "Synthetic Intergovernmental Organisation for Food, Agriculture and Rural Development Statistics",
  }),
  file(11, { published_on: null }),
];

export function user(
  n: number,
  email: string,
  role: string,
  status: string,
  extra: Json = {},
): Json {
  const signedIn = status !== "invited";
  return {
    id: `55555555-5555-4555-8555-${String(n).padStart(12, "0")}`,
    email,
    display_name: `Synthetic ${email.split("@")[0]}`,
    role,
    status,
    last_login_at: signedIn ? NOW : null,
    last_login_method: signedIn ? "sign_in_link" : null,
    created_at: NOW,
    consent_version: signedIn ? "v1" : null,
    consent_current: signedIn,
    ...extra,
  };
}

export const USERS = [
  user(1, "analyst@example.org", "tenant_admin", "active"),
  user(2, "invited@example.org", "user", "invited"),
  user(3, "member@example.org", "user", "active", { last_login_method: "sso" }),
  user(
    4,
    "policy.analyst.with.a.long.address@international-organisation.example.org",
    "user",
    "active",
  ),
  user(5, "former@example.org", "user", "deactivated"),
];

export const PROMPTS = [
  {
    workspace_id: WS_MARKETS.id,
    version: 2,
    text: "Answer for a business development audience. Lead with the commercial implication, then the evidence. Use metric tonnes and US dollars.",
    created_at: "2026-10-18T10:00:00Z",
  },
  {
    workspace_id: WS_MARKETS.id,
    version: 1,
    text: "Answer for a business development audience.",
    created_at: "2026-10-10T10:00:00Z",
  },
];

// P2A-05: the usage section's counts (synthetic).
export const USAGE = {
  since: "2026-09-19",
  until: "2026-10-18",
  questions: [
    { day: "2026-10-17", mode: "corpus_only", questions: 12 },
    { day: "2026-10-18", mode: "corpus_only", questions: 9 },
    { day: "2026-10-18", mode: "general_knowledge", questions: 3 },
  ],
  active_users: [
    { day: "2026-10-17", users: 3 },
    { day: "2026-10-18", users: 4 },
  ],
  top_sources: [
    { title: "Synthetic Trade Outlook 2026", publisher: "Synthetic Trade Observatory", answers: 7 },
    {
      title: "Synthetic Food Systems Brief",
      publisher: "Synthetic Food Systems Council",
      answers: 4,
    },
  ],
  cost_month: null,
  costs: null,
};

// P2A-08: an open settings grant on the operator's tenant page (synthetic).
export const SUPPORT_GRANT = {
  id: "99999999-9999-4999-8999-000000000001",
  scope: "settings",
  conversation_id: null,
  note: "Synthetic note: our answers stopped citing the markets reports.",
  created_at: "2026-10-18T09:00:00Z",
  expires_at: "2026-10-18T10:00:00Z",
};
export const SUPPORT_SETTINGS = {
  grant_id: SUPPORT_GRANT.id,
  expires_at: SUPPORT_GRANT.expires_at,
  retention_days: 14,
  workspaces: [
    {
      name: "Synthetic Markets",
      slug: "markets",
      default_mode: "corpus_only",
      default_model: "eu-standard",
      default_reasoning: false,
      instructions_version: 2,
      instructions: "Synthetic instructions for a business development audience.",
    },
  ],
};

export const LOGIN_POLICY = {
  sign_in_links_enabled: true,
  sso_source_kind: "entra",
  sso_source_slug: "synthetic-client-entra",
  sso_source_config: {
    tenant: "00000000-0000-4000-8000-0000000000ee",
    client_id: "synthetic-client-id",
  },
  jit_provisioning_enabled: true,
  admin_mfa_required: true,
  sso_endpoints: {
    redirect_uri: "https://sso.example.org/source/oauth/callback/synthetic-client-entra/",
  },
  updated_at: "2026-10-19T10:00:00Z",
};

// Operator console
export const TENANT_ID = "00000000-0000-4000-8000-00000000000a";
export function tenant(id: string, slug: string, name: string, extra: Json = {}): Json {
  return {
    id,
    slug,
    display_name: name,
    verified_domains: [`${slug}.example`],
    status: "active",
    created_at: "2026-10-01T09:00:00Z",
    admins: 1,
    entitlements: {
      answer_modes: ["corpus_only", "general_knowledge"],
      enabled_models: ["eu-standard", "eu-fast"],
      external_models_enabled: true,
      external_spend_cap_cents: 50000,
      external_acceptance_reference: "SYN-ACCEPT-0001",
      external_acceptance_date: "2026-10-12",
      updated_at: "2026-10-19T10:00:00Z",
    },
    login_policy: {
      ...LOGIN_POLICY,
      sso_source_kind: "none",
      sso_source_slug: null,
      sso_source_config: {},
      sso_endpoints: null,
    },
    ...extra,
  };
}
export const TENANTS = [
  tenant(TENANT_ID, "alpha", "Synthetic Alpha Foods"),
  tenant(
    "00000000-0000-4000-8000-00000000000b",
    "beta",
    "Synthetic Beta Intergovernmental Organisation",
    { admins: 3, verified_domains: ["beta.example", "beta-staff.example", "beta-field.example"] },
  ),
  tenant("00000000-0000-4000-8000-00000000000d", "gamma", "Synthetic Gamma", {
    status: "suspended",
    admins: 0,
  }),
];

export const OPERATOR_SOURCES = Array.from({ length: 7 }, (_, i) => ({
  id: `77777777-0000-4000-8000-${String(i + 1).padStart(12, "0")}`,
  type: ["pdf", "docx", "pptx"][i % 3],
  title: i === 3 ? LONG_TITLE : `Synthetic Source ${i + 1}`,
  publisher: PUBLISHERS[i % PUBLISHERS.length],
  licence_basis: ["publisher-terms", "own-analysis", "cc-by-4.0"][i % 3],
  status: "ingested",
  stored: i !== 5,
  downloadable: i % 3 === 1,
  tags: ["sample-reports", i % 2 ? "alpha-reports" : "shared-markets"],
}));

export const SPEND = {
  tenant_id: TENANT_ID,
  month: "2026-10",
  external_models_enabled: true,
  external_spend_cap_cents: 50000,
  external_spent_cents: "31250.40",
  models: [
    {
      model: "eu-standard",
      display_name: "Synthetic EU Standard",
      external: false,
      tokens_in: 1823400,
      tokens_out: 210300,
      cost_cents: "412.10",
    },
    {
      model: "external-large",
      display_name: "Synthetic External Large",
      external: true,
      tokens_in: 902100,
      tokens_out: 88100,
      cost_cents: "31250.40",
    },
  ],
  thresholds: [
    { percent: 50, cents: "25000", reached: true, notified_at: "2026-10-14T08:00:00Z" },
    { percent: 80, cents: "40000", reached: false, notified_at: null },
    { percent: 100, cents: "50000", reached: false, notified_at: null },
  ],
};

export const AGGREGATES = {
  month: "2026-10",
  tenants: 3,
  tenants_with_usage: 2,
  providers: [
    { provider: "scaleway", tokens_in: 3402100, tokens_out: 402100, cost_cents: "812.40" },
    { provider: "openrouter", tokens_in: 902100, tokens_out: 88100, cost_cents: "31250.40" },
  ],
  models: [
    {
      model: "eu-standard",
      display_name: "Synthetic EU Standard",
      provider: "scaleway",
      external: false,
      tenants: 2,
      tokens_in: 3002100,
      tokens_out: 350100,
      cost_cents: "700.20",
    },
    {
      model: "eu-fast",
      display_name: "Synthetic EU Fast",
      provider: "scaleway",
      external: false,
      tenants: 1,
      tokens_in: 400000,
      tokens_out: 52000,
      cost_cents: "112.20",
    },
    {
      model: "external-large",
      display_name: "Synthetic External Large",
      provider: "openrouter",
      external: true,
      tenants: 1,
      tokens_in: 902100,
      tokens_out: 88100,
      cost_cents: "31250.40",
    },
  ],
};

// Content console
const SRC = (n: number) => `88888888-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const SOURCE_STATUSES = [
  "proposed",
  "approved",
  "ingesting",
  "ingested",
  "failed",
  "withdrawn",
  "rejected",
];
export function contentSource(n: number, extra: Json = {}): Json {
  return {
    id: SRC(n),
    type: ["pdf", "docx", "pptx", "html"][n % 4],
    title: `Synthetic Register Entry ${n}`,
    publisher: PUBLISHERS[n % PUBLISHERS.length],
    published_on: `2026-0${(n % 9) + 1}-01`,
    canonical_url: "https://example.org/synthetic-register",
    licence_basis: ["publisher-terms", "own-analysis", "cc-by-4.0"][n % 3],
    tags: ["sample-reports"],
    status: SOURCE_STATUSES[n % SOURCE_STATUSES.length],
    downloadable: false,
    site_id: null,
    takedown_due_on: n === 4 ? "2026-10-30" : null,
    possible_replacement: n === 1,
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-21T10:00:00Z",
    ...extra,
  };
}
export const CONTENT_SOURCES = [
  ...Array.from({ length: 10 }, (_, i) => contentSource(i + 1)),
  contentSource(11, {
    title: LONG_TITLE,
    publisher:
      "Synthetic Intergovernmental Organisation for Food, Agriculture and Rural Development Statistics",
    tags: ["sample-reports", "shared-markets", "alpha-reports"],
  }),
];
export const SOURCE_DETAIL = {
  ...CONTENT_SOURCES[0],
  id: SRC(1),
  review_note: null,
  review_date: null,
  proposed_by: "editor@example.org",
  approved_by: null,
  approved_at: null,
  withdrawn_at: null,
  withdrawal_reason: null,
  chunk_count: null,
  error: null,
  licence_file: true,
  stored: true,
  fetched_at: null,
  supersedes: null,
  possible_replacements: [
    {
      id: SRC(4),
      title: "Synthetic Register Entry 4",
      publisher: "Synthetic Food Systems Council",
      status: "ingested",
    },
  ],
  takedown: null,
  documents: [],
  history: [
    {
      at: "2026-10-20T10:00:00Z",
      event: "proposed",
      actor: "editor@example.org",
      before: null,
      after: "proposed",
      method: null,
    },
    {
      at: "2026-10-20T10:05:00Z",
      event: "licence_uploaded",
      actor: "editor@example.org",
      before: null,
      after: null,
      method: null,
    },
  ],
  jobs: [],
};
export const TAGS = [
  {
    tag: "sample-reports",
    chunk_method: "naive",
    chunk_method_by_type: { pptx: "presentation" },
    dataset_id: "ds-synthetic-1",
    ragflow_url: null,
    sources: 42,
  },
  {
    tag: "shared-markets",
    chunk_method: "naive",
    chunk_method_by_type: {},
    dataset_id: "ds-synthetic-2",
    ragflow_url: null,
    sources: 7,
  },
  {
    tag: "alpha-reports",
    chunk_method: "paper",
    chunk_method_by_type: {},
    dataset_id: null,
    ragflow_url: null,
    sources: 0,
  },
];
export const TAKEDOWNS = [
  {
    source_id: SRC(4),
    title: "Synthetic Register Entry 4",
    reference: "TD-2026-0007",
    requested_on: "2026-10-16",
    due_on: "2026-10-30",
    working_days_left: 5,
    status: "open",
    licence_grounds: false,
  },
  {
    source_id: SRC(11),
    title: LONG_TITLE,
    reference: "TD-2026-0006",
    requested_on: "2026-10-01",
    due_on: "2026-10-15",
    working_days_left: -6,
    status: "open",
    licence_grounds: true,
  },
];
export const SITE_ID = "99999999-0000-4000-8000-000000000001";
export const SITES = [
  {
    id: SITE_ID,
    name: "Synthetic Observatory News",
    host: "news.example.org",
    start_url: "https://news.example.org/briefs/",
    publisher: "Synthetic Trade Observatory",
    licence_basis: "publisher-terms",
    tags: ["shared-markets"],
    status: "approved",
    schedule: "weekly",
    max_pages: 200,
    page_count: 143,
    blocked_count: 4,
    allow_decision: "allowed",
    allow_checked_at: "2026-10-18T03:00:00Z",
    last_crawl_at: "2026-10-18T03:10:00Z",
    last_crawl_status: "succeeded",
    next_crawl_at: "2026-10-25T03:00:00Z",
  },
  {
    id: "99999999-0000-4000-8000-000000000002",
    name: "Synthetic Council Publications Portal With A Rather Long Name",
    host: "council.example.org",
    start_url: "https://council.example.org/publications/",
    publisher: "Synthetic Food Systems Council",
    licence_basis: "cc-by-4.0",
    tags: ["sample-reports"],
    status: "proposed",
    schedule: "monthly",
    max_pages: 500,
    page_count: 0,
    blocked_count: 0,
    allow_decision: "pending",
    allow_checked_at: null,
    last_crawl_at: null,
    last_crawl_status: null,
    next_crawl_at: null,
  },
];
export const SITE_DETAIL = {
  ...SITES[0],
  allow_patterns: ["/briefs/*"],
  deny_patterns: ["/briefs/archive/*"],
  special_category_allow: [],
  approved_at: "2026-10-02T10:00:00Z",
  approved_by: "reviewer@example.org",
  proposed_by: "editor@example.org",
  review_note: "Synthetic review note.",
  withdrawn_at: null,
  withdrawal_reason: null,
  jobs: [
    {
      id: "j1",
      type: "crawl_site",
      status: "succeeded",
      attempts: 1,
      error_code: null,
      created_at: "2026-10-18T03:00:00Z",
      finished_at: "2026-10-18T03:10:00Z",
    },
    {
      id: "j2",
      type: "crawl_site",
      status: "failed",
      attempts: 3,
      error_code: "robots_unavailable",
      created_at: "2026-10-11T03:00:00Z",
      finished_at: "2026-10-11T03:20:00Z",
    },
  ],
  pages: Array.from({ length: 8 }, (_, i) => ({
    url: `https://news.example.org/briefs/synthetic-brief-${i + 1}${i === 2 ? "-with-a-very-long-slug-that-keeps-going-and-going-for-layout-testing" : ""}`,
    state: [
      "ingested",
      "ingested",
      "blocked",
      "ingested",
      "skipped",
      "ingested",
      "failed",
      "ingested",
    ][i],
    reason: i === 2 ? "special_category" : i === 4 ? "unchanged" : i === 6 ? "parse_error" : null,
    special_category: i === 2 ? "health" : null,
    source_id: null,
    published_on: "2026-10-1" + (i % 9),
    fetched_at: "2026-10-18T03:0" + i + ":00Z",
  })),
};
