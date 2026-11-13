import { useEffect, useState } from "react";
import { api, type Account, type AuditEvent, type Me, type Member } from "../api";

const ACTIONS: Record<string, string> = {
  "group.created": "created the group", "group.joined": "joined", "invite.created": "created an invite",
  "invite.rejected": "tried an invalid code", "member.removed": "removed a member", "member.role_changed": "changed a role",
  "import.completed": "imported transactions", "rule.created": "added a rule", "rule.deleted": "removed a rule",
  "rule.applied": "applied rules", "rule.imported": "imported rules", "category.created": "added a category",
  "transaction.categorised": "changed a category", "account.updated": "renamed an account",
};

export default function GroupScreen({ gid, me, isOwner, onLeft, onSignedOut }: {
  gid: string; me: Me; isOwner: boolean; onLeft: () => void; onSignedOut: () => void;
}) {
  const [members, setMembers] = useState<Member[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [activity, setActivity] = useState<AuditEvent[]>([]);
  const [invite, setInvite] = useState<{ code: string; expires_at: string } | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    api.members(gid).then(setMembers).catch((e) => setError(e.message));
    api.accounts(gid).then(setAccounts).catch(() => {});
    api.activity(gid).then((a) => setActivity(a.slice(0, 30))).catch(() => {});
  };
  useEffect(load, [gid]);

  async function act(fn: () => Promise<unknown>) {
    setError("");
    try { await fn(); load(); } catch (e) { setError((e as Error).message); }
  }

  const who = new Map(members.map((m) => [m.user_id, m.display_name]));
  return (
    <section>
      <h1>Family</h1>
      <div className="card">
        <h2>Members</h2>
        <ul className="list">
          {members.map((m) => (
            <li key={m.user_id}>
              <span>{m.display_name} <span className="muted">· {m.role}</span></span>
              {isOwner && m.user_id !== me.user.id && (
                <span>
                  <button className="link" onClick={() => act(() => api.setRole(gid, m.user_id, m.role === "owner" ? "member" : "owner"))}>
                    {m.role === "owner" ? "Make member" : "Make owner"}
                  </button>
                  <button className="link danger" onClick={() => act(() => api.removeMember(gid, m.user_id))}>Remove</button>
                </span>
              )}
            </li>
          ))}
        </ul>
        {isOwner && (invite ? (
          <div className="invite">
            <p>Share this code. It works once and expires {new Date(invite.expires_at).toLocaleDateString("en-AU")}.</p>
            <div className="code">{invite.code}</div>
          </div>
        ) : <button onClick={() => act(async () => setInvite(await api.invite(gid)))}>Invite someone</button>)}
      </div>

      <div className="card">
        <h2>Accounts</h2>
        <ul className="list">
          {accounts.map((a) => (
            <li key={a.id}>
              <span>{a.name} <span className="muted">· {a.kind === "credit_card" ? "credit card" : "transaction"}</span></span>
              <button className="link" onClick={() => {
                const name = prompt("Account name", a.name);
                if (name) act(() => api.renameAccount(gid, a.id, name));
              }}>Rename</button>
            </li>
          ))}
          {accounts.length === 0 && <li className="muted">Accounts appear when you import a file.</li>}
        </ul>
      </div>

      <div className="card">
        <h2>Recent activity</h2>
        <ul className="list small">
          {activity.map((e, i) => (
            <li key={i}>
              <span>{who.get(e.user_id ?? "") ?? "Someone"} {ACTIONS[e.action] ?? e.action}</span>
              <span className="muted">{new Date(e.at).toLocaleString("en-AU", { dateStyle: "short", timeStyle: "short" })}</span>
            </li>
          ))}
        </ul>
      </div>

      {error && <p className="error">{error}</p>}
      <div className="row-actions">
        <button onClick={onSignedOut}>Sign out</button>
        <button className="danger" onClick={() => act(async () => { await api.removeMember(gid, me.user.id); onLeft(); })}>Leave group</button>
      </div>
    </section>
  );
}
