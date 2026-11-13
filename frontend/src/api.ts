// A thin client for the API. Every screen goes through here, so a future mobile app can reuse it.

export type Me = { user: { id: string; email: string; display_name: string }; groups: { group_id: string; group_name: string; role: string }[] };
export type Member = { user_id: string; display_name: string; email: string; role: string; joined_at: string };
export type Account = { id: string; name: string; kind: string; institution: string; external_ref: string; owner_user_id: string | null };
export type Category = { id: string; name: string; kind: string; group_id: string | null };
export type Rule = { id: string; pattern: string; is_regex: boolean; category_id: string; priority: number };
export type Transaction = {
  id: string; account_id: string; posted_date: string; amount: string; description: string; merchant: string | null;
  bank_type: string | null; is_pending: boolean; category_id: string | null; category_source: string; is_internal_transfer: boolean;
};
export type ImportResult = {
  rows_total: number; rows_new: number; rows_duplicate: number; rows_pending_replaced: number; accounts_created: string[];
  accounts: string[]; transfers_paired: number; format: string; filename: string | null;
};
export type CsvMapping = {
  has_header: boolean; date: string; date_format: "auto" | "DD/MM/YYYY" | "MM/DD/YYYY" | "YYYY-MM-DD";
  amount: string | null; debit: string | null; credit: string | null; flip_sign: boolean; description: string[];
  merchant: string | null; category: string | null; balance: string | null;
  account_column: string | null; account_name: string | null; account_kind: "transaction" | "credit_card"; institution: string;
};
export type ImportPreview = {
  status: "recognised" | "saved" | "needs_mapping" | "mapping"; format: string | null; columns: string[]; has_header: boolean;
  sample: string[][]; suggested: Partial<CsvMapping>; parsed: { date: string; amount: string; description: string; account: string }[];
  error: string | null;
};
export type AuditEvent = { at: string; action: string; user_id: string | null; detail: Record<string, unknown> | null };

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

  transactions: (gid: string, params: Record<string, string | number | boolean>) => {
    const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
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
  importProfiles: (gid: string) => call<{ id: string; name: string; institution: string }[]>("GET", `${g(gid)}/import-profiles`),
  deleteImportProfile: (gid: string, id: string) => call<void>("DELETE", `${g(gid)}/import-profiles/${id}`),
};

export const money = (v: string | number, currency = "AUD") =>
  new Intl.NumberFormat("en-AU", { style: "currency", currency }).format(Number(v));
