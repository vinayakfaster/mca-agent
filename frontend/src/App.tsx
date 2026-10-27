import { useCallback, useEffect, useRef, useState, type MouseEvent as RMouseEvent, type ReactNode } from "react";
import {
  AnimatePresence, MotionConfig, motion, useReducedMotion, useScroll, useSpring, useTransform,
  type MotionValue, type Variants,
} from "framer-motion";

/* ───────────────────────── config, types, constants (unchanged behaviour) ───────────────────────── */

const API = ((import.meta.env.VITE_API_BASE_URL as string | undefined) || "http://localhost:8000").replace(/\/$/, "");
type Msg = { role: "user" | "assistant"; content: string };
type Health = { ollama: boolean; model_installed: boolean; model: string };
type Mod = { id: string; name: string; available: boolean; note: string };
const NAV = [["dashboard","Dashboard"],["chat","AI Chat"],["study","Study Companion"],["data","Data Analysis"],
  ["code","Code Documentation"],["pay","x402 Payments"],["history","History"],["about","About Project"]] as const;
type Tab = (typeof NAV)[number][0];

/* BUG FIX: localStorage can throw (private mode, blocked cookies) and crypto.randomUUID is missing on
   plain-http origins. The original crashed the whole app at import time in both cases. */
const store = {
  get(k: string): string | null { try { return localStorage.getItem(k); } catch { return null; } },
  set(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
  del(k: string) { try { localStorage.removeItem(k); } catch { /* ignore */ } },
};
const randomId = () => {
  try { return crypto.randomUUID().replace(/-/g, ""); }
  catch { return (Math.random().toString(36).slice(2) + Date.now().toString(36) + Math.random().toString(36).slice(2)).padEnd(16, "0"); }
};
const USER = (() => {
  let v = store.get("uid");
  if (!v) { v = "u_" + randomId().slice(0, 16); store.set("uid", v); }
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

/* ───────────────────────── motion helpers ───────────────────────── */

const EASE = [0.22, 1, 0.36, 1] as const;
const rise: Variants = { hidden: { opacity: 0, y: 26 }, show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } } };
const stagger: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.08 } } };

function Stagger({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={stagger} initial="hidden" whileInView="show" viewport={{ once: true, margin: "-60px" }}>
      {children}
    </motion.div>);
}

/* Card with cursor-following glow and a small 3D tilt */
function Spot({ children, className = "" }: { children: ReactNode; className?: string }) {
  const reduced = useReducedMotion();
  const rx = useSpring(0, { stiffness: 220, damping: 22 });
  const ry = useSpring(0, { stiffness: 220, damping: 22 });
  const onMove = (e: RMouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    e.currentTarget.style.setProperty("--mx", x + "px");
    e.currentTarget.style.setProperty("--my", y + "px");
    if (!reduced) { ry.set((x / r.width - 0.5) * 7); rx.set(-(y / r.height - 0.5) * 7); }
  };
  const reset = () => { rx.set(0); ry.set(0); };
  return (
    <motion.div onMouseMove={onMove} onMouseLeave={reset} style={{ rotateX: rx, rotateY: ry, transformPerspective: 900 }}
      className={`spot rounded-2xl border border-line bg-surface/80 ${className}`}>
      {children}
    </motion.div>);
}

/* ───────────────────────── icons ───────────────────────── */

const ICONS: Record<string, ReactNode> = {
  dashboard: <><rect x="3" y="3" width="7.5" height="7.5" rx="2" /><rect x="13.5" y="3" width="7.5" height="7.5" rx="2" /><rect x="3" y="13.5" width="7.5" height="7.5" rx="2" /><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2" /></>,
  chat: <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.2-4.4A8 8 0 1 1 21 12Z" />,
  study: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5v-15Z" /><path d="M8 7.5h8M8 11h5" /></>,
  data: <path d="M4 20V11M10 20V4M16 20v-7M22 20H2" />,
  code: <path d="m8 8-5 4 5 4M16 8l5 4-5 4M14 5l-4 14" />,
  pay: <><circle cx="12" cy="12" r="9" /><path d="M14.5 9.5h-3.2a1.8 1.8 0 0 0 0 3.6h1.4a1.8 1.8 0 0 1 0 3.6H9.5M12 7v10" /></>,
  history: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  about: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5Z" />,
  copy: <><rect x="8" y="8" width="12" height="12" rx="2.5" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></>,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  send: <path d="M5 12h14M13 6l6 6-6 6" />,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  eye: <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" /></>,
  eyeoff: <><path d="M3 3l18 18M10.6 5.1A9.7 9.7 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4M6.5 6.6A17 17 0 0 0 2 12s3.6 7 10 7a9.6 9.6 0 0 0 4.2-1M9.9 9.9a3 3 0 0 0 4.2 4.2" /></>,
  chevron: <path d="m9 6 6 6-6 6" />,
  lock: <><rect x="4" y="10.5" width="16" height="10" rx="2.5" /><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5" /></>,
  cpu: <><rect x="6" y="6" width="12" height="12" rx="2.5" /><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" /></>,
  tool: <path d="M14.5 6.5a4 4 0 0 0 4.9 4.9L21 13l-8 8-3-3 8-8-1.5-1.5ZM3 21l5-5" />,
};
function Icon({ name, className = "h-5 w-5" }: { name: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      {ICONS[name]}
    </svg>);
}

