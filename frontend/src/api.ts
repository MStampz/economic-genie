// A thin client for the API. Every screen goes through here, so a future mobile app can reuse it.

export type Me = { user: { id: string; email: string; display_name: string }; groups: { group_id: string; group_name: string; role: string }[] };
export type Member = { user_id: string; display_name: string; email: string; role: string; joined_at: string };
export type Account = { id: string; name: string; kind: string; institution: string; external_ref: string; owner_user_id: string | null };
export type Category = { id: string; name: string; kind: string; group_id: string | null };
export type Rule = { id: string; pattern: string; is_regex: boolean; category_id: string; priority: number };
export type Transaction = {
  id: string; account_id: string; posted_date: string; amount: string; description: string; merchant: string | null;
  bank_type: string | null; is_pending: boolean; category_id: string | null; category_source: string; is_internal_transfer: boolean;
  transfer_user: boolean | null; import_batch_id: string | null;
};
export type ImportResult = {
  batch_id: string; rows_total: number; rows_new: number; rows_duplicate: number; rows_pending_replaced: number; accounts_created: string[];
  accounts: string[]; transfers_paired: number; format: string; filename: string | null;
};
export type CsvMapping = {
  has_header: boolean; date: string; date_format: "auto" | "DD/MM/YYYY" | "MM/DD/YYYY" | "YYYY-MM-DD";
  amount: string | null; debit: string | null; credit: string | null; flip_sign: boolean; description: string[];
  merchant: string | null; category: string | null; balance: string | null;
  account_column: string | null; account_name: string | null; account_kind: "transaction" | "credit_card"; institution: string;
};
export type ImportPreview = {
  status: "recognised" | "saved" | "confirm_account" | "needs_mapping" | "mapping"; format: string | null; columns: string[]; has_header: boolean;
  sample: string[][]; suggested: Partial<CsvMapping>; parsed: { date: string; amount: string; description: string; account: string }[];
  error: string | null;
  account_choice: AccountChoice | null;
};
export type AccountChoice = {
  layout: string; mapping: CsvMapping; suggested_ref: string; accounts: { ref: string; name: string; kind: string }[];
};
export type ImportBatch = {
  id: string; created_at: string; filename: string | null; source: string; rows_new: number; remaining: number; accounts: string[];
};
export type AuditEvent = { at: string; action: string; user_id: string | null; detail: Record<string, unknown> | null };

