import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Me } from "./api";
import Auth from "./screens/Auth";
import Onboard from "./screens/Onboard";
import Transactions from "./screens/Transactions";
import Import from "./screens/Import";
import Overview from "./screens/Overview";
import Budget from "./screens/Budget";
import GroupScreen from "./screens/Group";

type Tab = "overview" | "transactions" | "budget" | "import" | "group";
const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "◔" },
  { id: "transactions", label: "Activity", icon: "≡" },
  { id: "budget", label: "Budget", icon: "▤" },
  { id: "import", label: "Import", icon: "⇪" },
  { id: "group", label: "Family", icon: "◎" },
];

function remembered(key: string) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function remember(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* private mode */ }
}

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [groupId, setGroupId] = useState<string | null>(remembered("genie.group"));
  const saved = remembered("genie.tab") as Tab | null;
  const [tab, setTab] = useState<Tab>(saved && TABS.some((t) => t.id === saved) ? saved : "overview");

  const refresh = useCallback(async () => {
    try {
      setMe(await api.me());
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
      else setMe(null);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  if (me === undefined) return <div className="splash"><Logo /></div>;
  if (me === null) return <Auth onSignedIn={setMe} />;

  const group = me.groups.find((g) => g.group_id === groupId) ?? me.groups[0];
  if (!group) return <Onboard me={me} onDone={async (id) => { setGroupId(id); remember("genie.group", id); await refresh(); }} />;

  const pick = (t: Tab) => { setTab(t); remember("genie.tab", t); };
  return (
    <div className="shell">
      <header className="topbar">
        <Logo small />
        {me.groups.length > 1 ? (
          <select className="group-pick" value={group.group_id}
            onChange={(e) => { setGroupId(e.target.value); remember("genie.group", e.target.value); }}>
            {me.groups.map((g) => <option key={g.group_id} value={g.group_id}>{g.group_name}</option>)}
          </select>
        ) : <span className="group-name">{group.group_name}</span>}
      </header>
      <main className="content">
        {tab === "overview" && <Overview gid={group.group_id} onSetBudget={() => pick("budget")} />}
        {tab === "transactions" && <Transactions gid={group.group_id} />}
        {tab === "budget" && <Budget gid={group.group_id} />}
        {tab === "import" && <Import gid={group.group_id} onImported={() => pick("overview")} />}
        {tab === "group" && (
          <GroupScreen gid={group.group_id} me={me} isOwner={group.role === "owner"}
            onLeft={async () => { setGroupId(null); await refresh(); }}
            onSignedOut={async () => { await api.logout(); setMe(null); }} />
        )}
      </main>
      <nav className="tabbar">
        {TABS.map((t) => (
          <button key={t.id} className={tab === t.id ? "active" : ""} onClick={() => pick(t.id)}>
            <span className="tab-icon" aria-hidden>{t.icon}</span>
            <span>{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

export function Logo({ small }: { small?: boolean }) {
  return (
    <div className={small ? "logo small" : "logo"}>
      <span className="logo-mark">✦</span>
      <span>Economic Genie</span>
    </div>
  );
}
