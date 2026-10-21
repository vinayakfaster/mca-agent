import { useCallback, useEffect, useRef, useState } from "react";

const API = ((import.meta.env.VITE_API_BASE_URL as string | undefined) || "http://localhost:8000").replace(/\/$/, "");
type Msg = { role: "user" | "assistant"; content: string };
type Health = { ollama: boolean; model_installed: boolean; model: string };
type Mod = { id: string; name: string; available: boolean; note: string };
const NAV = [["dashboard","Dashboard"],["chat","AI Chat"],["study","Study Companion"],["data","Data Analysis"],
  ["code","Code Documentation"],["pay","x402 Payments"],["history","History"],["about","About Project"]] as const;
type Tab = (typeof NAV)[number][0];

const USER = (() => {
  let v = localStorage.getItem("uid");
  if (!v) { v = "u_" + crypto.randomUUID().replace(/-/g, "").slice(0, 16); localStorage.setItem("uid", v); }
  return v;
})();

async function api<T>(path: string, key: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(API + path, { ...init, headers: { "Content-Type": "application/json", "X-API-Key": key, "ngrok-skip-browser-warning": "1" } });
  if (!r.ok) {
    let d = `Request failed (${r.status})`;
    try { const j = await r.json(); if (j.detail) d = j.detail; } catch { /* ignore */ }
    throw new Error(d);
  }
  return r.json();
}

const Dot = ({ ok }: { ok: boolean }) => <span className={`inline-block h-2.5 w-2.5 rounded-full ${ok ? "bg-teal-400" : "bg-red-400"}`} />;

