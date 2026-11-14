import { useEffect, useRef, useState } from "react";
import { api, type Transaction } from "../api";
import { mount, type EngineActions, type EngineData } from "../overview/engine";
import "../overview/proto.css";

const PAGE = 500;

async function allTransactions(gid: string): Promise<Transaction[]> {
  const out: Transaction[] = [];
  for (let offset = 0; ; offset += PAGE) {
    const p = await api.transactions(gid, { include_transfers: false, limit: PAGE, offset });
    out.push(...p.items);
    if (out.length >= p.total || p.items.length < PAGE) return out;
  }
}

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// The Overview is the approved prototype page, fed with the family's data. See overview/engine.ts.
export default function Overview({ gid, groupName, onImport }: { gid: string; groupName: string; onImport: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<EngineData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setData(null);
    Promise.all([allTransactions(gid), api.categories(gid), api.accounts(gid), api.budget(gid), api.overview(gid, "all")])
      .then(([transactions, categories, accounts, budget, ov]) => {
        if (live) setData({ groupName, today: todayIso(), transactions, categories, accounts, budget, recurring: ov.recurring });
      })
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [gid, groupName]);

  useEffect(() => {
    if (!data || !host.current || data.transactions.length === 0) return;
    const actions: EngineActions = {
      setCategory: (id, categoryId) => api.setCategory(gid, id, categoryId),
      renameAccount: (id, name) => api.renameAccount(gid, id, name),
      setPostAmount: (postId, amount) =>
        api.updatePost(gid, postId, amount === null ? { clear_amount: true } : { monthly_amount: amount }),
      linkBudget: async (name, categoryIds, amount) => {
        let b = await api.budget(gid);
        let heading = b.headings.find((h) => h.name === "Øvrige");
        if (!heading) {
          b = await api.addHeading(gid, "Øvrige");
          heading = b.headings.find((h) => h.name === "Øvrige")!;
        }
        b = await api.addPost(gid, heading.id, name);
        const post = b.headings.find((h) => h.id === heading!.id)!.posts.filter((p) => p.name === name).pop()!;
        b = await api.updatePost(gid, post.id, { category_ids: categoryIds, monthly_amount: amount });
        return { budget: b, postId: post.id };
      },
      useStarter: () => api.starterBudget(gid),
    };
    return mount(host.current, data, actions);
  }, [data, gid]);

  if (error) return <div className="eg"><main className="wrap"><p className="error" style={{ paddingTop: 24 }}>{error}</p></main></div>;
  if (!data) return <div className="eg"><main className="wrap"><div className="empty-state">Adding it all up…</div></main></div>;
  if (data.transactions.length === 0) {
    return (
      <div className="eg">
        <main className="wrap">
          <div className="card empty-state" style={{ marginTop: 24 }}>
            <h2>Nothing to show yet</h2>
            <p>Import a CSV file from your bank to see where your money goes.</p>
            <button className="btn primary" type="button" onClick={onImport}>Import a CSV file</button>
          </div>
        </main>
      </div>
    );
  }
  return <div className="eg" ref={host} />;
}
