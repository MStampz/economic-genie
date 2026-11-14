import { useEffect, useState } from "react";
import { api, money0, type Budget as Data, type BudgetPost, type Category } from "../api";
import { postColor } from "../components/charts";
import Rules from "./Rules";

export default function Budget({ gid }: { gid: string }) {
  const [view, setView] = useState<"budget" | "rules">("budget");
  return (
    <section>
      <h1>Budget</h1>
      <div className="segmented wide">
        <button className={view === "budget" ? "on" : ""} onClick={() => setView("budget")}>Budget posts</button>
        <button className={view === "rules" ? "on" : ""} onClick={() => setView("rules")}>Category rules</button>
      </div>
      {view === "budget" ? <BudgetSetup gid={gid} /> : <Rules gid={gid} embedded />}
    </section>
  );
}

function BudgetSetup({ gid }: { gid: string }) {
  const [data, setData] = useState<Data | null>(null);
  const [cats, setCats] = useState<Category[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [newHeading, setNewHeading] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.budget(gid).then(setData).catch((e) => setError(e.message));
    api.categories(gid).then(setCats).catch(() => {});
  }, [gid]);

  async function run(fn: () => Promise<Data>) {
    setError("");
    try { setData(await fn()); api.categories(gid).then(setCats).catch(() => {}); } catch (e) { setError((e as Error).message); }
  }

  if (!data) return error ? <p className="error">{error}</p> : <div className="spinner" />;

  const used = new Map<string, string>();
  data.headings.forEach((h) => h.posts.forEach((p) => p.category_ids.forEach((c) => used.set(c, p.name))));
  const spendCats = cats.filter((c) => c.kind === "expense");
  const free = spendCats.filter((c) => !used.has(c.id));
  const monthly = data.headings.flatMap((h) => h.posts).reduce((a, p) => a + Number(p.monthly_amount ?? 0), 0);

  function move(headingIdx: number, postIdx: number, dir: -1 | 1) {
    const order = data!.headings.map((h) => ({ id: h.id, post_ids: h.posts.map((p) => p.id) }));
    const list = order[headingIdx].post_ids;
    const j = postIdx + dir;
    if (j < 0 || j >= list.length) return;
    [list[postIdx], list[j]] = [list[j], list[postIdx]];
    run(() => api.reorderBudget(gid, order));
  }

  if (data.headings.length === 0) {
    return (
      <div className="card">
        <h2>Start your budget</h2>
        <p className="muted">A budget groups your spending categories into posts, like "Groceries og wine", under headings
          like "Faste udgifter". Each post can have a monthly amount.</p>
        <div className="row-actions">
          <button className="primary" onClick={() => run(() => api.starterBudget(gid))}>Use the budget from the prototype</button>
          <button onClick={() => run(() => api.addHeading(gid, "Udgifter"))}>Start empty</button>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    );
  }

  return (
    <>
      <p className="muted">Monthly total across all posts: <b>{money0(monthly)}</b>. Tap a post to set its amount and categories.</p>
      {error && <p className="error">{error}</p>}
      {data.headings.map((h, hi) => (
        <div key={h.id} className="card">
          <div className="card-head">
            <input className="heading-input" defaultValue={h.name} aria-label="Heading name"
              onBlur={(e) => e.target.value.trim() && e.target.value !== h.name && run(() => api.renameHeading(gid, h.id, e.target.value))} />
            <span className="num muted">{money0(h.posts.reduce((a, p) => a + Number(p.monthly_amount ?? 0), 0))}/mo</span>
          </div>
          <ul className="posts">
            {h.posts.map((p, pi) => (
              <PostRow key={p.id} gid={gid} post={p} cats={spendCats} used={used} open={open === p.id}
                onToggle={() => setOpen(open === p.id ? null : p.id)} run={run}
                onUp={pi > 0 ? () => move(hi, pi, -1) : undefined} onDown={pi < h.posts.length - 1 ? () => move(hi, pi, 1) : undefined} />
            ))}
          </ul>
          <div className="row-actions">
            <button onClick={() => { const name = prompt("Name of the new post"); if (name?.trim()) run(() => api.addPost(gid, h.id, name.trim())); }}>Add post</button>
            <button className="link danger" onClick={() => {
              if (confirm(`Delete "${h.name}" and its ${h.posts.length} posts? Your transactions are not affected.`)) run(() => api.deleteHeading(gid, h.id));
            }}>Delete heading</button>
          </div>
        </div>
      ))}
      <form className="inline" onSubmit={(e) => { e.preventDefault(); run(() => api.addHeading(gid, newHeading)); setNewHeading(""); }}>
        <input value={newHeading} onChange={(e) => setNewHeading(e.target.value)} placeholder="New heading, e.g. Opsparing" required />
        <button>Add heading</button>
      </form>
      {free.length > 0 && (
        <div className="card">
          <h2>Categories not in a budget</h2>
          <p className="muted small">Spending in these shows as "Not in a budget" on the overview.</p>
          <div className="chips">{free.map((c) => <span key={c.id} className="chip static">{c.name}</span>)}</div>
        </div>
      )}
    </>
  );
}

