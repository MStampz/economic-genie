import { useEffect, useState } from "react";
import { api, type Category, type Rule } from "../api";

export default function Rules({ gid, embedded }: { gid: string; embedded?: boolean }) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [cats, setCats] = useState<Category[]>([]);
  const [pattern, setPattern] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [newCat, setNewCat] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () => {
    api.rules(gid).then(setRules).catch((e) => setError(e.message));
    api.categories(gid).then(setCats).catch(() => {});
  };
  useEffect(load, [gid]);

  async function act(fn: () => Promise<unknown>, done?: string) {
    setError(""); setMsg("");
    try { await fn(); if (done) setMsg(done); load(); } catch (e) { setError((e as Error).message); }
  }

  async function importFile(file: File | undefined) {
    if (!file) return;
    const text = await file.text();
    act(async () => {
      const r = await api.importRules(gid, JSON.parse(text));
      setMsg(`Added ${r.updated} rules. Tap "Apply rules" to use them on existing transactions.`);
    });
  }

  const catName = new Map(cats.map((c) => [c.id, c.name]));
  return (
    <section>
      {!embedded && <h1>Category rules</h1>}
      <p className="muted">A rule puts every transaction whose merchant or description contains the text into a category.
        Categories you pick by hand are never changed by rules.</p>
      <form className="card form" onSubmit={(e) => { e.preventDefault(); act(async () => { await api.createRule(gid, pattern, categoryId); setPattern(""); }); }}>
        <label>When the text contains<input value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="e.g. bunnings" required minLength={2} /></label>
        <label>Put it in
          <select value={categoryId} onChange={(e) => setCategoryId(e.target.value)} required>
            <option value="" disabled>Choose a category</option>
            {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <button className="primary">Add rule</button>
      </form>
      <form className="inline" onSubmit={(e) => { e.preventDefault(); act(async () => { await api.createCategory(gid, newCat); setNewCat(""); }, "Category added."); }}>
        <input value={newCat} onChange={(e) => setNewCat(e.target.value)} placeholder="New category name" required />
        <button>Add category</button>
      </form>
      <div className="row-actions">
        <button onClick={() => act(async () => { const r = await api.applyRules(gid); setMsg(`Updated ${r.updated} transactions.`); })}>Apply rules</button>
        <label className="button">Import rules (JSON)<input type="file" accept=".json,application/json" hidden onChange={(e) => importFile(e.target.files?.[0])} /></label>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {error && <p className="error">{error}</p>}
      <ul className="list">
        {rules.map((r) => (
          <li key={r.id}>
            <span><code>{r.pattern}</code> → {catName.get(r.category_id)}</span>
            <button className="link danger" onClick={() => act(() => api.deleteRule(gid, r.id))}>Remove</button>
          </li>
        ))}
        {rules.length === 0 && <li className="muted">No rules yet.</li>}
      </ul>
    </section>
  );
}