/* ───────────────────────── small shared pieces ───────────────────────── */

/* Status dot. The original had no accessible name; this one does. */
const Dot = ({ ok, label }: { ok: boolean; label?: string }) => (
  <span className="relative inline-flex h-2.5 w-2.5 shrink-0" role="img" aria-label={label ?? (ok ? "online" : "offline")}>
    {ok && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand opacity-60 motion-reduce:animate-none" />}
    <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${ok ? "bg-brand" : "bg-danger"}`} />
  </span>);

function useTheme() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const toggle = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
    store.set("theme", next ? "dark" : "light");
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next ? "#07080d" : "#f3f5fa");
  };
  return { dark, toggle };
}

function useCopy(): [boolean, (t: string) => void] {
  const [done, setDone] = useState(false);
  const copy = (t: string) => {
    const ok = () => { setDone(true); setTimeout(() => setDone(false), 1600); };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(t).then(ok, () => { /* ignore */ });
    else {
      const a = document.createElement("textarea"); a.value = t; a.style.position = "fixed"; a.style.opacity = "0";
      document.body.appendChild(a); a.select();
      try { document.execCommand("copy"); ok(); } catch { /* ignore */ }
      a.remove();
    }
  };
  return [done, copy];
}

function ThemeToggle({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  return (
    <button onClick={onToggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      className="grid h-9 w-9 place-items-center overflow-hidden rounded-lg border border-line text-muted transition hover:border-brand hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={dark ? "moon" : "sun"} initial={{ rotate: -80, opacity: 0, scale: 0.6 }} animate={{ rotate: 0, opacity: 1, scale: 1 }}
          exit={{ rotate: 80, opacity: 0, scale: 0.6 }} transition={{ duration: 0.22 }}>
          <Icon name={dark ? "moon" : "sun"} className="h-[18px] w-[18px]" />
        </motion.span>
      </AnimatePresence>
    </button>);
}

function ScrollBar() {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, { stiffness: 120, damping: 28, restDelta: 0.001 });
  return <motion.div aria-hidden style={{ scaleX }} className="fixed inset-x-0 top-0 z-50 h-0.5 origin-left bg-linear-to-r from-brand to-brand2" />;
}

/* Fixed background glow that drifts at different speeds as you scroll */
function Aurora() {
  const { scrollY } = useScroll();
  const y1 = useTransform(scrollY, [0, 1600], [0, -280]);
  const y2 = useTransform(scrollY, [0, 1600], [0, 220]);
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      <motion.div style={{ y: y1 }} className="absolute -left-40 -top-48 h-[36rem] w-[36rem]">
        <div className="drift h-full w-full rounded-full bg-brand/15 blur-3xl dark:bg-brand/12" />
      </motion.div>
      <motion.div style={{ y: y2 }} className="absolute -right-48 top-1/3 h-[34rem] w-[34rem]">
        <div className="drift h-full w-full rounded-full bg-brand2/15 blur-3xl [animation-delay:-9s]" />
      </motion.div>
    </div>);
}

/* ───────────────────────── chat message rendering ───────────────────────── */

function Inline({ text }: { text: string }) {
  const segs = text.split(/(`[^`\n]+`)/g);
  return (
    <span className="whitespace-pre-wrap break-words">
      {segs.map((s, i) => s.length > 2 && s.startsWith("`") && s.endsWith("`")
        ? <code key={i} className="rounded bg-fg/10 px-1.5 py-0.5 font-mono text-[0.85em]">{s.slice(1, -1)}</code>
        : s)}
    </span>);
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, copy] = useCopy();
  return (
    <div className="my-2 overflow-hidden rounded-xl border border-line bg-bg">
      <div className="flex items-center justify-between border-b border-line px-3 py-1.5 text-xs text-muted">
        <span className="font-mono">{lang || "code"}</span>
        <button onClick={() => copy(code)} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 transition hover:text-fg focus-visible:outline-2 focus-visible:outline-brand">
          <Icon name={copied ? "check" : "copy"} className="h-3.5 w-3.5" />{copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 font-mono text-[13px] leading-relaxed text-fg"><code>{code}</code></pre>
    </div>);
}

