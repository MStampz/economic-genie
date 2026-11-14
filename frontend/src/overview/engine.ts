// @ts-nocheck -- ported almost line by line from the approved prototype (economic-genie.html, app.js) so the
// Overview looks and behaves exactly like it. It now draws from the family's real data and saves through the API.
// Typing it strictly would mean rewriting it; the boundary (mount + EngineData/EngineActions) is typed instead.
import * as d3 from "d3";
import type { Account, Budget, Category, Overview, Transaction } from "../api";

export type EngineData = {
  groupName: string;
  today: string; // YYYY-MM-DD
  transactions: Transaction[];
  categories: Category[];
  accounts: Account[];
  budget: Budget;
  recurring: Overview["recurring"];
};
export type EngineActions = {
  setCategory: (txId: string, categoryId: string) => Promise<Transaction>;
  renameAccount: (id: string, name: string) => Promise<Account>;
  setPostAmount: (postId: string, amount: number | null) => Promise<Budget>;
  linkBudget: (name: string, categoryIds: string[], amount: number) => Promise<{ budget: Budget; postId: string }>;
  useStarter: () => Promise<Budget>;
};

// Category groups, as in the prototype. Names match the app's categories (NAB's names plus the family's own).
const GROUP_DEF: [string, string[]][] = [
  ["Food & drink", ["Groceries", "Restaurants & takeaway", "Cafe & coffee", "Alcohol"]],
  ["Shopping", ["Other shopping", "Clothing & accessories", "Electronics & technology", "Gifts", "Media"]],
  ["Health & beauty", ["Medical", "Personal care"]],
  ["Transport", ["Crosser", "Fuel", "Vehicle expenses", "Parking & tolls", "Travel expenses", "Taxis & ride shares"]],
  ["Home", ["Homeware", "Home improvements"]],
  ["Bills & services", ["Phone & internet", "Insurance", "Services", "Subscriptions", "Government"]],
  ["Kids & school", ["Education"]],
  ["Fun & events", ["Attractions & events"]],
  ["Pets", ["Pets"]],
  ["Cash & fees", ["Cash", "Fees", "Loans"]],
  ["Housing", ["Rent", "Husleje", "Utilities"]],
  ["Other", []], // the family's own categories that fit no group above
  ["Uncategorised", ["Uncategorised"]],
];
export const GROUP_NAMES = GROUP_DEF.map((g) => g[0]);
const GCOL: Record<string, string> = {};
GROUP_NAMES.forEach((g, i) => (GCOL[g] = "var(--c" + (i + 1) + ")"));
GCOL["Housing"] = "var(--c12)";
GCOL["Other"] = "var(--c10)";
GCOL["Uncategorised"] = "var(--c11)";
const NAME2G: Record<string, string> = {};
for (const [g, cs] of GROUP_DEF) for (const c of cs) NAME2G[c.toLowerCase()] = g;
export const groupOfName = (name: string) => NAME2G[(name || "").toLowerCase()] || "Other";