function PostRow({ gid, post, cats, used, open, onToggle, run, onUp, onDown }: {
  gid: string; post: BudgetPost; cats: Category[]; used: Map<string, string>; open: boolean; onToggle: () => void;
  run: (fn: () => Promise<Data>) => void; onUp?: () => void; onDown?: () => void;
}) {
  const [amount, setAmount] = useState(post.monthly_amount ? String(Number(post.monthly_amount)) : "");
  const [name, setName] = useState(post.name);
  useEffect(() => { setAmount(post.monthly_amount ? String(Number(post.monthly_amount)) : ""); setName(post.name); }, [post]);
  const catName = new Map(cats.map((c) => [c.id, c.name]));

  function saveAmount() {
    const v = amount.trim();
    if (v === "" && post.monthly_amount !== null) run(() => api.updatePost(gid, post.id, { clear_amount: true }));
    else if (v !== "" && Number(v) !== Number(post.monthly_amount ?? NaN) && !Number.isNaN(Number(v)) && Number(v) >= 0)
      run(() => api.updatePost(gid, post.id, { monthly_amount: v }));
  }
  function toggleCat(id: string) {
    const ids = post.category_ids.includes(id) ? post.category_ids.filter((c) => c !== id) : [...post.category_ids, id];
    run(() => api.updatePost(gid, post.id, { category_ids: ids }));
  }

  return (
    <li className={`post ${open ? "open" : ""}`}>
      <div className="post-line" onClick={onToggle}>
        <span className="post-name"><i className="dot" style={{ background: postColor(post.color) }} />{post.name}</span>
        <span className={post.monthly_amount ? "num" : "num muted"}>{post.monthly_amount ? `${money0(post.monthly_amount)}/mo` : "No amount"}</span>
      </div>
      {!open && <div className="post-cats muted small">{post.category_ids.map((c) => catName.get(c)).filter(Boolean).join(" + ") || "No categories yet"}</div>}
      {open && (
        <div className="post-edit">
          <div className="grid2">
            <label>Name<input value={name} onChange={(e) => setName(e.target.value)}
              onBlur={() => name.trim() && name !== post.name && run(() => api.updatePost(gid, post.id, { name }))} /></label>
            <label>Monthly amount (AUD)<input inputMode="decimal" value={amount} placeholder="No amount"
              onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))} onBlur={saveAmount}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} /></label>
          </div>
          <div className="eyebrow">Colour</div>
          <div className="swatches">
            {[1, 2, 3, 4, 5, 6, 7, 8].map((c) => (
              <button key={c} className={c === post.color ? "swatch on" : "swatch"} style={{ background: postColor(c) }}
                aria-label={`Colour ${c}`} onClick={() => run(() => api.updatePost(gid, post.id, { color: c }))} />
            ))}
          </div>
          <div className="eyebrow">Categories in this post</div>
          <div className="chips">
            {cats.map((c) => {
              const mine = post.category_ids.includes(c.id);
              const elsewhere = !mine && used.get(c.id);
              return (
                <button key={c.id} className={mine ? "chip on" : elsewhere ? "chip taken" : "chip"} onClick={() => toggleCat(c.id)}
                  title={elsewhere ? `Now in ${elsewhere}. Tap to move it here.` : undefined}>
                  {c.name}{elsewhere ? ` · ${elsewhere}` : ""}
                </button>
              );
            })}
          </div>
          <div className="row-actions">
            {onUp && <button onClick={onUp}>↑ Move up</button>}
            {onDown && <button onClick={onDown}>↓ Move down</button>}
            <button className="link danger" onClick={() => confirm(`Delete "${post.name}"?`) && run(() => api.deletePost(gid, post.id))}>Delete post</button>
          </div>
        </div>
      )}
    </li>
  );
}