function Body({ text }: { text: string }) {
  const parts = text.split(/```(\w*)\n?([\s\S]*?)```/g);
  const out: ReactNode[] = [];
  for (let i = 0; i < parts.length; i += 3) {
    if (parts[i]) out.push(<Inline key={i} text={parts[i]} />);
    if (i + 2 < parts.length) out.push(<CodeBlock key={i + 1} lang={parts[i + 1]} code={parts[i + 2].replace(/\n$/, "")} />);
  }
  return <>{out}</>;
}

const Avatar = () => (
  <span aria-hidden className="mb-1 grid h-7 w-7 shrink-0 place-items-center rounded-full bg-linear-to-br from-brand to-brand2 font-display text-xs font-bold text-brandfg shadow-[0_0_18px_-4px_var(--brand)]">A</span>);

function Bubble({ m }: { m: Msg }) {
  const user = m.role === "user";
  const [copied, copy] = useCopy();
  return (
    <motion.div initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.35, ease: EASE }}
      className={`group flex items-end gap-2 ${user ? "justify-end" : "justify-start"}`}>
      {!user && <Avatar />}
      <div className="max-w-[85%] min-w-0">
        <div className={`rounded-2xl px-4 py-2.5 leading-relaxed ${user ? "rounded-br-md bg-brand text-brandfg shadow-[0_8px_24px_-12px_var(--brand)]" : "rounded-bl-md border border-line bg-surface2"}`}>
          <Body text={m.content} />
        </div>
        {!user && (
          <button onClick={() => copy(m.content)} aria-label="Copy reply"
            className="ml-1 mt-1 inline-flex items-center gap-1 text-xs text-muted transition hover:text-fg focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-brand sm:opacity-0 sm:group-hover:opacity-100">
            <Icon name={copied ? "check" : "copy"} className="h-3.5 w-3.5" />{copied ? "Copied" : "Copy"}
          </button>)}
      </div>
    </motion.div>);
}

function Typing() {
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex items-end gap-2">
      <Avatar />
      <div className="rounded-2xl rounded-bl-md border border-line bg-surface2 px-4 py-3" aria-hidden>
        <span className="flex gap-1.5">{[0, 1, 2].map(i => <span key={i} className="typing-dot block h-2 w-2 rounded-full bg-brand" style={{ animationDelay: `${i * 0.16}s` }} />)}</span>
      </div>
      <p className="mb-1 text-sm text-muted">Agent is thinking… local models can take a while.</p>
    </motion.div>);
}

const SUGGESTIONS = ["What's the weather in Delhi right now?", "Calculate 18% GST on 2,450", "What did we talk about earlier?"];

function EmptyChat({ onPick }: { onPick: (t: string) => void }) {
  return (
    <div className="grid h-full place-items-center">
      <div className="max-w-md text-center">
        <motion.div animate={{ y: [0, -6, 0] }} transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
          className="mx-auto mb-5 h-16 w-16 rounded-full bg-linear-to-br from-brand to-brand2 shadow-[0_0_60px_-8px_var(--brand)]" aria-hidden />
        <p className="text-muted">Ask about the weather in a city, a calculation, or something from an earlier chat.</p>
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          {SUGGESTIONS.map(s => (
            <button key={s} onClick={() => onPick(s)}
              className="rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-muted transition hover:border-brand hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">{s}</button>))}
        </div>
      </div>
    </div>);
}

/* ───────────────────────── dashboard ───────────────────────── */

const STACK = ["React", "Vite", "TypeScript", "Tailwind CSS", "FastAPI", "Python", "Ollama", "Open-Meteo"];

function StackStrip() {
  const { scrollY } = useScroll();
  const x = useTransform(scrollY, v => -v * 0.45);
  const words = [...STACK, ...STACK, ...STACK];
  return (
    <div aria-hidden className="overflow-hidden border-y border-line py-6">
      <motion.div style={{ x }} className="flex w-max items-center whitespace-nowrap font-display text-5xl font-semibold text-fg/10 md:text-7xl">
        {words.map((w, i) => <span key={i} className="flex items-center">{w}<span className="mx-8 text-2xl text-brand/60 md:mx-12">✦</span></span>)}
      </motion.div>
    </div>);
}

