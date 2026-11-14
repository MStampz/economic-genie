import { useEffect, useRef, useState } from "react";
import { api, money, type AccountChoice, type CsvMapping, type ImportBatch, type ImportPreview, type ImportResult } from "../api";

type Stage = "pick" | "checking" | "confirm" | "map" | "importing" | "done";

const EMPTY: CsvMapping = {
  has_header: true, date: "", date_format: "auto", amount: null, debit: null, credit: null, flip_sign: false,
  description: [], merchant: null, category: null, balance: null, account_column: null, account_name: "",
  account_kind: "transaction", institution: "",
};

export default function Import({ gid, onImported }: { gid: string; onImported: () => void }) {
  const [stage, setStage] = useState<Stage>("pick");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mapping, setMapping] = useState<CsvMapping>(EMPTY);
  const [saveAs, setSaveAs] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const [history, setHistory] = useState<ImportBatch[]>([]);
  const [notice, setNotice] = useState("");

  const loadHistory = () => { api.imports(gid).then(setHistory).catch(() => {}); };
  useEffect(loadHistory, [gid]);

  async function undo(batchId: string, label: string) {
    if (!confirm(`Remove every transaction that ${label} added? This can't be undone, but you can import the file again.`)) return;
    setError("");
    try {
      const r = await api.undoImport(gid, batchId);
      setNotice(`Removed ${r.removed} transaction${r.removed === 1 ? "" : "s"}` +
        (r.accounts_removed.length ? ` and the now empty account${r.accounts_removed.length > 1 ? "s" : ""} ${r.accounts_removed.join(", ")}.` : "."));
      reset(); loadHistory(); onImported();
    } catch (e) { setError((e as Error).message); }
  }

  async function choose(f: File | undefined) {
    if (!f) return;
    setFile(f); setError(""); setNotice(""); setResult(null); setStage("checking");
    try {
      const p = await api.previewFile(gid, f);
      setPreview(p);
      if ((p.status === "recognised" || p.status === "saved") && !p.error) {
        await doImport(f);
      } else if (p.status === "confirm_account" && p.account_choice && !p.error) {
        setStage("confirm");
      } else {
        setMapping({ ...EMPTY, ...p.suggested, institution: "", account_name: "" } as CsvMapping);
        setSaveAs("");
        setStage("map");
      }
    } catch (e) {
      setError((e as Error).message); setStage("pick");
    }
  }

  async function doImport(f: File, m?: CsvMapping, layoutName?: string) {
    const back: Stage = layoutName ? "confirm" : m ? "map" : "pick";
    setStage("importing"); setError("");
    try {
      setResult(await api.importFile(gid, f, m, m ? layoutName || saveAs || `${m.institution} CSV` : undefined));
      setStage("done");
      loadHistory();
    } catch (e) {
      setError((e as Error).message);
      setStage(back);
    }
  }

  function remap() {
    if (!preview) return;
    setMapping({ ...EMPTY, ...preview.suggested, institution: "", account_name: "" } as CsvMapping);
    setSaveAs("");
    setStage("map");
  }

  function reset() { setStage("pick"); setFile(null); setPreview(null); setResult(null); setError(""); }

  return (
    <section>
      <h1>Import transactions</h1>
      {stage === "pick" || stage === "checking" ? (
        <>
          <p className="muted">
            Export a CSV file from your bank's internet banking and drop it here. Files from NAB are recognised
            straight away. For another bank you match its columns once, and the app remembers them.
            Overlapping files are fine: transactions you already have are skipped.
          </p>
          <label className={`dropzone ${drag ? "drag" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); choose(e.dataTransfer.files[0]); }}>
            <input type="file" accept=".csv,.txt,text/csv" hidden onChange={(e) => { choose(e.target.files?.[0]); e.target.value = ""; }} />
            <span className="drop-icon">⇪</span>
            <span>{stage === "checking" ? "Reading the file…" : "Choose a CSV file or drop it here"}</span>
          </label>
          {notice && <p className="hint">{notice}</p>}
          {history.some((b) => b.remaining > 0) && (
            <div className="card">
              <h2>Recent imports</h2>
              <ul className="list small">
                {history.filter((b) => b.remaining > 0).slice(0, 10).map((b) => (
                  <li key={b.id}>
                    <span>{b.filename ?? "File"} <span className="muted">· {new Date(b.created_at).toLocaleDateString("en-AU")} · {b.remaining} transaction{b.remaining === 1 ? "" : "s"} in {b.accounts.join(", ")}</span></span>
                    <button className="link danger" onClick={() => undo(b.id, b.filename ?? "this import")}>Undo</button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : null}

      {stage === "importing" && <div className="card center"><div className="spinner" /> Importing {file?.name}…</div>}

      {stage === "confirm" && preview?.account_choice && file && (
        <ConfirmAccount preview={preview} choice={preview.account_choice} file={file} onRemap={remap} onCancel={reset}
          onImport={(m) => doImport(file, m, preview.account_choice!.layout)} />
      )}

      {stage === "map" && preview && file && (
        <Mapper preview={preview} file={file} gid={gid} mapping={mapping} setMapping={setMapping}
          saveAs={saveAs} setSaveAs={setSaveAs} onCancel={reset} onImport={() => doImport(file, mapping)} />
      )}

      {error && <p className="error">{error}</p>}

      {stage === "done" && result && <Done result={result} onView={onImported} onAnother={reset}
        onUndo={() => undo(result.batch_id, result.filename ?? "this import")} />}
    </section>
  );
}

// A saved layout whose files don't say which account they are from: always ask, so a second account's
// file never lands in the first account.
function ConfirmAccount({ preview, choice, file, onRemap, onCancel, onImport }: {
  preview: ImportPreview; choice: AccountChoice; file: File; onRemap: () => void; onCancel: () => void;
  onImport: (m: CsvMapping) => void;
}) {
  const known = choice.accounts.some((a) => a.ref === choice.suggested_ref);
  const [ref, setRef] = useState(known ? choice.suggested_ref : "");
  const [newName, setNewName] = useState("");
  const [kind, setKind] = useState<CsvMapping["account_kind"]>(choice.mapping.account_kind);
  const existing = choice.accounts.find((a) => a.ref === ref);
  const name = existing ? existing.ref : newName.trim();
  return (
    <div className="card">
      <h2>Which account is this file from?</h2>
      <p className="muted"><b>{file.name}</b> uses your saved layout “{choice.layout}”. The file doesn't say which account it
        belongs to, so choose one.</p>
      <ul className="list small">
        {preview.parsed.slice(0, 4).map((r, i) => (
          <li key={i}>
            <span>{r.date} · {r.description}</span>
            <span className={Number(r.amount) < 0 ? "amount out" : "amount in"}>{money(r.amount)}</span>
          </li>
        ))}
      </ul>
      <div className="form">
        <label>Account
          <select value={ref} onChange={(e) => setRef(e.target.value)}>
            {choice.accounts.map((a) => <option key={a.ref} value={a.ref}>{a.name}</option>)}
            <option value="">A new account…</option>
          </select>
        </label>
        {!existing && (
          <div className="grid2">
            <label>New account name<input value={newName} placeholder="e.g. Visa card" onChange={(e) => setNewName(e.target.value)} /></label>
            <label>Account type
              <select value={kind} onChange={(e) => setKind(e.target.value as CsvMapping["account_kind"])}>
                <option value="transaction">Transaction account</option>
                <option value="credit_card">Credit card</option>
              </select>
            </label>
          </div>
        )}
      </div>
      <div className="row-actions">
        <button className="primary" disabled={!name}
          onClick={() => onImport({ ...choice.mapping, account_name: name, account_kind: existing ? (existing.kind as CsvMapping["account_kind"]) : kind })}>
          Import into {existing ? existing.name : name || "the new account"}
        </button>
        <button onClick={onRemap}>Match the columns again</button>
        <button onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function Done({ result, onView, onAnother, onUndo }: {
  result: ImportResult; onView: () => void; onAnother: () => void; onUndo: () => void;
}) {
  // Pending card transactions are swapped for their latest version on every import, so they aren't "new".
  const added = Math.max(0, result.rows_new - result.rows_pending_replaced);
  const nothingNew = added === 0;
  return (
    <div className="card done">
      <div className="done-head">
        <span className="done-mark" aria-hidden>✓</span>
        <div>
          <h2>{nothingNew ? "Already up to date" : "Import complete"}</h2>
          <p className="muted">{result.filename} · read as {result.format}</p>
        </div>
      </div>
      <p className="done-line">
        {nothingNew
          ? "Every transaction in this file was already imported. Nothing was added twice."
          : <><b>{added}</b> new transaction{added === 1 ? "" : "s"} saved to <b>{result.accounts.join(", ")}</b>.</>}
      </p>
      <ul className="done-list">
        {result.rows_duplicate > 0 && <li>{result.rows_duplicate} already imported earlier, skipped</li>}
        {result.rows_pending_replaced > 0 && <li>{result.rows_pending_replaced} pending transactions updated</li>}
        {result.transfers_paired > 0 && <li>{result.transfers_paired} transfers between your own accounts matched, not counted as spending</li>}
        {result.accounts_created.length > 0 && <li>New account{result.accounts_created.length > 1 ? "s" : ""}: {result.accounts_created.join(", ")}</li>}
      </ul>
      <div className="row-actions">
        <button className="primary" onClick={onView}>See the overview</button>
        <button onClick={onAnother}>Import another file</button>
        {result.rows_new > 0 && <button className="danger" onClick={onUndo}>Undo this import</button>}
      </div>
    </div>
  );
}

function Mapper({ preview, file, gid, mapping, setMapping, saveAs, setSaveAs, onCancel, onImport }: {
  preview: ImportPreview; file: File; gid: string; mapping: CsvMapping; setMapping: (m: CsvMapping) => void;
  saveAs: string; setSaveAs: (s: string) => void; onCancel: () => void; onImport: () => void;
}) {
  const [check, setCheck] = useState<ImportPreview | null>(null);
  const [checkError, setCheckError] = useState("");
  const [twoColumns, setTwoColumns] = useState(!mapping.amount && !!(mapping.debit || mapping.credit));
  const [accountFromFile, setAccountFromFile] = useState(!!mapping.account_column);
  const seq = useRef(0);
  const [table, setTable] = useState({ columns: preview.columns, sample: preview.sample });
  const cols = table.columns;
  const sample = table.sample;

  const set = (patch: Partial<CsvMapping>) => setMapping({ ...mapping, ...patch });

  // Column names change when the first row stops (or starts) being a header, so start the matching again.
  async function toggleHeader(hasHeader: boolean) {
    try {
      const p = await api.previewFile(gid, file, undefined, hasHeader);
      setTable({ columns: p.columns, sample: p.sample });
      setMapping({ ...mapping, ...p.suggested, has_header: hasHeader } as CsvMapping);
    } catch (e) { setCheckError((e as Error).message); }
  }

  // Re-read the file with the current mapping as the user changes it, so they see the result live.
  useEffect(() => {
    const ready = mapping.date && mapping.description.length > 0 && (mapping.amount || mapping.debit || mapping.credit)
      && (mapping.account_column || mapping.account_name) && mapping.institution;
    if (!ready) { setCheck(null); setCheckError(""); return; }
    const n = ++seq.current;
    const t = setTimeout(() => {
      api.previewFile(gid, file, mapping)
        .then((p) => { if (n === seq.current) { setCheck(p); setTable({ columns: p.columns, sample: p.sample }); setCheckError(""); } })
        .catch((e) => { if (n === seq.current) { setCheck(null); setCheckError(e.message); } });
    }, 300);
    return () => clearTimeout(t);
  }, [gid, file, mapping]);

  const ok = check && !check.error && check.parsed.length > 0;
  const pick = (value: string | null, onChange: (v: string | null) => void, optional = true) => (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">{optional ? "Not in this file" : "Choose a column"}</option>
      {cols.map((c) => <option key={c} value={c}>{c}</option>)}
    </select>
  );

  return (
    <div className="mapper">
      <div className="card">
        <h2>New file layout</h2>
        <p className="muted">The app hasn't seen <b>{file.name}</b>'s layout before. Tell it which column is which.
          It remembers this, so the next file from the same bank imports straight away.</p>
        <div className="table-scroll">
          <table className="sample">
            <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
            <tbody>{sample.slice(0, 4).map((r, i) => <tr key={i}>{cols.map((_, j) => <td key={j}>{r[j] ?? ""}</td>)}</tr>)}</tbody>
          </table>
        </div>
        <label className="check"><input type="checkbox" checked={mapping.has_header}
          onChange={(e) => toggleHeader(e.target.checked)} />
          The first row holds column names</label>
      </div>

      <div className="card form">
        <label>Bank<input value={mapping.institution} placeholder="e.g. CBA, Westpac, ING" onChange={(e) => set({ institution: e.target.value })} /></label>
        <div className="grid2">
          <label>Date{pick(mapping.date || null, (v) => set({ date: v ?? "" }), false)}</label>
          <label>Date order
            <select value={mapping.date_format} onChange={(e) => set({ date_format: e.target.value as CsvMapping["date_format"] })}>
              <option value="auto">Work it out</option>
              <option value="DD/MM/YYYY">Day first (31/12/2026)</option>
              <option value="MM/DD/YYYY">Month first (12/31/2026)</option>
              <option value="YYYY-MM-DD">Year first (2026-12-31)</option>
            </select>
          </label>
        </div>
        <div className="segmented">
          <button type="button" className={!twoColumns ? "on" : ""} onClick={() => { setTwoColumns(false); set({ debit: null, credit: null }); }}>One amount column</button>
          <button type="button" className={twoColumns ? "on" : ""} onClick={() => { setTwoColumns(true); set({ amount: null }); }}>Money out and money in</button>
        </div>
        {twoColumns ? (
          <div className="grid2">
            <label>Money out{pick(mapping.debit, (v) => set({ debit: v }))}</label>
            <label>Money in{pick(mapping.credit, (v) => set({ credit: v }))}</label>
          </div>
        ) : (
          <label>Amount{pick(mapping.amount, (v) => set({ amount: v }), false)}</label>
        )}
        <label className="check"><input type="checkbox" checked={mapping.flip_sign} onChange={(e) => set({ flip_sign: e.target.checked })} />
          Purchases show as positive numbers (common in credit card files)</label>
        <div className="grid2">
          <label>Description{pick(mapping.description[0] ?? null, (v) => set({ description: v ? [v, ...mapping.description.slice(1)] : [] }), false)}</label>
          <label>More description{pick(mapping.description[1] ?? null, (v) => set({ description: v ? [mapping.description[0], v] : mapping.description.slice(0, 1) }))}</label>
          <label>Merchant{pick(mapping.merchant, (v) => set({ merchant: v }))}</label>
          <label>Bank's category{pick(mapping.category, (v) => set({ category: v }))}</label>
          <label>Balance{pick(mapping.balance, (v) => set({ balance: v }))}</label>
        </div>
        <div className="segmented">
          <button type="button" className={!accountFromFile ? "on" : ""} onClick={() => { setAccountFromFile(false); set({ account_column: null }); }}>All one account</button>
          <button type="button" className={accountFromFile ? "on" : ""} onClick={() => { setAccountFromFile(true); set({ account_name: null }); }}>Account is a column</button>
        </div>
        <div className="grid2">
          {accountFromFile
            ? <label>Account column{pick(mapping.account_column, (v) => set({ account_column: v }), false)}</label>
            : <label>Account name<input value={mapping.account_name ?? ""} placeholder="e.g. Everyday account" onChange={(e) => set({ account_name: e.target.value })} /></label>}
          <label>Account type
            <select value={mapping.account_kind} onChange={(e) => set({ account_kind: e.target.value as CsvMapping["account_kind"] })}>
              <option value="transaction">Transaction account</option>
              <option value="credit_card">Credit card</option>
            </select>
          </label>
        </div>
      </div>

      <div className="card">
        <h2>How it will be read</h2>
        {!check && !checkError && <p className="muted">Fill in the bank, date, amount, description and account to see a preview.</p>}
        {(checkError || check?.error) && <p className="error">{checkError || check?.error}</p>}
        {ok && (
          <ul className="list small">
            {check!.parsed.slice(0, 5).map((r, i) => (
              <li key={i}>
                <span>{r.date} · {r.description} <span className="muted">· {r.account}</span></span>
                <span className={Number(r.amount) < 0 ? "amount out" : "amount in"}>{money(r.amount)}</span>
              </li>
            ))}
          </ul>
        )}
        {ok && <p className="hint">Money out should be negative and money in positive. If it is the other way round, tick “Purchases show as positive numbers”.</p>}
        <label className="stack">Save this layout as
          <input value={saveAs} placeholder={`${mapping.institution || "Bank"} CSV`} onChange={(e) => setSaveAs(e.target.value)} />
        </label>
        <div className="row-actions">
          <button className="primary" disabled={!ok} onClick={onImport}>Import and remember layout</button>
          <button onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
