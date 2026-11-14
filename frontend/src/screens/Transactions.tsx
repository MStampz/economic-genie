import { useEffect, useMemo, useState } from "react";
import { api, money, type Account, type Category, type Transaction } from "../api";

const PAGE = 100;

export default function Transactions({ gid }: { gid: string }) {
  const [items, setItems] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [cats, setCats] = useState<Category[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [q, setQ] = useState("");
  const [onlyUncat, setOnlyUncat] = useState(false);
  const [hideTransfers, setHideTransfers] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.categories(gid).then(setCats).catch(() => {});
    api.accounts(gid).then(setAccounts).catch(() => {});
  }, [gid]);

  const params = useMemo(
    () => ({ q, uncategorised: onlyUncat, include_transfers: !hideTransfers, limit: PAGE }),
    [q, onlyUncat, hideTransfers],
  );
  useEffect(() => {
    const t = setTimeout(() => {
      api.transactions(gid, { ...params, offset: 0 })
        .then((p) => { setItems(p.items); setTotal(p.total); setError(""); })
        .catch((e) => setError(e.message));
    }, 200);
    return () => clearTimeout(t);
  }, [gid, params]);

  async function more() {
    const p = await api.transactions(gid, { ...params, offset: items.length });
    setItems([...items, ...p.items]);
  }

  async function setCategory(t: Transaction, categoryId: string) {
    const updated = await api.setCategory(gid, t.id, categoryId || null);
    setItems(items.map((x) => (x.id === t.id ? updated : x)));
  }

  async function setTransfer(t: Transaction, value: boolean | null) {
    try {
      await api.setTransfer(gid, t.id, value);
      // A change can pair or split the other leg too, so reload the page of results.
      const p = await api.transactions(gid, { ...params, offset: 0, limit: Math.max(PAGE, items.length) });
      setItems(p.items); setTotal(p.total);
    } catch (e) { setError((e as Error).message); }
  }

  async function remove(t: Transaction) {
    if (!confirm(`Delete “${t.merchant || t.description}” (${money(t.amount)})? Importing the same file again brings it back.`)) return;
    try {
      await api.deleteTransaction(gid, t.id);
      setItems(items.filter((x) => x.id !== t.id)); setTotal(total - 1);
    } catch (e) { setError((e as Error).message); }
  }

  const catName = new Map(cats.map((c) => [c.id, c.name]));
  const accName = new Map(accounts.map((a) => [a.id, a.name]));
  const byDay = new Map<string, Transaction[]>();
  for (const t of items) byDay.set(t.posted_date, [...(byDay.get(t.posted_date) ?? []), t]);

  return (
    <section>
      <h1>Activity</h1>
      <input className="search" placeholder="Search merchant or description" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="chips">
        <button className={onlyUncat ? "chip on" : "chip"} onClick={() => setOnlyUncat(!onlyUncat)}>Needs a category</button>
        <button className={hideTransfers ? "chip on" : "chip"} onClick={() => setHideTransfers(!hideTransfers)}>Hide own transfers</button>
      </div>
      {error && <p className="error">{error}</p>}
      {total === 0 && !error && <p className="empty">No transactions yet. Import a CSV file from your bank to get started.</p>}
      {[...byDay.entries()].map(([day, rows]) => (
        <div key={day} className="day">
          <h3>{new Date(day + "T00:00").toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short", year: "numeric" })}</h3>
          {rows.map((t) => (
            <div key={t.id} className={`tx ${t.is_internal_transfer ? "transfer" : ""}`}>
              <div className="tx-main">
                <div className="tx-title">{t.merchant || t.description}</div>
                <div className="tx-sub">
                  {accName.get(t.account_id) ?? ""}{t.is_pending && <span className="badge">pending</span>}
                  {t.is_internal_transfer && <span className="badge">own transfer</span>}
                  {t.is_internal_transfer
                    ? <button className="link" onClick={() => setTransfer(t, false)}>Not a transfer</button>
                    : <button className="link" onClick={() => setTransfer(t, true)}>Mark as own transfer</button>}
                  {t.transfer_user !== null && <button className="link" onClick={() => setTransfer(t, null)} title="Let the app decide again">↺ Automatic</button>}
                  <button className="link danger" onClick={() => remove(t)}>Delete</button>
                </div>
              </div>
              <div className="tx-side">
                <div className={Number(t.amount) < 0 ? "amount out" : "amount in"}>{money(t.amount)}</div>
                <select className={`cat-pick ${t.category_source}`} value={t.category_id ?? ""}
                  title={t.category_source === "user" ? "Chosen by you" : t.category_source === "rule" ? "Set by a rule" : "From the bank"}
                  onChange={(e) => setCategory(t, e.target.value)}>
                  <option value="">{t.category_source === "user" ? "↺ Automatic" : catName.get(t.category_id ?? "") ?? "Uncategorised"}</option>
                  {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </div>
            </div>
          ))}
        </div>
      ))}
      {items.length < total && <button className="more" onClick={more}>Show more ({total - items.length} left)</button>}
    </section>
  );
}