function Dashboard({ health, mods, go }: { health: Health | null; mods: Mod[]; go: () => void }) {
  const hero = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: hero, offset: ["start start", "end start"] });
  const textY = useTransform(scrollYProgress, [0, 1], [0, 120]);
  const fade = useTransform(scrollYProgress, [0, 0.85], [1, 0]);
  const ringA = useTransform(scrollYProgress, [0, 1], [0, 140]);
  const ringB = useTransform(scrollYProgress, [0, 1], [0, -200]);
  const orbY = useTransform(scrollYProgress, [0, 1], [0, -90]);
  const orbScale = useTransform(scrollYProgress, [0, 1], [1, 1.25]);
  const chipA = useTransform(scrollYProgress, [0, 1], [0, -160]);
  const chipB = useTransform(scrollYProgress, [0, 1], [0, 90]);

  const pillars = [
    ["cpu", "Runs on your machine", "Inference happens in Ollama on the host computer, not in a cloud API."],
    ["lock", "Private by access key", "Every request carries the access key you set in the backend .env file."],
    ["tool", "Uses tools, not just text", "The agent can look up weather through Open-Meteo, do calculations and recall earlier chats."],
  ] as const;

  return (
    <div className="mx-auto max-w-5xl">
      {/* hero */}
      <div ref={hero} className="relative grid min-h-[78vh] items-center gap-10 md:grid-cols-[1.15fr_1fr]">
        <div aria-hidden className="grid-bg pointer-events-none absolute inset-x-[-10%] inset-y-0" />
        <motion.div style={{ y: textY, opacity: fade }} className="relative">
          <motion.p initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
            className="mb-4 inline-flex items-center gap-2 rounded-full border border-line bg-surface/70 px-3 py-1 text-sm text-muted">
            <Dot ok={!!health?.ollama} label={health?.ollama ? "Ollama online" : "Ollama offline"} />
            {health?.model ?? "qwen3:8b"} · MCA010
          </motion.p>
          <h2 className="font-display text-5xl font-bold leading-[1.02] tracking-tight md:text-7xl">
            {["Local LLM-Based", "AI Agent"].map((line, i) => (
              <span key={line} className="block overflow-hidden pb-1">
                <motion.span className={`block ${i === 1 ? "text-gradient" : ""}`} initial={{ y: "105%" }} animate={{ y: 0 }}
                  transition={{ duration: 0.8, delay: 0.15 + i * 0.12, ease: EASE }}>{line}</motion.span>
              </span>))}
          </h2>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.55 }} className="mt-5 max-w-md text-lg text-muted">
            Study assistance, data analysis, code documentation and x402 micropayments.
          </motion.p>
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.7 }} className="mt-8">
            <motion.button whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }} onClick={go}
              className="rounded-xl bg-brand px-6 py-3 font-medium text-brandfg shadow-[0_10px_40px_-12px_var(--brand)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">Open chat</motion.button>
          </motion.div>
        </motion.div>

        <div aria-hidden className="relative mx-auto aspect-square w-full max-w-sm">
          <motion.div style={{ rotate: ringA }} className="absolute inset-0 rounded-full border border-line" />
          <motion.div style={{ rotate: ringB }} className="absolute inset-9 rounded-full border border-dashed border-brand/40" />
          <motion.div style={{ y: orbY, scale: orbScale }} className="absolute inset-[22%] rounded-full bg-linear-to-br from-brand to-brand2 shadow-[0_0_90px_-10px_var(--brand)]" />
          <motion.div style={{ y: chipA }} className="glass absolute left-[-4%] top-[14%] rounded-xl border border-line px-3 py-1.5 font-mono text-xs">weather()</motion.div>
          <motion.div style={{ y: chipB }} className="glass absolute bottom-[16%] right-[-2%] rounded-xl border border-line px-3 py-1.5 font-mono text-xs">calculate()</motion.div>
          <motion.div style={{ y: chipA }} className="glass absolute bottom-[4%] left-[12%] rounded-xl border border-line px-3 py-1.5 font-mono text-xs">recall()</motion.div>
        </div>

        <motion.div aria-hidden style={{ opacity: fade }} className="absolute bottom-2 left-1/2 hidden -translate-x-1/2 md:block">
          <span className="flex h-9 w-5 justify-center rounded-full border border-muted/60 pt-1.5"><span className="wheel block h-1.5 w-0.5 rounded bg-brand" /></span>
        </motion.div>
      </div>

      {/* live status */}
      <Stagger className="mt-10 grid gap-3 sm:grid-cols-3">
        {([
          ["Backend", !!health, health ? "Reachable" : "Unreachable"],
          ["Ollama", !!health?.ollama, health?.ollama ? "Reachable" : "Not reachable"],
          ["Model", !!health?.model_installed, `${health?.model ?? "qwen3:8b"} ${health?.model_installed ? "installed" : "not found"}`],
        ] as const).map(([name, ok, text]) => (
          <motion.div key={name} variants={rise}>
            <Spot className="p-4">
              <div className="flex items-center gap-2 font-medium"><Dot ok={ok} label={`${name}: ${ok ? "ok" : "problem"}`} />{name}</div>
              <div className="mt-1 text-sm text-muted">{text}</div>
            </Spot>
          </motion.div>))}
      </Stagger>

      {/* modules */}
      {mods.length > 0 && (
        <section className="mt-20">
          <motion.h3 initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} className="font-display text-3xl font-semibold tracking-tight">Modules</motion.h3>
          <Stagger className="mt-6 grid gap-3 sm:grid-cols-2">
            {mods.map(m => (
              <motion.div key={m.id} variants={rise}>
                <Spot className="h-full p-5">
                  <div className="flex items-center gap-2"><Dot ok={m.available} label={m.available ? "available" : "not available"} /><span className="font-medium">{m.name}</span>
                    <span className={`ml-auto rounded-full px-2 py-0.5 text-xs ${m.available ? "bg-brand/15 text-brand" : "bg-warn/15 text-warn"}`}>{m.available ? "Live" : "Not connected"}</span></div>
                  <p className="mt-2 text-sm text-muted">{m.note}</p>
                </Spot>
              </motion.div>))}
          </Stagger>
        </section>)}

      {/* pillars */}
      <section className="mt-24">
        <motion.h3 initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
          className="max-w-xl font-display text-3xl font-semibold leading-tight tracking-tight md:text-4xl">Built to run on hardware you control.</motion.h3>
        <Stagger className="mt-8 grid gap-4 md:grid-cols-3">
          {pillars.map(([icon, title, text]) => (
            <motion.div key={title} variants={rise}>
              <Spot className="h-full p-6">
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand/12 text-brand"><Icon name={icon} /></span>
                <h4 className="mt-4 font-display text-lg font-semibold">{title}</h4>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{text}</p>
              </Spot>
            </motion.div>))}
        </Stagger>
      </section>

      <div className="-mx-4 mt-24 md:-mx-6"><StackStrip /></div>

      <motion.section initial={{ opacity: 0, y: 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.7, ease: EASE }}
        className="my-24 flex flex-col items-start justify-between gap-6 rounded-3xl border border-line bg-surface/70 p-8 md:flex-row md:items-center md:p-10">
        <h3 className="max-w-md font-display text-3xl font-semibold leading-tight tracking-tight">Ask the agent something.</h3>
        <motion.button whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }} onClick={go}
          className="rounded-xl bg-brand px-6 py-3 font-medium text-brandfg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">Open chat</motion.button>
      </motion.section>
    </div>);
}