const MARKUP = `
<header class="top">
  <div class="top-in">
    <div class="brand"><div class="lamp" aria-hidden="true"></div><div><h1>Economic Genie</h1><small id="brandSub"></small></div></div>
    <div class="seg" role="group" aria-label="Period" id="periodSeg"></div>
    <select class="earlier" id="earlier" aria-label="Earlier months" hidden></select>
    <div class="seg" role="group" aria-label="Whose spending" id="whoSeg"></div>
  </div>
</header>
<main class="wrap">
  <section class="grid">
    <div class="card span-12 fade-in">
      <div class="hero">
        <div>
          <div class="eyebrow" id="heroEyebrow">Spent</div>
          <div class="big num" id="heroTotal">$0</div>
          <span class="delta" id="heroDelta"></span>
          <div class="kpis">
            <div class="kpi"><div class="l">Per day</div><div class="v" id="kDaily">–</div></div>
            <div class="kpi"><div class="l">Purchases</div><div class="v" id="kCount">–</div></div>
            <div class="kpi"><div class="l">Biggest category</div><div class="v" id="kTopCat" style="font-family:var(--f-body);font-size:15px;font-weight:600">–</div></div>
            <div class="kpi"><div class="l">Largest purchase</div><div class="v" id="kLargest">–</div></div>
          </div>
          <div class="budget-meter" id="budgetMeter"></div>
        </div>
        <div style="min-width:0">
          <div class="card-head" style="margin-bottom:4px">
            <div><h2>Running total</h2><div class="sub">Daily spend and how it adds up across the period</div></div>
            <div class="legend" id="paceLegend"></div>
          </div>
          <div class="chart" id="paceChart"><div class="tip" id="paceTip"></div></div>
        </div>
      </div>
    </div>
    <div class="span-12"><div class="ins" id="insights"></div></div>
    <div class="card span-7">
      <div class="card-head">
        <div><h2>Where it went</h2><div class="crumb" id="crumb"><span>Click a slice or row to drill in</span></div></div>
      </div>
      <div class="donut-wrap">
        <div class="donut" id="donut"><div class="donut-center"><div class="t num" id="donutT">$0</div><div class="l" id="donutL">All categories</div></div></div>
        <div class="cat-list" id="catList"></div>
      </div>
    </div>
    <div class="card span-5">
      <div class="card-head">
        <div><h2>Budgetoversigt</h2><div class="sub" id="budSub">Link a monthly budget to any category</div></div>
      </div>
      <div class="bud" id="budList"></div>
      <details class="unl" id="unlinked"><summary>+ Link a budget to another category</summary><div id="linkList" style="margin-top:6px"></div></details>
    </div>
    <div class="card span-3">
      <div class="card-head"><div><h2>Spending calendar</h2><div class="sub">Darker means more spent. Click a day.</div></div></div>
      <div class="cal" id="cal"></div>
    </div>
    <div class="card span-3">
      <div class="card-head"><div><h2>Who spent it</h2><div class="sub">One card each. Click a name to rename it.</div></div></div>
      <div class="split" id="split"></div>
      <div class="people" id="people"></div>
    </div>
    <div class="card span-3">
      <div class="card-head"><div><h2>Recurring and subscriptions</h2><div class="sub" id="subsSub">Detected from merchant and amount</div></div></div>
      <div class="subs" id="subs"></div>
    </div>
    <div class="card span-3">
      <div class="card-head"><div><h2>Top merchants</h2><div class="sub">Grouped by merchant, all stores combined</div></div></div>
      <div class="mer" id="mer"></div>
    </div>
    <div class="card span-12" id="txCard">
      <div class="card-head"><div><h2>Transactions</h2><div class="sub" id="txSub"></div></div></div>
      <div class="toolbar">
        <label class="search" for="q"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" style="color:var(--fg-3)"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg><input id="q" type="search" placeholder="Search merchant, description or amount" autocomplete="off"></label>
        <div class="chips" id="chips"></div>
      </div>
      <div class="tbl-wrap">
        <table>
          <thead><tr><th><button type="button" data-sort="d">Date</button></th><th>Merchant</th><th>Category</th><th>Card</th><th class="r"><button type="button" data-sort="a">Amount</button></th></tr></thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
      <div class="more"><button class="btn" id="moreBtn" type="button">Show more</button></div>
    </div>
  </section>
  <div class="foot"><span id="footRange"></span><span>Transfers between your own accounts are left out. Category and budget changes are saved for the whole family.</span></div>
</main>
<div class="toast" id="toast" role="status" aria-live="polite"></div>`;

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const DOWS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const AUD = new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" });
const AUD0 = new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 });
const fm = (v) => AUD.format(v), f0 = (v) => AUD0.format(v);
const pd = (s) => new Date(s + "T00:00:00");
const iso = d3.timeFormat("%Y-%m-%d");
const dlabel = (s) => { const d = pd(s); return DOWS[d.getDay()] + " " + d.getDate() + " " + MON[d.getMonth()]; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const store = {
  get(k, d) { try { const v = localStorage.getItem("eg." + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem("eg." + k, JSON.stringify(v)); } catch { /* private mode */ } },
};
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function cleanMerchant(m, desc) {
  if (m && m !== "Square" && m !== "CompassPay") return m.replace(/\s*\(.*?\)\s*/g, "").trim();
  let d = (desc || "").replace(/^(SQ \*|SP |SMP\*|ZLR\*|KPAY\*|COM\*|DD \*|PAYPAL \*)/i, "").replace(/\s+(MELBOURNE|SYDNEY|AUS|BEAUMARIS|BLACK ?ROCK|CHELTENHAM|HAWTHORN|SOUTH MELBOUR|DOCKLANDS).*$/i, "");
  d = d.replace(/[^A-Za-z&' ]/g, " ").trim().split(/\s+/).slice(0, 3).join(" ");
  return d.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) || "Unknown";
}

export function mount(root: HTMLElement, data: EngineData, act: EngineActions): () => void {
  root.innerHTML = MARKUP;
  const $ = (id) => root.querySelector("#" + id) as HTMLElement;
  const cats = new Map(data.categories.map((c) => [c.id, c]));
  const catName = (id) => cats.get(id)?.name ?? "Uncategorised";
  const uncId = data.categories.find((c) => c.name === "Uncategorised")?.id ?? null;

  // Spending, as the server's overview counts it: no own transfers, no income or transfer categories;
  // money in only counts (as a refund) when it sits in a spending category.
  let i = 0;
  const TX = [];
  for (const t of data.transactions) {
    if (t.is_internal_transfer) continue;
    const c = t.category_id ? cats.get(t.category_id) : null;
    const a = Number(t.amount);
    const counts = a > 0 ? c && c.kind === "expense" && c.name !== "Uncategorised" : !c || c.kind === "expense";
    if (!counts) continue;
    TX.push({ id: t.id, i: i++, d: t.posted_date, spend: -a, c: t.account_id, desc: t.description, cid: t.category_id ?? uncId,
      merch: cleanMerchant(t.merchant, t.description), p: t.is_pending, src: t.category_source });
  }
  const catOf = (t) => catName(t.cid);
  const groupOf = (t) => groupOfName(catOf(t));

  // Category picker: every spending category, under its group.
  const expenseCats = data.categories.filter((c) => c.kind === "expense");
  const GROUPS: Record<string, { id: string; name: string }[]> = Object.fromEntries(GROUP_NAMES.map((g) => [g, []]));
  for (const c of expenseCats) GROUPS[groupOfName(c.name)].push(c);

  // Accounts and their names.
  const names = Object.fromEntries(data.accounts.map((a) => [a.id, a.name]));
  const cardIds = data.accounts.map((a) => a.id).filter((id) => TX.some((t) => t.c === id));
  const CARD_COL = ["var(--c2)", "var(--c3)", "var(--c5)", "var(--c6)", "var(--c7)", "var(--c4)"];

  // Periods: one per month with data, plus all data.
  const DATA_START = d3.min(TX, (t) => t.d) ?? data.today, DATA_END = d3.max(TX, (t) => t.d) ?? data.today;
  const curMonth = data.today.slice(0, 7), curYear = data.today.slice(0, 4);
  const months = [...new Set(TX.map((t) => t.d.slice(0, 7)))].sort();
  const PERIODS: Record<string, any> = {};
  for (const m of months) {
    const [y, mo] = m.split("-").map(Number);
    const monthDays = new Date(y, mo, 0).getDate();
    const from = m + "-01", to = m + "-" + String(monthDays).padStart(2, "0");
    const isCur = m === curMonth;
    PERIODS[m] = { label: MONTH[mo - 1] + (String(y) !== curYear ? " " + y : "") + (isCur ? " so far" : ""), from, to, monthDays,
      elapsed: isCur ? Number(data.today.slice(8)) / monthDays : 1, dayOf: Number(data.today.slice(8)),
      dataFrom: from < DATA_START ? DATA_START : from, dataTo: to > DATA_END ? DATA_END : to };
  }
  PERIODS.all = { label: "All data", from: DATA_START, to: DATA_END, monthDays: 30.44, elapsed: 1, dataFrom: DATA_START, dataTo: DATA_END };

  let budget = data.budget;
  const S = {
    period: store.get("period", months[months.length - 1]), who: "all", drill: null,
    f: { group: null, cat: null, day: null, merchant: null }, q: "", sort: { k: "d", dir: -1 }, limit: 25, editing: null,
  };
  if (!PERIODS[S.period]) S.period = months[months.length - 1] ?? "all";

  const inPeriod = (t) => { const p = PERIODS[S.period]; return t.d >= p.from && t.d <= p.to; };
  const base = () => TX.filter((t) => inPeriod(t) && (S.who === "all" || t.c === S.who));
  const sum = (a) => a.reduce((s, t) => s + t.spend, 0);
  const daysOf = (p) => Math.round((pd(p.dataTo) - pd(p.dataFrom)) / 864e5) + 1;
  const dataDays = () => daysOf(PERIODS[S.period]);

  const cleanups: (() => void)[] = [];
  const on = (type, fn) => { root.addEventListener(type, fn); cleanups.push(() => root.removeEventListener(type, fn)); };
  let tt;
  function toast(m) { const t = $("toast"); t.textContent = m; t.classList.add("show"); clearTimeout(tt); tt = setTimeout(() => t.classList.remove("show"), 2200); }
  const fail = (e) => toast((e && e.message) || "Something went wrong. Try again.");

  // ---------- controls
  function renderControls() {
    $("brandSub").textContent = data.groupName;
    const keys = [...months.slice(-3), "all"];
    $("periodSeg").innerHTML = keys.map((k) => `<button type="button" aria-pressed="${S.period === k}" data-p="${k}">${esc(PERIODS[k].label)}</button>`).join("");
    const older = months.slice(0, -3).reverse();
    const sel = $("earlier") as HTMLSelectElement;
    sel.hidden = !older.length;
    sel.innerHTML = `<option value="">Earlier</option>` + older.map((k) => `<option value="${k}" ${S.period === k ? "selected" : ""}>${esc(PERIODS[k].label)}</option>`).join("");
    const who = [["all", cardIds.length === 2 ? "Both of us" : "Everyone"], ...cardIds.map((id) => [id, names[id]])];
    $("whoSeg").hidden = cardIds.length < 2;
    $("whoSeg").innerHTML = who.map(([k, l]) => `<button type="button" aria-pressed="${S.who === k}" data-w="${k}">${esc(l)}</button>`).join("");
  }
  on("click", (e) => {
    const p = e.target.closest("[data-p]"); if (p) { S.period = p.dataset.p; store.set("period", S.period); S.f.day = null; renderAll(); return; }
    const w = e.target.closest("[data-w]"); if (w) { S.who = w.dataset.w; renderAll(); }
  });
  on("change", (e) => { if (e.target.id === "earlier" && e.target.value) { S.period = e.target.value; store.set("period", S.period); S.f.day = null; renderAll(); } });

  // ---------- count up
  function countUp(el, to, fmt, dur = 900) {
    const from = +el.dataset.v || 0; el.dataset.v = to;
    if (reduced()) { el.innerHTML = fmt(to); return; }
    const t0 = performance.now();
    function step(now) { const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3); el.innerHTML = fmt(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); }
    requestAnimationFrame(step);
  }
  const bigFmt = (v) => { const s = AUD.format(v); const i = s.lastIndexOf("."); return s.slice(0, i) + '<span class="cents">' + s.slice(i) + "</span>"; };

  // ---------- budgets
  function budgetRows(rows) {
    const p = PERIODS[S.period];
    const scale = S.period === "all" ? dataDays() / p.monthDays : 1;
    const out = [];
    for (const h of budget.headings) for (const post of h.posts) {
      const ids = new Set(post.category_ids);
      const spent = sum(rows.filter((t) => ids.has(t.cid)));
      const amt = post.monthly_amount === null ? 0 : Number(post.monthly_amount);
      const b = amt * scale, elapsed = p.elapsed;
      const projected = elapsed < 1 ? spent / elapsed : spent;
      const status = !amt ? "unset" : spent > b ? "over" : projected > b ? "risk" : "ok";
      out.push({ key: post.id, name: post.name, amt, spent, budget: b, elapsed, projected, status, head: h.name,
        color: `var(--c${post.color || 10})`, cats: post.category_ids.map(catName) });
    }
    return out;
  }
  function barHTML(spent, b, elapsed, status) {
    const pct = b ? Math.min(100, spent / b * 100) : 0;
    const overPct = spent > b ? Math.min(100, (spent - b) / spent * 100) : 0;
    return `<div class="bar ${status === "over" ? "over" : status === "risk" ? "risk" : ""}"><i style="width:${pct}%"></i>${elapsed < 1 ? `<b style="left:${elapsed * 100}%" title="Today"></b>` : ""}${overPct ? `<s style="left:${100 - overPct}%"></s>` : ""}</div>`;
  }
  function renderBudgets(rows) {
    let br = budgetRows(rows);
    const p = PERIODS[S.period];
    $("budSub").textContent = S.period === "all" ? "Monthly budgets scaled to " + dataDays() + " days"
      : p.elapsed < 1 ? `Day ${p.dayOf} of ${p.monthDays}. The white tick marks today.` : "Full month";
    const rowHTML = (b) => {
      if (b.status === "unset" && S.editing !== b.key) return `<div class="bud-row"><div class="nm"><span class="sw" style="background:${b.color}"></span><span class="t">${esc(b.name)}</span></div><button class="btn primary" type="button" data-bedit="${b.key}" style="padding:4px 10px">Set amount</button><div class="meta"><span><span class="pill unset">No amount yet</span> ${esc(b.cats.join(" + "))}</span><span>${f0(b.spent)} spent</span></div></div>`;
      const pill = b.status === "over" ? `<span class="pill over">Over by ${f0(b.spent - b.budget)}</span>` : b.status === "risk" ? `<span class="pill risk">Heading for ${f0(b.projected)}</span>` : b.status === "ok" ? `<span class="pill ok">On track</span>` : `<span class="pill unset">No amount yet</span>`;
      const left = b.status === "over" ? `${Math.round(b.spent / b.budget * 100)}% of budget` : b.amt ? `${f0(b.budget - b.spent)} left` : `${f0(b.spent)} spent`;
      const editing = S.editing === b.key;
      return `<div class="bud-row ${b.status === "over" ? "is-over" : ""}">
        <div class="nm"><span class="sw" style="background:${b.color}"></span><span class="t">${esc(b.name)}</span></div>
        ${editing ? `<div class="bud-edit"><input id="budInput" type="number" min="0" step="50" value="${b.amt || ""}" placeholder="per month" aria-label="Monthly budget for ${esc(b.name)}"><button class="btn primary" type="button" data-bsave="${b.key}">Save</button>${b.amt ? `<button class="btn" type="button" data-bdel="${b.key}">Remove</button>` : ""}</div>`
          : `<button class="btn" type="button" data-bedit="${b.key}" title="Edit budget" style="padding:4px 10px"><span class="num">${f0(b.spent)} / ${f0(b.budget)}</span></button>`}
        ${barHTML(b.spent, b.budget, b.elapsed, b.status)}
        <div class="meta"><span>${pill} ${esc(b.cats.join(" + "))}</span><span>${left}</span></div>
      </div>`;
    };
    const heads = budget.headings.map((h) => h.name);
    $("budList").innerHTML = heads.map((h) => {
      const rs = br.filter((b) => b.head === h); if (!rs.length) return "";
      const set = rs.filter((b) => b.status !== "unset"), sp = d3.sum(rs, (b) => b.spent), bt = d3.sum(set, (b) => b.budget), nOver = rs.filter((b) => b.status === "over").length;
      return `<div class="bud-head"><span>${esc(h)}</span><span class="num">${f0(sp)} spent${bt ? ` · ${f0(bt)} budgeted` : ""}${nOver ? ` <span class="pill over">${nOver} over</span>` : ""}</span></div>` + rs.map(rowHTML).join("");
    }).join("") || `<div class="link-row" style="color:var(--fg-3)"><span>No budget yet. Start from the one we set up in the prototype, then set the amounts.</span><button class="btn primary" type="button" data-starter>Use starter budget</button></div>`;
    // unlinked: groups with no linked categories, and single categories, that had spending
    const linked = new Set(budget.headings.flatMap((h) => h.posts.flatMap((p) => p.category_ids)));
    const perMonth = S.period === "all" ? dataDays() / 30.44 : 1;
    const gItems = d3.rollups(rows, (v) => ({ v: d3.sum(v, (t) => t.spend), ids: [...new Set(v.map((t) => t.cid))] }), groupOf)
      .filter(([n, o]) => o.ids.every((id) => !linked.has(id)) && n !== "Uncategorised")
      .map(([n, o]) => ({ name: n, v: o.v, ids: o.ids, kind: "group", col: GCOL[n] }));
    const cItems = d3.rollups(rows, (v) => d3.sum(v, (t) => t.spend), (t) => t.cid)
      .filter(([id]) => id && !linked.has(id) && id !== uncId)
      .map(([id, v]) => ({ name: catName(id), v, ids: [id], kind: "category", col: GCOL[groupOfName(catName(id))] }));
    LINKS = [...gItems, ...cItems].filter((x) => x.v > 0).sort((a, b) => b.v - a.v).slice(0, 14);
    $("unlinked").hidden = !budget.headings.length || !LINKS.length;
    $("linkList").innerHTML = LINKS.map((x, i) => `<div class="link-row"><span><span class="sw" style="background:${x.col};margin-right:8px"></span>${esc(x.name)} <span style="color:var(--fg-3);font-size:11.5px">${x.kind} · ${f0(x.v)} spent</span></span><button class="btn" type="button" data-blink="${i}" data-sugg="${Math.ceil(x.v / perMonth / 50) * 50}">Link budget</button></div>`).join("");
    // hero meter
    br = br.filter((b) => b.status !== "unset");
    const tot = br.reduce((s, b) => s + b.budget, 0), sp = br.reduce((s, b) => s + b.spent, 0);
    const nOver = br.filter((b) => b.status === "over").length, nRisk = br.filter((b) => b.status === "risk").length;
    const st = sp > tot ? "over" : br.some((b) => b.status !== "ok") ? "risk" : "ok";
    $("budgetMeter").innerHTML = br.length ? `<div class="row"><span><b style="color:var(--fg)">${br.length} budget${br.length > 1 ? "s" : ""} linked</b> · ${nOver ? `<span style="color:var(--over)">${nOver} over</span>` : "none over"}${nRisk ? ` · <span style="color:var(--risk)">${nRisk} at risk</span>` : ""}</span><span class="num">${f0(sp)} / ${f0(tot)}</span></div>${barHTML(sp, tot, PERIODS[S.period].elapsed, st)}`
      : `<div class="row"><span>No budget amounts set yet. Set them in Budgetoversigt below.</span></div>`;
  }
  let LINKS = [];
  const focusInput = () => setTimeout(() => { const i = root.querySelector("#budInput") as HTMLInputElement; if (i) { i.focus(); i.select(); } }, 0);
  async function saveAmount(id, v) {
    try { budget = await act.setPostAmount(id, v); toast(v === null ? "Budget removed" : "Budget saved"); } catch (e) { fail(e); }
    S.editing = null; renderAll();
  }
  on("click", async (e) => {
    const ed = e.target.closest("[data-bedit]"); if (ed) { S.editing = ed.dataset.bedit; renderAll(); focusInput(); return; }
    const sv = e.target.closest("[data-bsave]"); if (sv) { const v = +(root.querySelector("#budInput") as HTMLInputElement).value; if (v > 0) await saveAmount(sv.dataset.bsave, v); else { S.editing = null; renderAll(); } return; }
    const dl = e.target.closest("[data-bdel]"); if (dl) { await saveAmount(dl.dataset.bdel, null); return; }
    const lk = e.target.closest("[data-blink]"); if (lk) {
      const x = LINKS[+lk.dataset.blink];
      try { const r = await act.linkBudget(x.name, x.ids, +lk.dataset.sugg || 100); budget = r.budget; S.editing = r.postId; toast("Linked. Set the monthly amount."); } catch (err) { fail(err); }
      renderAll(); focusInput(); return;
    }
    if (e.target.closest("[data-starter]")) { try { budget = await act.useStarter(); toast("Starter budget added. Set the amounts."); } catch (err) { fail(err); } renderAll(); }
  });
  on("keydown", (e) => {
    if (e.target.id === "budInput") {
      if (e.key === "Enter") { const b = root.querySelector("[data-bsave]") as HTMLElement; b && b.click(); }
      if (e.key === "Escape") { S.editing = null; renderAll(); }
    }
  });

  // ---------- hero
  function renderHero(rows) {
    const p = PERIODS[S.period], total = sum(rows), days = dataDays();
    $("heroEyebrow").textContent = (S.who === "all" ? "Spent together" : "Spent by " + names[S.who]) + " · " + p.label;
    countUp($("heroTotal"), total, bigFmt);
    const purchases = rows.filter((t) => t.spend > 0);
    countUp($("kDaily"), total / days, f0, 700);
    $("kCount").textContent = String(purchases.length);
    const g = d3.rollups(rows, (v) => d3.sum(v, (t) => t.spend), groupOf).sort((a, b) => b[1] - a[1]);
    $("kTopCat").innerHTML = g.length && total > 0 ? `<span class="sw" style="background:${GCOL[g[0][0]]};margin-right:6px"></span>${esc(g[0][0])} <span class="num" style="color:var(--fg-3);font-size:12.5px;font-weight:400">${Math.round(g[0][1] / total * 100)}%</span>` : "–";
    const big = d3.greatest(purchases, (t) => t.spend);
    $("kLargest").innerHTML = big ? `${f0(big.spend)} <span style="font-family:var(--f-body);color:var(--fg-3);font-size:12px">${esc(big.merch)}</span>` : "–";
    // delta: per-day spend this month vs last month
    let dt = "";
    const prevKey = S.period !== "all" ? months[months.indexOf(S.period) - 1] : null;
    if (p.elapsed < 1 && prevKey) {
      const pp = PERIODS[prevKey];
      const prev = TX.filter((t) => t.d >= pp.from && t.d <= pp.to && (S.who === "all" || t.c === S.who));
      const prevAvg = sum(prev) / daysOf(pp), avg = total / days, ch = prevAvg ? (avg / prevAvg - 1) * 100 : 0;
      dt = `<span style="color:${ch > 0 ? "var(--over)" : "var(--good)"}">${ch > 0 ? "▲" : "▼"} ${Math.abs(ch).toFixed(0)}%</span> per day vs ${esc(pp.label)}`;
    } else dt = `${days} days of data · ${dlabel(p.dataFrom)} to ${dlabel(p.dataTo)}`;
    $("heroDelta").innerHTML = dt;
  }

  // ---------- pace chart (cumulative area + stacked daily bars)
  function renderPace(rows) {
    const host = $("paceChart"); host.querySelectorAll("svg").forEach((n) => n.remove());
    const p = PERIODS[S.period];
    const days = d3.timeDays(pd(p.dataFrom), d3.timeDay.offset(pd(p.dataTo), 1)).map(iso);
    if (!days.length) return;
    const byDay = d3.group(rows, (t) => t.d);
    let cum = 0;
    const series = days.map((d) => { const r = byDay.get(d) || []; const v = sum(r); cum += v; const gs = {}; for (const t of r) { if (t.spend > 0) { const g = groupOf(t); gs[g] = (gs[g] || 0) + t.spend; } } return { d, v, cum, gs, r }; });
    const narrow = host.clientWidth < 600; const W = narrow ? 420 : 760, H = narrow ? 320 : 300, m = { l: 44, r: 8, t: 12 }, h1 = 150, gap = 26, h2 = 88;
    const x = d3.scaleBand().domain(days).range([m.l, W - m.r]).padding(0.22);
    const xc = (d) => x(d) + x.bandwidth() / 2;
    const y1 = d3.scaleLinear().domain([0, d3.max(series, (s) => s.cum) || 1]).nice().range([m.t + h1, m.t]);
    const y2 = d3.scaleLinear().domain([0, d3.max(series, (s) => d3.sum(Object.values(s.gs))) || 1]).nice().range([m.t + h1 + gap + h2, m.t + h1 + gap]);
    const svg = d3.select(host).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img").attr("aria-label", "Running total and daily spend");
    const defs = svg.append("defs"); const lg = defs.append("linearGradient").attr("id", "areaG").attr("x1", 0).attr("x2", 0).attr("y1", 0).attr("y2", 1);
    lg.append("stop").attr("offset", "0%").attr("stop-color", "var(--accent)").attr("stop-opacity", 0.35); lg.append("stop").attr("offset", "100%").attr("stop-color", "var(--accent)").attr("stop-opacity", 0);
    const k = (d) => (d >= 1000 ? "$" + d / 1000 + "k" : "$" + d);
    svg.append("g").selectAll("line").data(y1.ticks(4)).join("line").attr("class", "gridline").attr("x1", m.l).attr("x2", W - m.r).attr("y1", (d) => y1(d)).attr("y2", (d) => y1(d));
    svg.append("g").attr("class", "axis").selectAll("text").data(y1.ticks(4)).join("text").attr("x", m.l - 8).attr("y", (d) => y1(d) + 3).attr("text-anchor", "end").text(k);
    svg.append("g").attr("class", "axis").selectAll("text").data(y2.ticks(2)).join("text").attr("x", m.l - 8).attr("y", (d) => y2(d) + 3).attr("text-anchor", "end").text(k);
    svg.append("g").selectAll("line").data(y2.ticks(2)).join("line").attr("class", "gridline").attr("x1", m.l).attr("x2", W - m.r).attr("y1", (d) => y2(d)).attr("y2", (d) => y2(d));
    const area = d3.area().x((s) => xc(s.d)).y0(y1(0)).y1((s) => y1(s.cum)).curve(d3.curveMonotoneX);
    const line = d3.line().x((s) => xc(s.d)).y((s) => y1(s.cum)).curve(d3.curveMonotoneX);
    svg.append("path").datum(series).attr("d", area).attr("fill", "url(#areaG)");
    const lp = svg.append("path").datum(series).attr("d", line).attr("fill", "none").attr("stroke", "var(--accent)").attr("stroke-width", 2.5).attr("stroke-linecap", "round");
    if (!reduced()) { const L = lp.node().getTotalLength(); lp.attr("stroke-dasharray", L + " " + L).attr("stroke-dashoffset", L).transition().duration(1100).ease(d3.easeCubicOut).attr("stroke-dashoffset", 0).on("end", () => lp.attr("stroke-dasharray", null)); }
    const last = series[series.length - 1];
    svg.append("circle").attr("cx", xc(last.d)).attr("cy", y1(last.cum)).attr("r", 5).attr("fill", "var(--accent)").attr("stroke", "var(--surface)").attr("stroke-width", 2.5);
    svg.append("text").attr("x", xc(last.d) - 10).attr("y", y1(last.cum) - 12).attr("text-anchor", "end").attr("fill", "var(--fg)").attr("font-family", "var(--f-mono)").attr("font-size", 12).text(f0(last.cum));
    const bars = svg.append("g");
    series.forEach((s) => { let y0 = 0; GROUP_NAMES.forEach((g) => { const v = s.gs[g]; if (!v) return; bars.append("rect").attr("x", x(s.d)).attr("width", x.bandwidth()).attr("y", y2(y0 + v)).attr("height", Math.max(0, y2(y0) - y2(y0 + v))).attr("fill", GCOL[g]).attr("rx", 1.5).attr("opacity", S.f.day && S.f.day !== s.d ? 0.3 : 1); y0 += v; }); });
    const every = Math.ceil(days.length / (narrow ? 5 : 9));
    svg.append("g").attr("class", "axis").selectAll("text").data(days.filter((d, i) => (i % every === 0 ? days.length - 1 - i >= every * 0.6 || i === days.length - 1 : i === days.length - 1))).join("text").attr("x", xc).attr("y", H - 2).attr("text-anchor", "middle").text((d) => { const t = pd(d); return t.getDate() + " " + MON[t.getMonth()]; });
    svg.append("text").attr("x", m.l).attr("y", m.t + h1 + gap - 8).attr("fill", "var(--fg-3)").attr("font-size", 10.5).attr("font-family", "var(--f-mono)").text("DAILY, BY CATEGORY");
    const tip = $("paceTip"); const guide = svg.append("line").attr("y1", m.t).attr("y2", m.t + h1 + gap + h2).attr("stroke", "var(--fg-3)").attr("stroke-dasharray", "3 3").attr("opacity", 0);
    const dot = svg.append("circle").attr("r", 4).attr("fill", "var(--accent)").attr("opacity", 0);
    const at = (ev) => { const [mx] = d3.pointer(ev); return series[Math.max(0, Math.min(days.length - 1, Math.floor((mx - m.l) / x.step())))]; };
    svg.append("rect").attr("x", m.l).attr("width", W - m.l - m.r).attr("y", 0).attr("height", H).attr("fill", "transparent").style("cursor", "pointer")
      .on("mousemove touchmove", (ev) => { const s = at(ev);
        guide.attr("x1", xc(s.d)).attr("x2", xc(s.d)).attr("opacity", 1); dot.attr("cx", xc(s.d)).attr("cy", y1(s.cum)).attr("opacity", 1);
        const top = [...s.r].filter((t) => t.spend > 0).sort((a, b) => b.spend - a.spend).slice(0, 3);
        tip.innerHTML = `<div style="opacity:.7">${dlabel(s.d)}</div><div>Day <b>${fm(s.v)}</b> · Running <b>${f0(s.cum)}</b></div>${top.map((t) => `<div style="opacity:.8">${esc(t.merch)} <b>${f0(t.spend)}</b></div>`).join("")}`;
        const r = host.getBoundingClientRect(); const px = xc(s.d) / W * r.width; tip.style.left = Math.max(90, Math.min(r.width - 90, px)) + "px"; tip.style.top = y1(s.cum) / H * r.height + "px"; tip.style.opacity = "1"; })
      .on("mouseleave touchend", () => { tip.style.opacity = "0"; guide.attr("opacity", 0); dot.attr("opacity", 0); })
      .on("click", (ev) => setFilter("day", at(ev).d));
    $("paceLegend").innerHTML = `<span><i class="sw" style="background:var(--accent)"></i>Running total</span><span><i class="sw" style="background:var(--c1)"></i><i class="sw" style="background:var(--c2)"></i><i class="sw" style="background:var(--c3)"></i>Daily, by category</span>`;
  }

  // ---------- donut
  function renderDonut(rows) {
    const drill = S.drill;
    const data2 = drill
      ? d3.rollups(rows.filter((t) => groupOf(t) === drill), (v) => d3.sum(v, (t) => t.spend), catOf).filter((d) => d[1] > 0).sort((a, b) => b[1] - a[1])
      : d3.rollups(rows, (v) => d3.sum(v, (t) => t.spend), groupOf).filter((d) => d[1] > 0).sort((a, b) => b[1] - a[1]);
    const total = d3.sum(data2, (d) => d[1]);
    const colorOf = (n, i) => (drill ? `color-mix(in srgb, ${GCOL[drill]} ${100 - i * Math.min(18, 70 / Math.max(1, data2.length - 1))}%, var(--surface))` : GCOL[n]);
    const host = $("donut"); let svg = d3.select(host).select("svg");
    if (svg.empty()) svg = d3.select(host).insert("svg", ":first-child").attr("viewBox", "-120 -120 240 240").attr("role", "img").attr("aria-label", "Spending by category");
    const pie = d3.pie().value((d) => d[1]).sort(null).padAngle(0.012);
    const arc = d3.arc().innerRadius(76).outerRadius(112).cornerRadius(4);
    const sel = svg.selectAll("path.arc").data(pie(data2), (d) => d.data[0]);
    sel.exit().transition().duration(300).attrTween("d", function (d) { const i = d3.interpolate(d, { ...d, startAngle: d.endAngle }); return (t) => arc(i(t)); }).remove();
    sel.enter().append("path").attr("class", "arc").each(function (d) { this._c = { ...d, endAngle: d.startAngle }; })
      .merge(sel).attr("fill", (d, i) => colorOf(d.data[0], i)).attr("stroke", "var(--surface)").attr("stroke-width", 1.5)
      .on("click", (ev, d) => { if (!S.drill) { S.drill = d.data[0]; S.f.group = d.data[0]; S.f.cat = null; renderAll(); } else setFilter("cat", d.data[0]); })
      .on("mouseenter", (ev, d) => { $("donutT").textContent = f0(d.data[1]); $("donutL").textContent = d.data[0] + " · " + Math.round(d.data[1] / total * 100) + "%"; })
      .on("mouseleave", () => { $("donutT").textContent = f0(total); $("donutL").textContent = drill || "All categories"; })
      .transition().duration(reduced() ? 0 : 750).ease(d3.easeCubicOut).attrTween("d", function (d) { const i = d3.interpolate(this._c || d, d); this._c = d; return (t) => arc(i(t)); });
    svg.selectAll("path.arc title").remove();
    svg.selectAll("path.arc").append("title").text((d) => d.data[0] + ": " + f0(d.data[1]));
    $("donutT").textContent = f0(total); $("donutL").textContent = drill || "All categories";
    $("crumb").innerHTML = drill ? `<button type="button" id="crumbBack">All categories</button><span>›</span><span style="color:var(--fg)">${esc(drill)}</span>` : `<span>Click a slice or row to drill in</span>`;
    $("catList").innerHTML = data2.map(([n, v], i) => `<button class="cat-row" type="button" data-cat="${esc(n)}"><span class="sw" style="background:${colorOf(n, i)}"></span><span class="name">${esc(n)}</span><span class="amt">${f0(v)} <span style="color:var(--fg-3)">${Math.round(v / total * 100)}%</span></span><span class="share"><i style="width:${v / data2[0][1] * 100}%;background:${colorOf(n, i)}"></i></span></button>`).join("")
      || `<div style="color:var(--fg-3);padding:8px">No spending in this period.</div>`;
  }
  on("click", (e) => {
    if (e.target.id === "crumbBack") { S.drill = null; S.f.group = null; S.f.cat = null; renderAll(); return; }
    const r = e.target.closest(".cat-row"); if (r) { const n = r.dataset.cat; if (!S.drill) { S.drill = n; S.f.group = n; S.f.cat = null; } else { S.f.cat = n; S.f.group = null; } S.limit = 25; renderAll(); }
  });

  // ---------- calendar
  function renderCal(rows) {
    const p = PERIODS[S.period];
    const start = d3.timeMonday.floor(pd(p.from)), end = pd(p.to);
    const byDay = d3.rollup(rows, (v) => d3.sum(v, (t) => t.spend), (t) => t.d);
    const max = d3.max([...byDay.values()]) || 1;
    let html = "<span></span>" + ["M", "T", "W", "T", "F", "S", "S"].map((d) => `<span class="dow">${d}</span>`).join("");
    for (let w = start; w <= end; w = d3.timeDay.offset(w, 7)) {
      html += `<span class="wk">${w.getDate()} ${MON[w.getMonth()]}</span>`;
      for (let i = 0; i < 7; i++) {
        const d = d3.timeDay.offset(w, i), k = iso(d);
        const inData = k >= p.dataFrom && k <= p.dataTo && k >= p.from && k <= p.to;
        if (!inData) { html += `<span class="day empty" aria-hidden="true"></span>`; continue; }
        const v = Math.max(0, byDay.get(k) || 0), pct = Math.round(Math.sqrt(v / max) * 92) + 4;
        html += `<button class="day ${S.f.day === k ? "on" : ""}" type="button" data-day="${k}" title="${dlabel(k)}: ${fm(v)}" style="background:color-mix(in srgb, var(--accent) ${v ? pct : 0}%, var(--line-soft));color:${v && pct > 55 ? "var(--accent-ink)" : "var(--fg-3)"}">${d.getDate()}</button>`;
      }
    }
    $("cal").innerHTML = html;
  }
  on("click", (e) => { const d = e.target.closest(".day[data-day]"); if (d) setFilter("day", S.f.day === d.dataset.day ? null : d.dataset.day); });

  // ---------- people
  function renderPeople() {
    const all = TX.filter(inPeriod), total = sum(all) || 1;
    const cards = cardIds.map((c, i) => { const r = all.filter((t) => t.c === c); const g = d3.rollups(r, (v) => d3.sum(v, (t) => t.spend), groupOf).sort((a, b) => b[1] - a[1]); return { c, v: sum(r), n: r.filter((t) => t.spend > 0).length, top: g[0], col: CARD_COL[i % CARD_COL.length] }; });
    $("split").innerHTML = cards.map((k) => `<i style="width:${Math.max(0, k.v) / total * 100}%;background:${k.col}" title="${esc(names[k.c])}"></i>`).join("");
    $("people").innerHTML = cards.map((k) => `<div class="person"><div class="avatar" style="background:${k.col}">${esc((names[k.c] || "?").replace(/^Card ··/, "#").slice(0, 1).toUpperCase())}</div>
      <input value="${esc(names[k.c])}" data-name="${k.c}" aria-label="Name for ${esc(names[k.c])}" maxlength="80">
      <span class="amt">${f0(k.v)}</span>
      <div class="bar"><i style="width:${Math.max(0, k.v) / total * 100}%;background:${k.col}"></i></div>
      <div class="meta">${Math.round(k.v / total * 100)}% · ${k.n} purchases${k.top ? ` · mostly ${esc(k.top[0]).toLowerCase()}` : ""}</div></div>`).join("");
  }
  on("change", async (e) => {
    const n = e.target.closest("[data-name]"); if (!n) return;
    const v = n.value.trim(); if (!v || v === names[n.dataset.name]) { n.value = names[n.dataset.name]; return; }
    try { const a = await act.renameAccount(n.dataset.name, v); names[a.id] = a.name; toast("Name saved"); } catch (err) { fail(err); }
    renderAll();
  });
  on("keydown", (e) => { if (e.target.matches("[data-name]") && e.key === "Enter") e.target.blur(); });

  // ---------- merchants
  function renderMerchants(rows) {
    const m = d3.rollups(rows.filter((t) => t.spend > 0), (v) => ({ v: d3.sum(v, (t) => t.spend), n: v.length, g: groupOf(v[0]) }), (t) => t.merch).sort((a, b) => b[1].v - a[1].v).slice(0, 8);
    const max = m.length ? m[0][1].v : 1;
    $("mer").innerHTML = m.map(([n, o]) => `<button class="mer-row" type="button" data-merch="${esc(n)}"><span class="nm">${esc(n)}<small>${o.n}×</small></span><span class="amt">${f0(o.v)}</span><span class="track"><i style="width:${o.v / max * 100}%;background:${GCOL[o.g]}"></i></span></button>`).join("");
  }
  on("click", (e) => { const r = e.target.closest("[data-merch]"); if (r) setFilter("merchant", r.dataset.merch); });

  // ---------- recurring (detected by the server across all data)
  function renderSubs() {
    const subs = data.recurring;
    const monthly = d3.sum(subs, (s) => Number(s.amount));
    $("subsSub").innerHTML = subs.length ? `About <b class="num" style="color:var(--fg)">${f0(monthly)}</b> a month across ${subs.length} merchant${subs.length > 1 ? "s" : ""}` : "Detected from merchant and amount";
    $("subs").innerHTML = subs.slice(0, 7).map((o) => `<div class="sub-row"><span class="sub-ic">${esc(o.name.slice(0, 1))}</span><span class="nm">${esc(o.name)}<small>${o.count} charge${o.count > 1 ? "s" : ""} · last ${dlabel(o.last_date)}</small></span><span class="amt">${fm(Number(o.amount))}</span></div>`).join("")
      || `<div style="color:var(--fg-3);font-size:12.5px">Nothing recurring found yet. It shows up after two monthly charges.</div>`;
  }

  // ---------- insights
  function renderInsights(rows) {
    const days = dataDays(), weeks = days / 7;
    const eat = rows.filter((t) => ["Restaurants & takeaway", "Cafe & coffee"].includes(catOf(t)));
    const freq = d3.rollups(rows.filter((t) => t.spend > 0), (v) => ({ n: v.length, v: d3.sum(v, (t) => t.spend) }), (t) => t.merch).sort((a, b) => b[1].n - a[1].n)[0];
    const fees = rows.filter((t) => ["Fees", "Loans"].includes(catOf(t)));
    const byDay = d3.rollup(rows, (v) => d3.sum(v, (t) => t.spend), (t) => t.d);
    const unc = rows.filter((t) => t.cid === uncId);
    const bigDay = [...byDay].sort((a, b) => b[1] - a[1])[0];
    const bigTop = bigDay ? [...d3.rollup(rows.filter((t) => t.d === bigDay[0] && t.spend > 0), (v) => d3.sum(v, (t) => t.spend), (t) => t.merch)].sort((a, b) => b[1] - a[1]).slice(0, 2).map(([m]) => m) : [];
    const cards = [
      { k: "Eating out", h: f0(sum(eat) / weeks) + " a week", p: `${eat.length} restaurant, takeaway and cafe purchases, ${f0(sum(eat))} in total.`, c: "var(--c1)" },
      freq ? { k: "Most frequent", h: esc(freq[0]), p: `${freq[1].n} purchases adding up to ${fm(freq[1].v)}. Small, but it is your most regular stop.`, c: "var(--c2)" } : null,
      bigDay ? { k: "Biggest day", h: dlabel(bigDay[0]), p: `${fm(bigDay[1])} in one day, led by ${bigTop.map(esc).join(", ")}.`, c: "var(--c3)" } : null,
      fees.length ? { k: "Fees and interest", h: fm(sum(fees)), p: `${fees.length} fee and interest charge${fees.length > 1 ? "s" : ""} in this period.`, c: "var(--c4)" }
        : { k: "To sort", h: unc.length + " uncategorised", p: "Assign a category in the table and it is remembered.", c: "var(--c4)" },
    ].filter(Boolean);
    $("insights").innerHTML = cards.map((c, i) => `<div class="insight fade-in" style="--k:${c.c};animation-delay:${i * 70}ms"><span class="k">${c.k}</span><span class="h">${c.h}</span><p>${c.p}</p></div>`).join("");
  }

  // ---------- table
  function setFilter(k, v) {
    S.f = { group: null, cat: null, day: null, merchant: null, ...(k === "day" || k === "merchant" ? { group: S.f.group, cat: S.f.cat } : {}), [k]: v };
    S.limit = 25; renderAll();
    if (v) $("txCard").scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "start" });
  }
  function renderTable(rows) {
    let r = rows;
    if (S.f.group) r = r.filter((t) => groupOf(t) === S.f.group);
    if (S.f.cat) r = r.filter((t) => catOf(t) === S.f.cat);
    if (S.f.day) r = r.filter((t) => t.d === S.f.day);
    if (S.f.merchant) r = r.filter((t) => t.merch === S.f.merchant);
    if (S.q) { const q = S.q.toLowerCase(); r = r.filter((t) => (t.merch + " " + t.desc + " " + catOf(t) + " " + Math.abs(t.spend).toFixed(2)).toLowerCase().includes(q)); }
    r = [...r].sort((a, b) => (S.sort.k === "a" ? (a.spend - b.spend) * S.sort.dir : (a.d < b.d ? -1 : a.d > b.d ? 1 : b.i - a.i) * S.sort.dir));
    const chips = []; if (S.f.group) chips.push(["group", S.f.group]); if (S.f.cat) chips.push(["cat", S.f.cat]); if (S.f.day) chips.push(["day", dlabel(S.f.day)]); if (S.f.merchant) chips.push(["merchant", S.f.merchant]);
    $("chips").innerHTML = chips.map(([k, l]) => `<button class="chip" type="button" data-clear="${k}" aria-label="Remove filter ${esc(l)}">${esc(l)}</button>`).join("");
    $("txSub").innerHTML = `${r.length} shown · <span class="num">${fm(sum(r))}</span>`;
    const opts = (sel) => GROUP_NAMES.filter((g) => GROUPS[g].length).map((g) => `<optgroup label="${esc(g)}">${GROUPS[g].map((c) => `<option value="${c.id}" ${c.id === sel ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</optgroup>`).join("");
    $("tbody").innerHTML = r.slice(0, S.limit).map((t) => {
      const g = groupOf(t);
      return `<tr class="tx"><td class="date">${dlabel(t.d)}</td>
      <td><span class="mn">${esc(t.merch)}</span> ${t.p ? '<span class="pill pend">Pending</span>' : ""}${t.src === "rule" ? '<span class="pill rule" title="Categorised by a rule">rule</span>' : ""}${t.src === "user" ? '<span class="pill rule">edited</span>' : ""}<span class="ds">${esc(t.desc)}</span></td>
      <td><span class="cdot" style="background:${GCOL[g]}"></span><select class="catsel" data-tx="${t.id}" aria-label="Category for ${esc(t.merch)}">${opts(t.cid)}</select></td>
      <td class="cardtag">${esc(names[t.c])}</td>
      <td class="r amt ${t.spend < 0 ? "pos" : ""}">${t.spend < 0 ? "+" + fm(-t.spend) : fm(t.spend)}</td></tr>`;
    }).join("") || `<tr><td colspan="5" style="color:var(--fg-3);padding:24px 8px">No transactions match. Clear a filter or change the search.</td></tr>`;
    const more = $("moreBtn"); more.hidden = r.length <= S.limit; more.textContent = `Show more (${r.length - S.limit} left)`;
  }
  on("click", (e) => {
    const c = e.target.closest("[data-clear]"); if (c) { S.f[c.dataset.clear] = null; if (c.dataset.clear === "group") S.drill = null; renderAll(); return; }
    if (e.target.id === "moreBtn") { S.limit += 60; renderAll(); return; }
    const s = e.target.closest("[data-sort]"); if (s) { const k = s.dataset.sort; S.sort = S.sort.k === k ? { k, dir: -S.sort.dir } : { k, dir: -1 }; renderAll(); }
  });
  on("change", async (e) => {
    const s = e.target.closest(".catsel"); if (!s) return;
    const t = TX.find((x) => x.id === s.dataset.tx);
    try {
      const u = await act.setCategory(t.id, s.value);
      t.cid = u.category_id; t.src = u.category_source;
      toast(`Moved to ${catName(t.cid)}. Totals and budgets updated.`);
    } catch (err) { fail(err); }
    renderAll();
  });
  on("input", (e) => { if (e.target.id === "q") { S.q = e.target.value; S.limit = 25; renderTable(base()); } });

  function renderAll() {
    const rows = base();
    renderControls(); renderHero(rows); renderPace(rows); renderInsights(rows); renderDonut(rows); renderBudgets(rows); renderCal(rows); renderPeople(); renderSubs(); renderMerchants(rows); renderTable(rows);
    const y0 = DATA_START.slice(0, 4), y1 = DATA_END.slice(0, 4);
    $("footRange").textContent = `${TX.length} transactions from ${cardIds.length} account${cardIds.length === 1 ? "" : "s"}, ${dlabel(DATA_START)}${y0 !== y1 ? " " + y0 : ""} to ${dlabel(DATA_END)} ${y1}`;
  }
  let rz; const onResize = () => { clearTimeout(rz); rz = setTimeout(() => renderPace(base()), 150); };
  addEventListener("resize", onResize);
  cleanups.push(() => removeEventListener("resize", onResize));
  renderAll();
  return () => { cleanups.forEach((f) => f()); clearTimeout(tt); root.innerHTML = ""; };
}
