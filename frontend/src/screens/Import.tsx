import { useState } from "react";
import { api, type ImportResult } from "../api";

export default function Import({ gid, onImported }: { gid: string; onImported: () => void }) {
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);

  async function send(file: File | undefined) {
    if (!file) return;
    setBusy(true); setError(""); setResult(null);
    try { setResult(await api.importFile(gid, file)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <section>
      <h1>Import transactions</h1>
      <p className="muted">
        In NAB Internet Banking, open an account, choose <b>Export</b>, pick <b>CSV</b> and a date range, and drop the file here.
        Overlapping files are fine: rows you already have are skipped.
      </p>
      <label className={`dropzone ${drag ? "drag" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files[0]); }}>
        <input type="file" accept=".csv,text/csv" hidden onChange={(e) => send(e.target.files?.[0])} />
        <span className="drop-icon">⇪</span>
        <span>{busy ? "Importing…" : "Choose a CSV file or drop it here"}</span>
      </label>
      {error && <p className="error">{error}</p>}
      {result && (
        <div className="card result">
          <div className="stat"><b>{result.rows_new}</b><span>new</span></div>
          <div className="stat"><b>{result.rows_duplicate}</b><span>already had</span></div>
          <div className="stat"><b>{result.transfers_paired}</b><span>transfers matched</span></div>
          {result.accounts_created.length > 0 && <p className="muted full">New accounts: {result.accounts_created.join(", ")}</p>}
          <button className="primary full" onClick={onImported}>See transactions</button>
        </div>
      )}
    </section>
  );
}