/* ───────────────────────── about: scroll-driven architecture ───────────────────────── */

const FLOW = [
  ["Browser", "React, Vercel", "HTTPS + access key"],
  ["Tunnel", "Cloudflare / ngrok", ""],
  ["FastAPI backend", "run_agent() + tools + conversation_store", "localhost only"],
  ["Ollama", "qwen3:8b", ""],
] as const;

function FlowNode({ i, progress, title, sub, link }: { i: number; progress: MotionValue<number>; title: string; sub: string; link: string }) {
  const s = i / FLOW.length;
  const opacity = useTransform(progress, [Math.max(0, s - 0.1), s + 0.08], [0.2, 1]);
  const x = useTransform(progress, [Math.max(0, s - 0.1), s + 0.08], [-28, 0]);
  return (
    <motion.div style={{ opacity, x }} className="relative pl-14">
      <span className="absolute left-0 top-3 grid h-10 w-10 place-items-center rounded-full border border-line bg-surface font-mono text-sm text-brand">{i + 1}</span>
      <Spot className="p-5">
        <h3 className="font-display text-xl font-semibold">{title}</h3>
        <p className="mt-1 font-mono text-sm text-muted">{sub}</p>
      </Spot>
      {link && <p className="ml-1 mt-5 font-mono text-xs text-brand">↓ {link}</p>}
    </motion.div>);
}