export default function App() {
  const [key, setKey] = useState(localStorage.getItem("apikey") || "");
  const [keyInput, setKeyInput] = useState("");
  const [tab, setTab] = useState<Tab>("dashboard");
  const [health, setHealth] = useState<Health | null>(null);
  const [mods, setMods] = useState<Mod[]>([]);
  const [convs, setConvs] = useState<string[]>([]);
  const [convId, setConvId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try { setHealth(await (await fetch(API + "/api/health", { headers: { "ngrok-skip-browser-warning": "1" } })).json()); }
    catch { setHealth(null); }
    if (!key) return;
    try {
      setMods(await api<Mod[]>("/api/modules", key));
      setConvs((await api<{ conversations: string[] }>(`/api/conversations?user_id=${USER}`, key)).conversations);
    } catch (e) {
      if ((e as Error).message.includes("access key")) { localStorage.removeItem("apikey"); setKey(""); }
    }
  }, [key]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, loading]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput(""); setError(""); setLoading(true);
    setMsgs(m => [...m, { role: "user", content: text }]);
    try {
      const r = await api<{ reply: string; conversation_id: string }>("/api/chat", key,
        { method: "POST", body: JSON.stringify({ user_id: USER, conversation_id: convId, message: text }) });
      setConvId(r.conversation_id);
      setMsgs(m => [...m, { role: "assistant", content: r.reply }]);
      refresh();
    } catch (e) { setError(e instanceof TypeError ? "Cannot reach the backend. Is it running and is the tunnel URL current?" : (e as Error).message); }
    finally { setLoading(false); }
  };

  const open = async (id: string) => {
    setError("");
    try {
      const r = await api<{ messages: Msg[] }>(`/api/conversations/${id}?user_id=${USER}`, key);
      setMsgs(r.messages); setConvId(id); setTab("chat");
    } catch (e) { setError((e as Error).message); }
  };
  const fresh = () => { setConvId(null); setMsgs([]); setError(""); };

  if (!key) return (
    <main className="min-h-screen grid place-items-center bg-slate-950 p-6 text-slate-100">
      <form className="w-full max-w-sm space-y-4" onSubmit={e => { e.preventDefault(); if (keyInput.trim()) { localStorage.setItem("apikey", keyInput.trim()); setKey(keyInput.trim()); } }}>
        <h1 className="text-2xl font-semibold">Enter access key</h1>
        <p className="text-sm text-slate-400">This demo is private. Use the key set in the backend .env file.</p>
        <input type="password" autoFocus value={keyInput} onChange={e => setKeyInput(e.target.value)} aria-label="Access key"
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 focus:outline-2 focus:outline-teal-400" />
        <button className="w-full rounded-lg bg-teal-500 py-2 font-medium text-slate-950 hover:bg-teal-400 focus:outline-2 focus:outline-offset-2 focus:outline-teal-300">Continue</button>
      </form>
    </main>);

  const unavailable = (id: string) => mods.find(m => m.id === id);

  return (
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      <aside className={`${menu ? "block" : "hidden"} fixed inset-y-0 left-0 z-20 w-64 bg-slate-950 p-4 text-slate-300 md:static md:block`}>
        <h2 className="mb-6 text-lg font-semibold text-white">MCA010 Agent</h2>
        <nav className="space-y-1">
          {NAV.map(([id, label]) => (
            <button key={id} onClick={() => { setTab(id); setMenu(false); }}
              className={`block w-full rounded-lg px-3 py-2 text-left focus:outline-2 focus:outline-teal-400 ${tab === id ? "bg-teal-500/20 text-teal-300" : "hover:bg-slate-800"}`}>{label}</button>))}
        </nav>
        <button onClick={() => { localStorage.removeItem("apikey"); setKey(""); }} className="mt-8 text-sm text-slate-500 hover:text-slate-300">Change access key</button>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-3">
          <button className="md:hidden rounded border px-2 py-1" aria-label="Menu" onClick={() => setMenu(v => !v)}>☰</button>
          <h1 className="font-semibold">{NAV.find(n => n[0] === tab)?.[1]}</h1>
          <span className="ml-auto flex items-center gap-2 text-sm text-slate-600"><Dot ok={!!health?.ollama} />{health?.ollama ? "Ollama online" : "Ollama offline"}</span>
        </header>

        <section className="flex-1 p-4 md:p-6">
          {tab === "dashboard" && (
            <div className="max-w-3xl space-y-6">
              <div><h2 className="text-2xl font-semibold">Local LLM-Based AI Agent</h2>
                <p className="mt-1 text-slate-600">Study assistance, data analysis, code documentation and x402 micropayments.</p></div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-xl border bg-white p-4"><Dot ok={!!health} /> Backend<div className="text-sm text-slate-500">{health ? "Reachable" : "Unreachable"}</div></div>
                <div className="rounded-xl border bg-white p-4"><Dot ok={!!health?.ollama} /> Ollama<div className="text-sm text-slate-500">{health?.ollama ? "Reachable" : "Not reachable"}</div></div>
                <div className="rounded-xl border bg-white p-4"><Dot ok={!!health?.model_installed} /> Model<div className="text-sm text-slate-500">{health?.model ?? "qwen3:8b"} {health?.model_installed ? "installed" : "not found"}</div></div>
              </div>
              <ul className="divide-y rounded-xl border bg-white">
                {mods.map(m => (<li key={m.id} className="flex items-start gap-3 p-3"><Dot ok={m.available} />
                  <div><div className="font-medium">{m.name}</div><div className="text-sm text-slate-500">{m.note}</div></div></li>))}
              </ul>
              <button onClick={() => setTab("chat")} className="rounded-lg bg-teal-600 px-4 py-2 font-medium text-white hover:bg-teal-700 focus:outline-2 focus:outline-offset-2 focus:outline-teal-500">Open chat</button>
            </div>)}

          {tab === "chat" && (
            <div className="mx-auto flex h-[calc(100vh-7.5rem)] max-w-3xl flex-col">
              <div className="mb-2 flex justify-end"><button onClick={fresh} className="rounded-lg border px-3 py-1 text-sm hover:bg-slate-100">Clear chat</button></div>
              <div className="flex-1 space-y-3 overflow-y-auto rounded-xl border bg-white p-4" aria-live="polite">
                {msgs.length === 0 && <p className="text-slate-500">Ask about the weather in a city, a calculation, or something from an earlier chat.</p>}
                {msgs.map((m, i) => (
                  <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                    <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-2 ${m.role === "user" ? "bg-teal-600 text-white" : "bg-slate-100"}`}>{m.content}</div></div>))}
                {loading && <p className="text-sm text-slate-500">Agent is thinking… local models can take a while.</p>}
                <div ref={end} />
              </div>
              {error && <p role="alert" className="mt-2 rounded-lg bg-red-50 p-2 text-sm text-red-700">{error}</p>}
              <form className="mt-3 flex gap-2" onSubmit={e => { e.preventDefault(); send(); }}>
                <input value={input} onChange={e => setInput(e.target.value)} placeholder="Type a message" aria-label="Message" maxLength={4000}
                  className="flex-1 rounded-lg border bg-white px-3 py-2 focus:outline-2 focus:outline-teal-500" />
                <button disabled={loading || !input.trim()} className="rounded-lg bg-teal-600 px-4 py-2 font-medium text-white hover:bg-teal-700 disabled:opacity-50">Send</button>
              </form>
            </div>)}

          {(["study", "data", "code", "pay"] as Tab[]).includes(tab) && (
            <div className="max-w-xl rounded-xl border border-amber-300 bg-amber-50 p-5">
              <h2 className="font-semibold">Not available yet</h2>
              <p className="mt-1 text-sm text-slate-700">{unavailable(tab)?.note ?? "This module is not connected to the agent."} Nothing is simulated on this page.</p>
              {tab === "pay" && <p className="mt-2 text-sm text-slate-700">No wallet is connected and no USDC can be spent from this website.</p>}
            </div>)}

          {tab === "history" && (
            <div className="max-w-xl">
              {error && <p role="alert" className="mb-2 text-sm text-red-700">{error}</p>}
              {convs.length === 0 ? <p className="text-slate-500">No saved conversations yet. Start one in AI Chat.</p> :
                <ul className="divide-y rounded-xl border bg-white">{convs.map(c => (
                  <li key={c}><button onClick={() => open(c)} className="w-full px-4 py-3 text-left hover:bg-slate-50 focus:outline-2 focus:outline-teal-500">{c}</button></li>))}</ul>}
            </div>)}

          {tab === "about" && (
            <div className="max-w-2xl space-y-4">
              <h2 className="text-2xl font-semibold">About this project</h2>
              <p>Local LLM-Based AI Agent for Study Assistance, Data Analysis, Code Documentation and x402 Micropayments. MCA010, JSS University, Noida, Session 2025–26.</p>
              <pre className="overflow-x-auto rounded-xl bg-slate-950 p-4 text-sm text-teal-300">{`Browser (React, Vercel)
   ↓ HTTPS + access key
Tunnel (Cloudflare / ngrok)
   ↓
FastAPI backend  →  run_agent() + tools + conversation_store
   ↓ localhost only
Ollama (qwen3:8b)`}</pre>
              <p className="text-sm text-slate-600">Stack: React, Vite, TypeScript, Tailwind CSS, FastAPI, Python, Ollama, Open-Meteo.</p>
            </div>)}
        </section>
      </main>
    </div>);
}