export type BudgetPost = {
  id: string; heading_id: string; name: string; color: number; position: number; monthly_amount: string | null; category_ids: string[];
};
export type BudgetHeading = { id: string; name: string; position: number; posts: BudgetPost[] };
export type Budget = { headings: BudgetHeading[] };
export type PostLine = {
  id: string; name: string; heading: string | null; color: number; spent: string; count: number;
  budget: string | null; pace: string | null; category_ids: string[];
};
export type DayLine = { date: string; total: string; by_post: Record<string, string> };
export type MerchantLine = { name: string; spent: string; count: number };
export type Overview = {
  period: { key: string; label: string; start: string; end: string; days: number; data_from: string | null; data_to: string | null; days_with_data: number; elapsed: number };
  months: { key: string; label: string }[];
  total: string; purchases: number; refunds: string; per_day: string; biggest_purchase: MerchantLine | null;
  days: DayLine[]; posts: PostLine[];
  headings: { id: string; name: string; spent: string; budget: string | null; over: number }[];
  categories: { id: string | null; name: string; spent: string; count: number; post_id: string }[];
  accounts: { id: string; name: string; spent: string; count: number; top_post: string | null }[];
  merchants: MerchantLine[];
  recurring: { name: string; amount: string; count: number; last_date: string }[];
  insights: {
    eating_out_total: string; eating_out_count: number; eating_out_per_week: string; most_frequent: MerchantLine | null;
    biggest_day: DayLine | null; biggest_day_merchants: string[]; fees_total: string; fees_count: number;
  };
  budgets_set: number; budgets_over: number; budget_total: string; budget_spent: string;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "X-Genie-Client": "web" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const res = await fetch(`/api${path}`, { method, headers, body: payload, credentials: "same-origin" });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    let msg = "Something went wrong. Try again.";
    if (typeof data?.detail === "string") msg = data.detail;
    else if (Array.isArray(data?.detail) && data.detail[0]?.msg) msg = String(data.detail[0].msg).replace(/^Value error, /, "");
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

const g = (id: string) => `/groups/${id}`;

function form(file: File, mapping?: CsvMapping, saveAs?: string) {
  const fd = new FormData();
  fd.append("file", file);
  if (mapping) fd.append("mapping", JSON.stringify(mapping));
  if (saveAs) fd.append("save_as", saveAs);
  return fd;
}

export const api = {
  me: () => call<Me>("GET", "/auth/me"),
  register: (email: string, password: string, display_name: string) => call<Me>("POST", "/auth/register", { email, password, display_name }),
  login: (email: string, password: string) => call<Me>("POST", "/auth/login", { email, password }),
  logout: () => call<void>("POST", "/auth/logout"),

  createGroup: (name: string) => call<{ id: string }>("POST", "/groups", { name }),
  join: (code: string) => call<{ id: string }>("POST", "/groups/join", { code }),
  members: (gid: string) => call<Member[]>("GET", `${g(gid)}/members`),
  invite: (gid: string) => call<{ code: string; expires_at: string }>("POST", `${g(gid)}/invites`),
  setRole: (gid: string, uid: string, role: string) => call<Member>("PATCH", `${g(gid)}/members/${uid}`, { role }),
  removeMember: (gid: string, uid: string) => call<void>("DELETE", `${g(gid)}/members/${uid}`),
  activity: (gid: string) => call<AuditEvent[]>("GET", `${g(gid)}/activity`),

  accounts: (gid: string) => call<Account[]>("GET", `${g(gid)}/accounts`),
  renameAccount: (gid: string, id: string, name: string) => call<Account>("PATCH", `${g(gid)}/accounts/${id}`, { name }),
  categories: (gid: string) => call<Category[]>("GET", `${g(gid)}/categories`),
  createCategory: (gid: string, name: string) => call<Category>("POST", `${g(gid)}/categories`, { name }),
  rules: (gid: string) => call<Rule[]>("GET", `${g(gid)}/rules`),
  createRule: (gid: string, pattern: string, category_id: string, is_regex = false) =>
    call<Rule>("POST", `${g(gid)}/rules`, { pattern, category_id, is_regex }),
  deleteRule: (gid: string, id: string) => call<void>("DELETE", `${g(gid)}/rules/${id}`),
  applyRules: (gid: string) => call<{ updated: number }>("POST", `${g(gid)}/rules/apply`),
  importRules: (gid: string, rules: unknown) => call<{ updated: number }>("POST", `${g(gid)}/rules/import`, rules),

  overview: (gid: string, period?: string, accountId?: string) => {
    const qs = new URLSearchParams();
    if (period) qs.set("period", period);
    if (accountId) qs.set("account_id", accountId);
    return call<Overview>("GET", `${g(gid)}/overview?${qs}`);
  },
  budget: (gid: string) => call<Budget>("GET", `${g(gid)}/budget`),
  starterBudget: (gid: string) => call<Budget>("POST", `${g(gid)}/budget/starter`),
  addHeading: (gid: string, name: string) => call<Budget>("POST", `${g(gid)}/budget/headings`, { name }),
  renameHeading: (gid: string, id: string, name: string) => call<Budget>("PATCH", `${g(gid)}/budget/headings/${id}`, { name }),
  deleteHeading: (gid: string, id: string) => call<Budget>("DELETE", `${g(gid)}/budget/headings/${id}`),
  addPost: (gid: string, heading_id: string, name: string) => call<Budget>("POST", `${g(gid)}/budget/posts`, { heading_id, name }),
  updatePost: (gid: string, id: string, patch: Record<string, unknown>) => call<Budget>("PATCH", `${g(gid)}/budget/posts/${id}`, patch),
  deletePost: (gid: string, id: string) => call<Budget>("DELETE", `${g(gid)}/budget/posts/${id}`),
  reorderBudget: (gid: string, headings: { id: string; post_ids: string[] }[]) => call<Budget>("PUT", `${g(gid)}/budget/order`, { headings }),

  transactions: (gid: string, params: Record<string, string | number | boolean | string[]>) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (Array.isArray(v)) v.forEach((x) => qs.append(k, x));
      else qs.set(k, String(v));
    }
    return call<{ items: Transaction[]; total: number }>("GET", `${g(gid)}/transactions?${qs}`);
  },
  setCategory: (gid: string, id: string, category_id: string | null) =>
    call<Transaction>("PATCH", `${g(gid)}/transactions/${id}`, { category_id }),
  previewFile: (gid: string, file: File, mapping?: CsvMapping, hasHeader?: boolean) => {
    const fd = form(file, mapping);
    if (hasHeader !== undefined) fd.append("has_header", String(hasHeader));
    return call<ImportPreview>("POST", `${g(gid)}/imports/preview`, fd);
  },
  importFile: (gid: string, file: File, mapping?: CsvMapping, saveAs?: string) =>
    call<ImportResult>("POST", `${g(gid)}/imports`, form(file, mapping, saveAs)),
  setTransfer: (gid: string, id: string, is_transfer: boolean | null) =>
    call<Transaction>("PATCH", `${g(gid)}/transactions/${id}`, { is_transfer }),
  deleteTransaction: (gid: string, id: string) => call<void>("DELETE", `${g(gid)}/transactions/${id}`),
  deleteAccount: (gid: string, id: string) => call<void>("DELETE", `${g(gid)}/accounts/${id}`),
  imports: (gid: string) => call<ImportBatch[]>("GET", `${g(gid)}/imports`),
  undoImport: (gid: string, id: string) =>
    call<{ removed: number; accounts_removed: string[] }>("DELETE", `${g(gid)}/imports/${id}`),
  importProfiles: (gid: string) => call<{ id: string; name: string; institution: string }[]>("GET", `${g(gid)}/import-profiles`),
  deleteImportProfile: (gid: string, id: string) => call<void>("DELETE", `${g(gid)}/import-profiles/${id}`),
};

export const money = (v: string | number, currency = "AUD") =>
  new Intl.NumberFormat("en-AU", { style: "currency", currency }).format(Number(v));
export const money0 = (v: string | number, currency = "AUD") =>
  new Intl.NumberFormat("en-AU", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(v));