function About() {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 70%", "end 60%"] });
  const fill = useSpring(scrollYProgress, { stiffness: 110, damping: 26 });
  return (
    <div className="mx-auto max-w-2xl space-y-6 pb-24">
      <motion.h2 initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} className="font-display text-4xl font-bold tracking-tight">About this project</motion.h2>
      <p className="leading-relaxed">Local LLM-Based AI Agent for Study Assistance, Data Analysis, Code Documentation and x402 Micropayments. MCA010, JSS University, Noida, Session 2025–26.</p>
      <p className="text-sm text-muted">Scroll to follow a request from the browser to the model.</p>

      <div ref={ref} className="relative space-y-14 py-6">
        <div aria-hidden className="absolute bottom-10 left-5 top-10 w-px bg-line">
          <motion.div style={{ scaleY: fill }} className="h-full w-full origin-top bg-linear-to-b from-brand to-brand2" />
        </div>
        {FLOW.map(([title, sub, link], i) => <FlowNode key={title} i={i} progress={fill} title={title} sub={sub} link={link} />)}
      </div>

      <p className="text-sm text-muted">Stack: React, Vite, TypeScript, Tailwind CSS, FastAPI, Python, Ollama, Open-Meteo.</p>
    </div>);
}

/* ───────────────────────── access-key gate ───────────────────────── */

function Gate({ onSubmit, dark, onToggle }: { onSubmit: (k: string) => void; dark: boolean; onToggle: () => void }) {
  const [value, setValue] = useState("");
  const [show, setShow] = useState(false);
  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden bg-bg p-6 text-fg">
      <Aurora />
      <div className="absolute right-4 top-4 z-10"><ThemeToggle dark={dark} onToggle={onToggle} /></div>
      <motion.form initial={{ opacity: 0, y: 24, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ duration: 0.7, ease: EASE }}
        className="glass relative z-10 w-full max-w-sm space-y-4 rounded-3xl border border-line p-7 shadow-2xl shadow-black/10"
        onSubmit={e => { e.preventDefault(); if (value.trim()) onSubmit(value.trim()); }}>
        <span className="grid h-11 w-11 place-items-center rounded-2xl bg-linear-to-br from-brand to-brand2 text-brandfg"><Icon name="lock" /></span>
        <h1 className="font-display text-3xl font-semibold tracking-tight">Enter access key</h1>
        <p className="text-sm text-muted">This demo is private. Use the key set in the backend .env file.</p>
        <div className="relative">
          <input type={show ? "text" : "password"} autoFocus autoComplete="off" value={value} onChange={e => setValue(e.target.value)} aria-label="Access key"
            className="w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 pr-11 transition focus:border-brand focus:outline-2 focus:outline-brand/40" />
          <button type="button" onClick={() => setShow(v => !v)} aria-label={show ? "Hide key" : "Show key"}
            className="absolute right-1.5 top-1.5 grid h-8 w-8 place-items-center rounded-lg text-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-brand"><Icon name={show ? "eyeoff" : "eye"} className="h-[18px] w-[18px]" /></button>
        </div>
        <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
          className="w-full rounded-xl bg-brand py-2.5 font-medium text-brandfg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">Continue</motion.button>
      </motion.form>
    </main>);
}

/* ───────────────────────── app ───────────────────────── */

