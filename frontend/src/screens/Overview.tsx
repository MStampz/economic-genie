import { useEffect, useMemo, useState } from "react";
import { api, money, money0, type Account, type Overview as Data, type PostLine, type Transaction } from "../api";
import { Calendar, Donut, SpendChart, postColor, type Slice } from "../components/charts";

type Pick = Slice & { category_ids: string[] };
type View = "categories" | "posts";

function remembered(): View {
  try { return localStorage.getItem("genie.breakdown") === "posts" ? "posts" : "categories"; } catch { return "categories"; }
}

const pct = (a: number, b: number) => (b > 0 ? Math.round((a / b) * 100) : 0);
const dayLabel = (s: string) => new Date(s + "T00:00").toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" });

export default function Overview({ gid, onSetBudget }: { gid: string; onSetBudget: () => void }) {
  const [period, setPeriod] = useState<string | undefined>(undefined);
  const [accountId, setAccountId] = useState<string | undefined>(undefined);
  const [data, setData] = useState<Data | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [post, setPost] = useState<string | null>(null);
  const [view, setView] = useState<View>(remembered);
  const [day, setDay] = useState<string | null>(null);

  useEffect(() => { api.accounts(gid).then(setAccounts).catch(() => {}); }, [gid]);
  useEffect(() => {
    api.overview(gid, period, accountId).then((d) => { setData(d); setError(""); }).catch((e) => setError(e.message));
  }, [gid, period, accountId]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <div className="card center"><div className="spinner" /> Adding it all up…</div>;
  if (data.months.length === 0) {
    return (
      <section>
        <h1>Overview</h1>
        <p className="empty">Import your first CSV file to see where your money goes.</p>
      </section>
    );
  }

  const p = data.period;
  const accName = new Map(accounts.map((a) => [a.id, a.name]));
  const postById = new Map(data.posts.map((x) => [x.id, x]));
  const budgeted = data.posts.filter((x) => x.id !== "none");
  const biggestCat = data.categories.find((x) => Number(x.spent) > 0);
  const shownView: View = budgeted.length ? view : "categories";
  const total = Number(data.total);
  const isCurrent = p.elapsed < 1;

  return (
    <section className="overview">
      <div className="filters">
        <div className="chips scroll">
          {data.months.slice(0, 6).map((m) => (
            <button key={m.key} className={p.key === m.key ? "chip on" : "chip"} onClick={() => { setPeriod(m.key); setDay(null); }}>
              {m.label.replace(/ \d{4}$/, "")}
            </button>
          ))}
          <button className={p.key === "all" ? "chip on" : "chip"} onClick={() => { setPeriod("all"); setDay(null); }}>All data</button>
        </div>
        {accounts.length > 1 && (
          <select className="account-pick" value={accountId ?? ""} onChange={(e) => setAccountId(e.target.value || undefined)}>
            <option value="">All accounts</option>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        )}
      </div>

      <div className="card hero">
        <div className="hero-top">
          <div className="eyebrow">Spent · {p.label}{isCurrent ? " so far" : ""}</div>
          <div className="hero-number">{money0(total)}<span>.{money(total).split(".")[1] ?? "00"}</span></div>
          <div className="hero-sub">
            {p.data_from && p.data_to && <>{p.days_with_data} days of data · {dayLabel(p.data_from)} to {dayLabel(p.data_to)}</>}
          </div>
        </div>
        <div className="stats">
          <div><span>Per day</span><b>{money0(data.per_day)}</b></div>
          <div><span>Purchases</span><b>{data.purchases}</b></div>
          <div>
            <span>Biggest category</span>
            <b>{biggestCat ? <><i className="dot" style={{ background: postColor(biggestCat.color) }} />{biggestCat.name} <em className="muted">{pct(Number(biggestCat.spent), total)}%</em></> : "None"}</b>
          </div>
          <div><span>Largest purchase</span><b>{data.biggest_purchase ? `${money0(data.biggest_purchase.spent)} · ${data.biggest_purchase.name}` : "None"}</b></div>
        </div>
        {data.budgets_set > 0 ? (
          <BudgetSummary data={data} />
        ) : (
          <button className="hero-cta" onClick={onSetBudget}>Set monthly amounts to see over and under budget →</button>
        )}
      </div>

      <WhereItWent data={data} view={shownView} setView={(v) => { setView(v); setPost(null); try { localStorage.setItem("genie.breakdown", v); } catch { /* private mode */ } }}
        selected={post} onSelect={(id) => { setPost(id); setDay(null); }} />

      {(post || day) && (
        <Drill gid={gid} pick={post ? picks(data, shownView).find((x) => x.id === post) ?? null : null} day={day} period={p} accountId={accountId}
          accName={accName} onClose={() => { setPost(null); setDay(null); }} />
      )}

      <div className="card">
        <h2>Running total</h2>
        <p className="muted small">How spending adds up over {isCurrent ? "the month so far" : "the period"}, and each day split by budget post. Tap a day to see it.</p>
        <SpendChart days={data.days} posts={data.posts} onDay={(d) => setDay(day === d ? null : d)} />
      </div>

      <Insights data={data} />

      <div className="budget-wrap">
        <div className="card">
          <div className="card-head">
            <h2>Budget</h2>
            <button className="link" onClick={onSetBudget}>Edit</button>
          </div>
          <p className="muted small">{isCurrent ? "The marker shows where you'd be if you spent evenly through the month." : p.key === "all" ? "Monthly amounts scaled to the whole period." : "Full month."}</p>
          {budgeted.length === 0 && <p className="muted">No budget posts yet. <button className="link" onClick={onSetBudget}>Set up your budget</button></p>}
          {data.headings.map((h) => (
            <div key={h.id} className="budget-group">
              <div className="budget-head">
                <span>{h.name}</span>
                <span className="num">{money0(h.spent)}{h.over > 0 && <b className="over-chip">⚠ {h.over} over</b>}</span>
              </div>
              {budgeted.filter((x) => x.heading === h.name).map((x) => <BudgetRow key={x.id} line={x} onClick={() => { setView("posts"); setPost(x.id); setDay(null); window.scrollTo({ top: 0, behavior: "smooth" }); }} />)}
            </div>
          ))}
        </div>
      </div>

      <div className="three-col">
        <div className="card">
          <h2>Spending calendar</h2>
          <p className="muted small">Darker means more spent. Tap a day.</p>
          <Calendar days={data.days} selected={day} onSelect={(d) => { setDay(d); setPost(null); }} />
        </div>
        <div className="card">
          <h2>Who spent it</h2>
          <p className="muted small">By account.</p>
          <ul className="bars">
            {data.accounts.map((a) => {
              const top = a.top_post ? postById.get(a.top_post) : undefined;
              return (
                <li key={a.id}>
                  <div className="bar-row"><span>{a.name}</span><span className="num">{money0(a.spent)}</span></div>
                  <div className="track"><div style={{ width: `${pct(Number(a.spent), Number(data.accounts[0].spent))}%`, background: "var(--c1)" }} /></div>
                  <div className="muted small">{a.count} purchases{top ? ` · mostly ${top.name}` : ""}</div>
                </li>
              );
            })}
          </ul>
        </div>
        <div className="card">
          <h2>Top merchants</h2>
          <p className="muted small">All stores of a chain combined.</p>
          <ul className="bars">
            {data.merchants.map((m) => (
              <li key={m.name}>
                <div className="bar-row"><span>{m.name} <em className="muted">{m.count}×</em></span><span className="num">{money0(m.spent)}</span></div>
                <div className="track"><div style={{ width: `${pct(Number(m.spent), Number(data.merchants[0].spent))}%`, background: "var(--c7)" }} /></div>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {data.recurring.length > 0 && (
        <div className="card">
          <h2>Recurring and subscriptions</h2>
          <p className="muted small">About <b>{money0(data.recurring.reduce((a, r) => a + Number(r.amount), 0))}</b> a month across {data.recurring.length} merchants.</p>
          <ul className="list small">
            {data.recurring.map((r) => (
              <li key={r.name}>
                <span>{r.name} <span className="muted">· {r.count} charge{r.count === 1 ? "" : "s"} · last {dayLabel(r.last_date)}</span></span>
                <span className="num">{money(r.amount)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="footnote">Payments between your own accounts are not counted as spending. Salary and other money in is left out; refunds lower spending.</p>
    </section>
  );
}

function BudgetSummary({ data }: { data: Data }) {
  const spent = Number(data.budget_spent), budget = Number(data.budget_total);
  const over = spent > budget;
  return (
    <div className={`budget-summary ${data.budgets_over ? "has-over" : ""}`}>
      <div className="bar-row">
        <span>{data.budgets_set} budget{data.budgets_set === 1 ? "" : "s"} set{data.budgets_over > 0 && <b className="over-text"> · {data.budgets_over} over</b>}</span>
        <span className="num">{money0(spent)} / {money0(budget)}</span>
      </div>
      <div className="track big"><div className={over ? "bad" : "good"} style={{ width: `${Math.min(pct(spent, budget), 100)}%` }} /></div>
    </div>
  );
}

function BudgetRow({ line, onClick }: { line: PostLine; onClick: () => void }) {
  const spent = Number(line.spent);
  if (line.budget === null) {
    return (
      <div className="budget-row" onClick={onClick}>
        <div className="bar-row"><span><i className="dot" style={{ background: postColor(line.color) }} />{line.name}</span><span className="num">{money0(spent)}</span></div>
        <div className="muted small">No amount yet</div>
      </div>
    );
  }
  const budget = Number(line.budget);
  const over = spent > budget;
  const ahead = !over && line.pace !== null && spent > Number(line.pace);
  return (
    <div className={`budget-row ${over ? "over" : ""}`} onClick={onClick}>
      <div className="bar-row">
        <span><i className="dot" style={{ background: postColor(line.color) }} />{line.name}</span>
        <span className="num">{money0(spent)} / {money0(budget)}</span>
      </div>
      <div className="track">
        <div className={over ? "bad" : ahead ? "warn" : "good"} style={{ width: `${Math.min(pct(spent, budget), 100)}%` }} />
        {line.pace !== null && <i className="pace" style={{ left: `${Math.min(pct(Number(line.pace), budget), 100)}%` }} />}
      </div>
      <div className="bar-row small">
        {over ? <span className="status bad">⚠ Over by {money0(spent - budget)}</span>
          : ahead ? <span className="status warn">◔ Ahead of pace</span>
          : <span className="status good">✓ On track</span>}
        <span className="muted">{over ? `${pct(spent, budget)}% of budget` : `${money0(budget - spent)} left`}</span>
      </div>
    </div>
  );
}

function Insights({ data }: { data: Data }) {
  const i = data.insights;
  const cards = [
    Number(i.eating_out_total) > 0 && { label: "Eating out", value: `${money0(i.eating_out_per_week)} a week`, text: `${i.eating_out_count} restaurant, takeaway and café purchases, ${money0(i.eating_out_total)} in total.`, c: 2 },
    i.most_frequent && { label: "Most frequent", value: i.most_frequent.name, text: `${i.most_frequent.count} purchases adding up to ${money(i.most_frequent.spent)}.`, c: 1 },
    i.biggest_day && { label: "Biggest day", value: dayLabel(i.biggest_day.date), text: `${money(i.biggest_day.total)} in one day${i.biggest_day_merchants.length ? `, led by ${i.biggest_day_merchants.join(" and ")}` : ""}.`, c: 5 },
    Number(i.fees_total) > 0 && { label: "Fees and interest", value: money(i.fees_total), text: `${i.fees_count} charge${i.fees_count === 1 ? "" : "s"} you could avoid.`, c: 4 },
  ].filter(Boolean) as { label: string; value: string; text: string; c: number }[];
  if (!cards.length) return null;
  return (
    <div className="insights">
      {cards.map((c) => (
        <div key={c.label} className="card insight" style={{ borderLeftColor: postColor(c.c) }}>
          <div className="eyebrow">{c.label}</div>
          <div className="insight-value">{c.value}</div>
          <p className="muted small">{c.text}</p>
        </div>
      ))}
    </div>
  );
}

function Drill({ gid, pick: post, day, period, accountId, accName, onClose }: {
  gid: string; pick: Pick | null; day: string | null; period: Data["period"]; accountId?: string;
  accName: Map<string, string>; onClose: () => void;
}) {
  const [items, setItems] = useState<Transaction[] | null>(null);
  const params = useMemo(() => {
    const q: Record<string, string | number | boolean | string[]> = { include_transfers: false, limit: 200 };
    q.date_from = day ?? period.start;
    q.date_to = day ?? period.end;
    if (post) q.category_ids = post.category_ids.length ? post.category_ids : ["00000000-0000-0000-0000-000000000000"];
    if (accountId) q.account_id = accountId;
    return q;
  }, [post, day, period, accountId]);
  useEffect(() => { setItems(null); api.transactions(gid, params).then((p) => setItems(p.items)).catch(() => setItems([])); }, [gid, params]);
  const title = post && day ? `${post.name} on ${dayLabel(day)}` : post ? post.name : day ? dayLabel(day) : "";
  return (
    <div className="card drill">
      <div className="card-head">
        <h2>{post && <i className="dot" style={{ background: postColor(post.color) }} />}{title}</h2>
        <button className="link" onClick={onClose}>Close</button>
      </div>
      {items === null ? <div className="spinner" /> : items.length === 0 ? <p className="muted">No transactions.</p> : (
        <ul className="list small">
          {items.map((t) => (
            <li key={t.id}>
              <span>{dayLabel(t.posted_date)} · {t.merchant || t.description} <span className="muted">· {accName.get(t.account_id)}</span></span>
              <span className={Number(t.amount) < 0 ? "num" : "num in"}>{money(-Number(t.amount))}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function picks(data: Data, view: View): Pick[] {
  if (view === "posts") {
    return data.posts.map((x) => ({ id: x.id, name: x.name, color: x.color, spent: x.spent, category_ids: x.category_ids }));
  }
  return data.categories
    .filter((c) => c.id !== null)
    .map((c) => ({ id: c.id as string, name: c.name, color: c.color, spent: c.spent, category_ids: [c.id as string] }));
}

function WhereItWent({ data, view, setView, selected, onSelect }: {
  data: Data; view: View; setView: (v: View) => void; selected: string | null; onSelect: (id: string | null) => void;
}) {
  const hasBudget = data.posts.some((x) => x.id !== "none");
  const items = picks(data, hasBudget ? view : "categories").filter((x) => Number(x.spent) > 0);
  const total = Number(data.total);
  const top = Number(items[0]?.spent ?? 0);
  return (
    <div className="card">
      <div className="card-head">
        <h2>Where it went</h2>
        {hasBudget && (
          <div className="segmented small">
            <button className={view === "categories" ? "on" : ""} onClick={() => setView("categories")}>Categories</button>
            <button className={view === "posts" ? "on" : ""} onClick={() => setView("posts")}>Budget posts</button>
          </div>
        )}
      </div>
      <p className="muted small">Biggest first. Tap one to see its transactions.</p>
      <div className="where">
        <Donut items={items} total={data.total} selected={selected} onSelect={onSelect} />
        <ul className="bars">
          {items.map((x) => (
            <li key={x.id} className={selected && selected !== x.id ? "dim" : ""} onClick={() => onSelect(selected === x.id ? null : x.id)}>
              <div className="bar-row">
                <span><i className="dot" style={{ background: postColor(x.color) }} />{x.name}</span>
                <span className="num">{money(x.spent)} <em>{pct(Number(x.spent), total)}%</em></span>
              </div>
              <div className="track"><div style={{ width: `${pct(Number(x.spent), top)}%`, background: postColor(x.color) }} /></div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
