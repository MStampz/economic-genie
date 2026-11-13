import { useState } from "react";
import { api, type Me } from "../api";
import { Logo } from "../App";

export default function Onboard({ me, onDone }: { me: Me; onDone: (groupId: string) => void }) {
  const [name, setName] = useState(`${me.user.display_name}'s family`);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");

  async function run(fn: () => Promise<{ id: string }>) {
    setError("");
    try { onDone((await fn()).id); } catch (e) { setError((e as Error).message); }
  }

  return (
    <div className="centered">
      <Logo />
      <p className="tagline">Hi {me.user.display_name}. Money is shared in a group, usually your household.</p>
      <form className="card form" onSubmit={(e) => { e.preventDefault(); run(() => api.createGroup(name)); }}>
        <h2>Start a new group</h2>
        <label>Group name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <button className="primary">Create group</button>
      </form>
      <div className="or">or</div>
      <form className="card form" onSubmit={(e) => { e.preventDefault(); run(() => api.join(code)); }}>
        <h2>Join with an invite code</h2>
        <label>Invite code<input value={code} onChange={(e) => setCode(e.target.value)} placeholder="ABCDE-FGHJK" required /></label>
        <button>Join group</button>
      </form>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