function Shell() {
  const [key, setKey] = useState(store.get("apikey") || "");
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
  const list = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);
  const chatSeq = useRef(0); // BUG FIX: lets us ignore replies that arrive after the user cleared/switched chat
  const reduced = useReducedMotion();
  const { dark, toggle } = useTheme();

  const loadHealth = useCallback(async () => {
    try {
      const r = await fetch(API + "/api/health", { headers: { "ngrok-skip-browser-warning": "1" } });
      if (!r.ok) throw new Error("unhealthy"); // BUG FIX: a 404/502 tunnel page was parsed as health data
      setHealth(await r.json());
    } catch { setHealth(null); }
  }, []);

  const refresh = useCallback(async () => {
    await loadHealth();
    if (!key) return;
    try {
      setMods(await api<Mod[]>("/api/modules", key));
      setConvs((await api<{ conversations: string[] }>(`/api/conversations?user_id=${USER}`, key)).conversations);
    } catch (e) {
      if ((e as Error).message.includes("access key")) { store.del("apikey"); setKey(""); }
    }
  }, [key, loadHealth]);

  useEffect(() => { refresh(); }, [refresh]);

  /* BUG FIX: status was only checked once, so "Ollama online" went stale. Re-check every 30 s while the tab is visible. */
  useEffect(() => {
    const t = setInterval(() => { if (!document.hidden) loadHealth(); }, 30000);
    return () => clearInterval(t);
  }, [loadHealth]);

  /* BUG FIX: scrollIntoView also scrolled the whole page. Scroll only the message list. */
  useEffect(() => {
    const run = () => { const el = list.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: reduced ? "auto" : "smooth" }); };
    run();
    const t = setTimeout(run, 320); // the chat panel mounts after the page-transition exit finishes
    return () => clearTimeout(t);
  }, [msgs, loading, tab, reduced]);

  useEffect(() => { window.scrollTo({ top: 0 }); setError(""); }, [tab]);
  useEffect(() => {
    if (!menu) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenu(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menu]);
  useEffect(() => { // auto-grow the message box
    const a = area.current;
    if (a) { a.style.height = "auto"; a.style.height = Math.min(a.scrollHeight, 160) + "px"; }
  }, [input, tab]);

  const send = async () => {
    const text = input.trim();
    if (!text || loading) return;
    const seq = chatSeq.current;
    setInput(""); setError(""); setLoading(true);
    setMsgs(m => [...m, { role: "user", content: text }]);
    try {
      const r = await api<{ reply: string; conversation_id: string }>("/api/chat", key,
        { method: "POST", body: JSON.stringify({ user_id: USER, conversation_id: convId, message: text }) });
      if (seq === chatSeq.current) {
        setConvId(r.conversation_id);
        setMsgs(m => [...m, { role: "assistant", content: r.reply }]);
      }
      refresh();
    } catch (e) {
      if (seq === chatSeq.current) setError(e instanceof TypeError ? "Cannot reach the backend. Is it running and is the tunnel URL current?" : (e as Error).message);
    } finally {
      if (seq === chatSeq.current) { setLoading(false); area.current?.focus(); }
    }
  };

  const open = async (id: string) => {
    setError("");
    const seq = ++chatSeq.current;
    setLoading(false);
    try {
      const r = await api<{ messages: Msg[] }>(`/api/conversations/${id}?user_id=${USER}`, key);
      if (seq !== chatSeq.current) return;
      setMsgs(r.messages); setConvId(id); setTab("chat");
    } catch (e) { setError((e as Error).message); }
  };
  const fresh = () => { chatSeq.current++; setLoading(false); setConvId(null); setMsgs([]); setError(""); };

  if (!key) return <Gate dark={dark} onToggle={toggle} onSubmit={k => { store.set("apikey", k); setKey(k); }} />;

  const unavailable = (id: string) => mods.find(m => m.id === id);
  const title = NAV.find(n => n[0] === tab)?.[1];

  return (
    <div className="relative flex min-h-dvh bg-bg text-fg">
      <Aurora />
      <ScrollBar />

      {menu && <button aria-label="Close menu" onClick={() => setMenu(false)} className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm md:hidden" />}

      <aside className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-line bg-surface p-4 transition-transform duration-300 md:sticky md:top-0 md:z-20 md:h-dvh md:translate-x-0 md:bg-surface/70 md:backdrop-blur-xl ${menu ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="mb-8 flex items-center gap-2.5 px-1">
          <span aria-hidden className="h-7 w-7 rounded-lg bg-linear-to-br from-brand to-brand2 shadow-[0_0_20px_-4px_var(--brand)]" />
          <h2 className="font-display text-lg font-semibold tracking-tight">MCA010 Agent</h2>
        </div>
        <nav className="space-y-1">
          {NAV.map(([id, label]) => (
            <button key={id} onClick={() => { setTab(id); setMenu(false); }} aria-current={tab === id ? "page" : undefined}
              className={`relative flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-brand ${tab === id ? "text-brand" : "text-muted hover:text-fg"}`}>
              {tab === id && <motion.span layoutId="nav-pill" className="absolute inset-0 rounded-xl bg-brand/12 ring-1 ring-brand/30" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
              <Icon name={id} className="relative h-[18px] w-[18px]" /><span className="relative">{label}</span>
            </button>))}
        </nav>
        <button onClick={() => { store.del("apikey"); setKey(""); }} className="mt-auto px-1 text-left text-sm text-muted hover:text-fg focus-visible:outline-2 focus-visible:outline-brand">Change access key</button>
      </aside>

      <main className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="glass sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line px-4">
          <button className="grid h-9 w-9 place-items-center rounded-lg border border-line md:hidden" aria-label="Menu" aria-expanded={menu} onClick={() => setMenu(v => !v)}><Icon name="menu" className="h-[18px] w-[18px]" /></button>
          <AnimatePresence mode="wait" initial={false}>
            <motion.h1 key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.18 }} className="font-display text-lg font-semibold">{title}</motion.h1>
          </AnimatePresence>
          <span className="ml-auto flex items-center gap-2 text-sm text-muted"><Dot ok={!!health?.ollama} />{health?.ollama ? "Ollama online" : "Ollama offline"}</span>
          <ThemeToggle dark={dark} onToggle={toggle} />
        </header>

        <section className="flex-1 p-4 md:p-6">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={tab} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.22, ease: EASE }}>

              {tab === "dashboard" && <Dashboard health={health} mods={mods} go={() => setTab("chat")} />}

              {tab === "chat" && (
                <div className="mx-auto flex h-[calc(100dvh-3.5rem-2rem)] max-w-3xl flex-col md:h-[calc(100dvh-3.5rem-3rem)]">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <span className="truncate font-mono text-xs text-muted">{convId ? `conversation ${convId}` : "new conversation"}</span>
                    <button onClick={fresh} className="rounded-lg border border-line px-3 py-1 text-sm text-muted transition hover:border-brand hover:text-fg focus-visible:outline-2 focus-visible:outline-brand">Clear chat</button>
                  </div>
                  <div ref={list} className="flex-1 space-y-4 overflow-y-auto rounded-2xl border border-line bg-surface/70 p-4 backdrop-blur" aria-live="polite">
                    {msgs.length === 0 && !loading && <EmptyChat onPick={t => { setInput(t); area.current?.focus(); }} />}
                    {msgs.map((m, i) => <Bubble key={i} m={m} />)}
                    {loading && <Typing />}
                  </div>
                  <AnimatePresence>
                    {error && <motion.p role="alert" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }}
                      className="mt-2 overflow-hidden rounded-lg border border-danger/30 bg-danger/10 p-2.5 text-sm text-danger">{error}</motion.p>}
                  </AnimatePresence>
                  <form className="mt-3 flex items-end gap-2" onSubmit={e => { e.preventDefault(); send(); }}>
                    <div className="relative flex-1">
                      <textarea ref={area} rows={1} value={input} onChange={e => setInput(e.target.value)} placeholder="Type a message" aria-label="Message" maxLength={4000}
                        onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}
                        className="block max-h-40 w-full resize-none rounded-xl border border-line bg-surface px-3.5 py-2.5 transition placeholder:text-muted focus:border-brand focus:outline-2 focus:outline-brand/40" />
                      {input.length > 3400 && <span className="absolute -top-5 right-1 font-mono text-xs text-muted">{input.length}/4000</span>}
                    </div>
                    <motion.button whileTap={{ scale: 0.94 }} disabled={loading || !input.trim()} aria-label="Send"
                      className="flex h-[42px] items-center gap-2 rounded-xl bg-brand px-4 font-medium text-brandfg transition disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand">
                      <span className="hidden sm:inline">Send</span><Icon name="send" className="h-[18px] w-[18px]" />
                    </motion.button>
                  </form>
                  <p className="mt-1.5 hidden text-xs text-muted sm:block">Enter to send · Shift+Enter for a new line</p>
                </div>)}

              {(["study", "data", "code", "pay"] as Tab[]).includes(tab) && (
                <div className="mx-auto max-w-xl pt-6">
                  <div className="rounded-2xl border border-warn/40 bg-warn/10 p-6">
                    <h2 className="font-display text-xl font-semibold">Not available yet</h2>
                    <p className="mt-2 text-sm leading-relaxed">{unavailable(tab)?.note ?? "This module is not connected to the agent."} Nothing is simulated on this page.</p>
                    {tab === "pay" && <p className="mt-2 text-sm leading-relaxed">No wallet is connected and no USDC can be spent from this website.</p>}
                  </div>
                </div>)}

              {tab === "history" && (
                <div className="mx-auto max-w-xl">
                  {error && <p role="alert" className="mb-3 text-sm text-danger">{error}</p>}
                  {convs.length === 0 ? <p className="text-muted">No saved conversations yet. Start one in AI Chat.</p> : (
                    <Stagger className="space-y-2">
                      {convs.map(c => (
                        <motion.div key={c} variants={rise}>
                          <button onClick={() => open(c)} className="group flex w-full items-center gap-3 rounded-xl border border-line bg-surface/80 px-4 py-3 text-left transition hover:border-brand hover:bg-surface focus-visible:outline-2 focus-visible:outline-brand">
                            <Icon name="chat" className="h-[18px] w-[18px] text-muted group-hover:text-brand" /><span className="min-w-0 flex-1 truncate font-mono text-sm">{c}</span>
                            <Icon name="chevron" className="h-4 w-4 text-muted transition group-hover:translate-x-1 group-hover:text-brand" />
                          </button>
                        </motion.div>))}
                    </Stagger>)}
                </div>)}

              {tab === "about" && <About />}

            </motion.div>
          </AnimatePresence>
        </section>
      </main>
    </div>);
}

export default function App() {
  return <MotionConfig reducedMotion="user"><Shell /></MotionConfig>;
}
