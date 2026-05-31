"use client";

import { useState, useEffect, useRef } from "react";

const BASE = "http://localhost:8000/api";

const TOPIC_LABELS: Record<string, string> = {
  dsa: "DSA", system_design: "System Design", java: "Java",
  python: "Python", aws: "AWS", behavioral: "Behavioral",
  projects: "Projects", general: "General",
};

const TOPIC_COLORS: Record<string, string> = {
  dsa: "#7c3aed", system_design: "#0ea5e9", java: "#f97316",
  python: "#10b981", aws: "#f59e0b", behavioral: "#ec4899",
  projects: "#06b6d4", general: "#6b7280",
};

const MASTERY_COLORS = ["", "#f87171", "#fbbf24", "#fbbf24", "#4ade80", "#4ade80"];
const MASTERY_LABELS = ["", "Not covered", "Introduced", "Intermediate", "Strong", "Mastered"];

type View = "chat" | "progress" | "star" | "revision" | "patterns";
type Mode = "chat" | "interview";
interface Message { id: string; role: "user" | "assistant"; content: string; }
interface SessionSummary { id: string; title: string; topic?: string; message_count: number; }

// ── Simple markdown renderer (no deps) ───────────────────────────────────────
function renderMarkdown(text: string): string {
  return text
    .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
      `<pre style="background:#18181b;border:1px solid #27272a;border-radius:6px;padding:12px;overflow-x:auto;margin:8px 0"><code style="color:#e4e4e7;font-size:12px;font-family:monospace">${escHtml(code.trim())}</code></pre>`)
    .replace(/`([^`]+)`/g, `<code style="background:#27272a;color:#c4b5fd;padding:2px 6px;border-radius:4px;font-size:12px">$1</code>`)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^### (.+)$/gm, `<h3 style="color:#f4f4f5;font-size:14px;margin:14px 0 6px 0">$1</h3>`)
    .replace(/^## (.+)$/gm, `<h2 style="color:#f4f4f5;font-size:15px;margin:16px 0 8px 0">$1</h2>`)
    .replace(/^# (.+)$/gm, `<h1 style="color:#f4f4f5;font-size:16px;margin:16px 0 8px 0">$1</h1>`)
    .replace(/^[-*] (.+)$/gm, `<div style="padding:2px 0 2px 16px;color:#e4e4e7">• $1</div>`)
    .replace(/^\d+\. (.+)$/gm, `<div style="padding:2px 0 2px 16px;color:#e4e4e7">$1</div>`)
    .replace(/\n\n/g, `<br/><br/>`)
    .replace(/\n/g, `<br/>`);
}

function escHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div
      style={{ lineHeight: 1.7, color: "#e4e4e7", fontSize: 13 }}
      dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
    />
  );
}

// ── App shell ─────────────────────────────────────────────────────────────────
export default function App() {
  const [view, setView] = useState<View>("chat");
  return (
    <div style={{ display: "flex", height: "100vh", background: "#09090b", color: "#f4f4f5", fontFamily: "monospace", fontSize: 13 }}>
      <aside style={{ width: 190, borderRight: "1px solid #27272a", display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid #27272a", fontWeight: 700, fontSize: 14 }}>
          PrepAI <span style={{ fontSize: 9, color: "#71717a", border: "1px solid #3f3f46", padding: "1px 5px", borderRadius: 4, marginLeft: 6 }}>local</span>
        </div>
        <nav style={{ padding: "8px" }}>
          {([
            ["chat", "💬 Chat"],
            ["progress", "📈 My Progress"],
            ["revision", "🔁 Revision Queue"],
            ["patterns", "🔍 Pattern Gaps"],
            ["star", "⭐ STAR Scorer"],
          ] as [View, string][]).map(([id, label]) => (
            <button key={id} onClick={() => setView(id)} style={{
              display: "block", width: "100%", textAlign: "left", padding: "8px 10px",
              borderRadius: 6, border: "none", cursor: "pointer", fontSize: 12, marginBottom: 2,
              background: view === id ? "#27272a" : "transparent",
              color: view === id ? "#f4f4f5" : "#71717a",
            }}>{label}</button>
          ))}
        </nav>
      </aside>
      <main style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
        {view === "chat" && <ChatView />}
        {view === "progress" && <ProgressView />}
        {view === "revision" && <RevisionView />}
        {view === "patterns" && <PatternGapsView />}
        {view === "star" && <StarView />}
      </main>
    </div>
  );
}

// ── Chat ─────────────────────────────────────────────────────────────────────
function ChatView() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [topic, setTopic] = useState("");
  const [mode, setMode] = useState<Mode>("chat");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { fetchSessions(); }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, loading]);

  async function fetchSessions() {
    try { const r = await fetch(`${BASE}/chat/sessions`); setSessions(await r.json()); } catch {}
  }
  async function loadSession(id: string) {
    try {
      const r = await fetch(`${BASE}/chat/sessions/${id}`);
      const d = await r.json();
      setSessionId(d.id);
      setMessages(d.messages.map((m: any) => ({ id: m.id, role: m.role, content: m.content })));
    } catch {}
  }
  function newSession() { setSessionId(undefined); setMessages([]); inputRef.current?.focus(); }

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading) return;
    setInput(""); setLoading(true);
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: "user", content: text }]);
    try {
      const r = await fetch(`${BASE}/chat/`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text, topic: topic || undefined, mode, use_rag: true }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setSessionId(d.session_id);
      setMessages(prev => [...prev, { id: d.message.id, role: "assistant", content: d.message.content }]);
      fetchSessions();
    } catch (e: any) {
      setMessages(prev => [...prev, { id: crypto.randomUUID(), role: "assistant", content: `Error: ${e.message}` }]);
    } finally { setLoading(false); inputRef.current?.focus(); }
  }

  const SUGGESTIONS = [
    "What DSA patterns have I covered?",
    "What should I study today?",
    "What are my weak areas across all topics?",
    "Which patterns am I missing?",
    "What Java topics have I learned?",
    "Design a distributed rate limiter",
  ];

  return (
    <div style={{ display: "flex", flex: 1, minWidth: 0, overflow: "hidden" }}>
      {/* Session sidebar */}
      <div style={{ width: 200, borderRight: "1px solid #27272a", display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div style={{ padding: "8px" }}>
          <button onClick={newSession} style={{ width: "100%", padding: "7px 10px", background: "transparent", border: "1px solid #3f3f46", color: "#a1a1aa", borderRadius: 6, cursor: "pointer", fontSize: 11 }}>+ New session</button>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {sessions.map(s => (
            <div key={s.id} onClick={() => loadSession(s.id)} style={{
              padding: "8px 10px", cursor: "pointer", fontSize: 11, borderBottom: "1px solid #18181b",
              background: sessionId === s.id ? "#27272a" : "transparent",
              color: sessionId === s.id ? "#f4f4f5" : "#a1a1aa",
            }}>
              <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.title}</div>
              {s.topic && <div style={{ fontSize: 10, color: TOPIC_COLORS[s.topic] || "#52525b", marginTop: 2 }}>{TOPIC_LABELS[s.topic] || s.topic}</div>}
              <div style={{ fontSize: 10, color: "#52525b" }}>{s.message_count} msgs</div>
            </div>
          ))}
        </div>
      </div>

      {/* Main chat */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* Toolbar */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", borderBottom: "1px solid #27272a" }}>
          <select value={topic} onChange={e => setTopic(e.target.value)} style={{ background: "#18181b", border: "1px solid #3f3f46", color: "#d4d4d8", borderRadius: 6, padding: "4px 8px", fontSize: 11, cursor: "pointer" }}>
            <option value="">All topics</option>
            {Object.entries(TOPIC_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <div style={{ display: "flex", border: "1px solid #3f3f46", borderRadius: 6, overflow: "hidden" }}>
            {(["chat", "interview"] as Mode[]).map(m => (
              <button key={m} onClick={() => setMode(m)} style={{ padding: "4px 10px", fontSize: 11, border: "none", cursor: "pointer", textTransform: "capitalize", background: mode === m ? "#3f3f46" : "transparent", color: mode === m ? "#f4f4f5" : "#71717a" }}>{m}</button>
            ))}
          </div>
          <span style={{ marginLeft: "auto", fontSize: 10, color: "#3f3f46" }}>progress Qs → DB · knowledge Qs → RAG</span>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px", display: "flex", flexDirection: "column", gap: 16 }}>
          {messages.length === 0 && !loading && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 12 }}>
              <p style={{ color: "#52525b", fontSize: 14 }}>PrepAI — Personal Interview OS</p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, width: "100%", maxWidth: 500 }}>
                {SUGGESTIONS.map(q => (
                  <button key={q} onClick={() => { setInput(q); setTimeout(() => inputRef.current?.focus(), 50); }} style={{
                    background: "#18181b", border: "1px solid #27272a", borderRadius: 6,
                    padding: "8px 10px", fontSize: 11, color: "#a1a1aa", cursor: "pointer", textAlign: "left",
                  }}>{q}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => (
            <div key={msg.id} style={{ display: "flex", gap: 10, flexDirection: msg.role === "user" ? "row-reverse" : "row" }}>
              <div style={{
                width: 26, height: 26, borderRadius: "50%", flexShrink: 0,
                background: msg.role === "user" ? "#3f3f46" : "#4c1d95",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 10, fontWeight: 700, color: "#f4f4f5", marginTop: 2,
              }}>{msg.role === "user" ? "U" : "AI"}</div>

              {msg.role === "user" ? (
                <div style={{ maxWidth: "75%", background: "#27272a", borderRadius: 8, padding: "8px 12px", color: "#e4e4e7", lineHeight: 1.6, wordBreak: "break-word" }}>
                  {msg.content}
                </div>
              ) : (
                <div style={{ flex: 1, maxWidth: "85%" }}>
                  <MarkdownMessage content={msg.content} />
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div style={{ display: "flex", gap: 10 }}>
              <div style={{ width: 26, height: 26, borderRadius: "50%", background: "#4c1d95", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#f4f4f5" }}>AI</div>
              <span style={{ color: "#71717a", paddingTop: 4 }}>Thinking…</span>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={{ padding: "0 16px 16px" }}>
          <div style={{ border: "1px solid #3f3f46", borderRadius: 10, background: "#18181b" }}>
            <textarea ref={inputRef} value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
              placeholder="Ask about your progress, patterns, or any technical topic…"
              rows={3} style={{ background: "transparent", border: "none", outline: "none", padding: "10px 14px 6px", color: "#f4f4f5", resize: "none", fontFamily: "monospace", fontSize: 13, lineHeight: 1.6, width: "100%", boxSizing: "border-box" }} />
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 10px 8px" }}>
              <span style={{ fontSize: 10, color: "#52525b" }}>↵ send · shift+↵ newline</span>
              <button onClick={sendMessage} disabled={!input.trim() || loading} style={{ padding: "5px 14px", borderRadius: 6, fontSize: 12, fontWeight: 600, background: input.trim() && !loading ? "#7c3aed" : "#27272a", color: input.trim() && !loading ? "#fff" : "#52525b", border: "none", cursor: input.trim() && !loading ? "pointer" : "not-allowed" }}>Send</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Progress Dashboard — multi-topic ──────────────────────────────────────────
function ProgressView() {
  const [dsa, setDsa] = useState<any>(null);
  const [mastery, setMastery] = useState<any>({});
  const [today, setToday] = useState<any>(null);
  const [weaknesses, setWeaknesses] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${BASE}/progress/dsa`).then(r => r.json()),
      fetch(`${BASE}/progress/mastery`).then(r => r.json()),
      fetch(`${BASE}/progress/today`).then(r => r.json()),
      fetch(`${BASE}/progress/weaknesses`).then(r => r.json()),
    ]).then(([d, m, t, w]) => {
      setDsa(d); setMastery(m); setToday(t); setWeaknesses(w);
    }).catch(console.error).finally(() => setLoading(false));
  }, []);

  if (loading) return <Center>Loading progress…</Center>;

  const patterns = dsa?.patterns_covered || {};
  const missing = dsa?.missing_patterns || [];
  const difficulty = dsa?.difficulty_breakdown || {};
  const hasMastery = Object.keys(mastery).length > 0;

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1 }}>
      <h2 style={{ color: "#f4f4f5", fontWeight: 700, margin: "0 0 20px 0" }}>📈 My Progress</h2>

      {/* Stats row */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
        {[
          ["DSA Problems", dsa?.total_problems ?? 0],
          ["Patterns Covered", Object.keys(patterns).length],
          ["Topics Tracked", Object.values(mastery).reduce((s: number, d: any) => s + (d.topic_count || 0), 0)],
          ["Patterns Missing", missing.length],
        ].map(([label, value]) => (
          <div key={label as string} style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: "14px 16px" }}>
            <div style={{ color: "#71717a", fontSize: 11, marginBottom: 4 }}>{label}</div>
            <div style={{ color: "#f4f4f5", fontSize: 22, fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Today's recommendations */}
      {today?.recommendations?.length > 0 && (
        <div style={{ background: "#0f172a", border: "1px solid #1e3a5f", borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <div style={{ color: "#7dd3fc", fontWeight: 600, marginBottom: 12, fontSize: 12 }}>
            📋 Study Today — {today.pattern_coverage} DSA pattern coverage
          </div>
          {today.recommendations.map((r: any, i: number) => (
            <div key={i} style={{ marginBottom: 10, paddingBottom: 10, borderBottom: i < today.recommendations.length - 1 ? "1px solid #1e3a5f" : "none" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ fontSize: 10, background: TOPIC_COLORS[r.topic] || "#3f3f46", color: "#fff", padding: "1px 6px", borderRadius: 4, flexShrink: 0 }}>
                  {TOPIC_LABELS[r.topic] || r.topic}
                </span>
                <span style={{ color: "#f4f4f5", fontSize: 12 }}>{r.action}</span>
              </div>
              <div style={{ color: "#52525b", fontSize: 10, marginLeft: 0, marginTop: 4 }}>{r.reason}</div>
            </div>
          ))}
        </div>
      )}

      {/* Multi-topic mastery from KB files */}
      {hasMastery && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ color: "#a1a1aa", fontWeight: 600, fontSize: 12, marginBottom: 10 }}>📚 Topic Mastery (from your learning notes)</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {Object.entries(mastery).map(([cat, data]: any) => (
              <div key={cat} style={{ background: "#18181b", border: `1px solid ${TOPIC_COLORS[cat] || "#27272a"}30`, borderRadius: 8, padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                  <span style={{ color: TOPIC_COLORS[cat] || "#a1a1aa", fontWeight: 600, fontSize: 12 }}>
                    {TOPIC_LABELS[cat] || cat}
                  </span>
                  <span style={{ fontSize: 11, color: "#71717a" }}>{data.topic_count} topics · avg {data.avg_mastery}/5</span>
                </div>
                {/* Progress bar */}
                <div style={{ height: 4, background: "#27272a", borderRadius: 2, marginBottom: 10 }}>
                  <div style={{ height: "100%", width: `${(data.avg_mastery / 5) * 100}%`, background: TOPIC_COLORS[cat] || "#7c3aed", borderRadius: 2 }} />
                </div>
                {data.strong_topics?.length > 0 && (
                  <div style={{ marginBottom: 4 }}>
                    <span style={{ fontSize: 10, color: "#4ade80" }}>Strong: </span>
                    <span style={{ fontSize: 10, color: "#86efac" }}>{data.strong_topics.slice(0, 3).join(", ")}</span>
                  </div>
                )}
                {data.weak_topics?.length > 0 && (
                  <div>
                    <span style={{ fontSize: 10, color: "#f87171" }}>Weak: </span>
                    <span style={{ fontSize: 10, color: "#fca5a5" }}>{data.weak_topics.slice(0, 3).join(", ")}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {!hasMastery && (
        <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <div style={{ color: "#71717a", fontSize: 12 }}>
            No topic mastery data yet. Add your knowledge base MD files to <code style={{ color: "#c4b5fd" }}>data/notes/</code> and re-run ingestion.
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {/* DSA patterns */}
        <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
          <div style={{ color: "#4ade80", fontWeight: 600, marginBottom: 10, fontSize: 12 }}>✅ DSA Patterns ({Object.keys(patterns).length})</div>
          {Object.keys(patterns).length === 0 && <p style={{ color: "#52525b", fontSize: 11 }}>No patterns detected. Re-run ingestion.</p>}
          {Object.entries(patterns).sort((a: any, b: any) => b[1] - a[1]).map(([p, c]: any) => (
            <div key={p} style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 12 }}>
              <span style={{ color: "#86efac" }}>{p}</span>
              <span style={{ color: "#4ade80", fontWeight: 600 }}>{c}×</span>
            </div>
          ))}
        </div>

        {/* Difficulty + weaknesses */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
            <div style={{ color: "#a1a1aa", fontWeight: 600, marginBottom: 10, fontSize: 12 }}>Difficulty Breakdown</div>
            {Object.entries(difficulty).map(([d, c]: any) => {
              const color = d === "Easy" ? "#4ade80" : d === "Medium" ? "#fbbf24" : "#f87171";
              return (
                <div key={d} style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 12 }}>
                  <span style={{ color }}>{d}</span>
                  <span style={{ color, fontWeight: 600 }}>{c}</span>
                </div>
              );
            })}
            {Object.keys(difficulty).length === 0 && <p style={{ color: "#52525b", fontSize: 11 }}>No data</p>}
          </div>

          {weaknesses && (weaknesses.kb_weaknesses?.length > 0 || weaknesses.session_weaknesses?.length > 0) && (
            <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
              <div style={{ color: "#f87171", fontWeight: 600, marginBottom: 10, fontSize: 12 }}>⚠️ Known Weaknesses</div>
              {weaknesses.kb_weaknesses?.slice(0, 4).map((w: any, i: number) => (
                <div key={i} style={{ fontSize: 11, color: "#fca5a5", marginBottom: 4 }}>
                  • {w.weakness} <span style={{ color: "#52525b" }}>({w.category})</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Missing patterns */}
      {missing.length > 0 && (
        <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16, marginTop: 14 }}>
          <div style={{ color: "#f87171", fontWeight: 600, marginBottom: 10, fontSize: 12 }}>❌ Missing DSA Patterns ({missing.length})</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {missing.map((p: string) => (
              <span key={p} style={{ background: "#27272a", color: "#fca5a5", padding: "3px 8px", borderRadius: 4, fontSize: 11 }}>{p}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Pattern Gaps ──────────────────────────────────────────────────────────────
function PatternGapsView() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${BASE}/progress/gaps`).then(r => r.json()).then(setData).finally(() => setLoading(false));
  }, []);

  if (loading) return <Center>Loading…</Center>;
  if (!data) return <Center>No data</Center>;

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1 }}>
      <h2 style={{ color: "#f4f4f5", fontWeight: 700, margin: "0 0 8px 0" }}>🔍 DSA Pattern Coverage</h2>
      <p style={{ color: "#71717a", fontSize: 12, marginBottom: 20 }}>
        Coverage: <strong style={{ color: "#7dd3fc" }}>{data.coverage_percent}%</strong> of 19 expected senior-level patterns
      </p>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
          <div style={{ color: "#4ade80", fontWeight: 600, marginBottom: 12, fontSize: 12 }}>✅ Covered ({Object.keys(data.covered_patterns || {}).length})</div>
          {Object.entries(data.covered_patterns || {}).map(([p, c]: any) => (
            <div key={p} style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 12 }}>
              <span style={{ color: "#86efac" }}>{p}</span>
              <span style={{ color: "#4ade80" }}>{c} problems</span>
            </div>
          ))}
        </div>
        <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
          <div style={{ color: "#f87171", fontWeight: 600, marginBottom: 12, fontSize: 12 }}>❌ Missing ({(data.missing_patterns || []).length})</div>
          {(data.missing_patterns || []).map((p: string) => (
            <div key={p} style={{ color: "#fca5a5", fontSize: 12, marginBottom: 6 }}>• {p}</div>
          ))}
        </div>
        {Object.keys(data.weak_patterns || {}).length > 0 && (
          <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16, gridColumn: "1 / -1" }}>
            <div style={{ color: "#fbbf24", fontWeight: 600, marginBottom: 10, fontSize: 12 }}>⚠️ Thin Coverage (only 1 solution)</div>
            {Object.keys(data.weak_patterns).map((p: string) => (
              <span key={p} style={{ display: "inline-block", background: "#27272a", color: "#fde68a", padding: "3px 8px", borderRadius: 4, fontSize: 11, marginRight: 6, marginBottom: 6 }}>{p}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Revision Queue ────────────────────────────────────────────────────────────
function RevisionView() {
  const [candidates, setCandidates] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${BASE}/progress/revision`).then(r => r.json())
      .then(d => setCandidates(d.candidates || []))
      .finally(() => setLoading(false));
  }, []);

  async function markRevised(name: string) {
    await fetch(`${BASE}/progress/problem/${encodeURIComponent(name)}/revise`, { method: "POST" });
    setCandidates(prev => prev.map(p => p.problem_name === name ? { ...p, revision_count: (p.revision_count || 0) + 1 } : p));
  }

  const dc = (d: string) => d === "Easy" ? "#4ade80" : d === "Medium" ? "#fbbf24" : "#f87171";

  if (loading) return <Center>Loading…</Center>;

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1 }}>
      <h2 style={{ color: "#f4f4f5", fontWeight: 700, margin: "0 0 8px 0" }}>🔁 Revision Queue</h2>
      <p style={{ color: "#71717a", fontSize: 12, marginBottom: 20 }}>Ranked by priority: low revision count + hard difficulty = top.</p>
      {candidates.length === 0 && <p style={{ color: "#52525b" }}>No problems tracked yet. Run ingestion first.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {candidates.map((p, i) => (
          <div key={p.id || i} style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: "12px 16px", display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#27272a", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, color: "#71717a", flexShrink: 0 }}>{i + 1}</div>
            <div style={{ flex: 1 }}>
              <div style={{ color: "#f4f4f5", fontSize: 13, fontWeight: 500, marginBottom: 4 }}>{p.problem_name}</div>
              <div style={{ display: "flex", gap: 8 }}>
                {p.pattern && <span style={{ fontSize: 10, background: "#27272a", color: "#a1a1aa", padding: "1px 6px", borderRadius: 4 }}>{p.pattern}</span>}
                {p.difficulty && <span style={{ fontSize: 10, color: dc(p.difficulty) }}>{p.difficulty}</span>}
                <span style={{ fontSize: 10, color: "#52525b" }}>revised {p.revision_count || 0}×</span>
              </div>
            </div>
            <button onClick={() => markRevised(p.problem_name)} style={{ padding: "4px 12px", background: "#14532d", border: "1px solid #166534", color: "#4ade80", borderRadius: 6, fontSize: 11, cursor: "pointer" }}>✓ Revised</button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── STAR Scorer ───────────────────────────────────────────────────────────────
function StarView() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  async function score() {
    if (!question.trim() || !answer.trim() || loading) return;
    setLoading(true); setResult(null);
    try {
      const r = await fetch(`${BASE}/analysis/star`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question, answer }) });
      setResult(await r.json());
    } catch (e: any) { setResult({ error: e.message }); }
    finally { setLoading(false); }
  }

  const sc = (n: number) => n >= 4 ? "#4ade80" : n >= 3 ? "#fbbf24" : "#f87171";

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1 }}>
      <h2 style={{ color: "#f4f4f5", fontWeight: 700, margin: "0 0 20px 0" }}>⭐ STAR Answer Scorer</h2>
      <label style={{ fontSize: 11, color: "#71717a", display: "block", marginBottom: 4 }}>Behavioral question</label>
      <input value={question} onChange={e => setQuestion(e.target.value)}
        placeholder="e.g. Tell me about a production incident you handled"
        style={{ width: "100%", background: "#18181b", border: "1px solid #3f3f46", color: "#f4f4f5", borderRadius: 6, padding: "8px 12px", fontSize: 12, fontFamily: "monospace", boxSizing: "border-box", marginBottom: 12 }} />
      <label style={{ fontSize: 11, color: "#71717a", display: "block", marginBottom: 4 }}>Your STAR answer</label>
      <textarea value={answer} onChange={e => setAnswer(e.target.value)}
        placeholder="Situation: ... Task: ... Action: ... Result: ..."
        rows={7} style={{ width: "100%", background: "#18181b", border: "1px solid #3f3f46", color: "#f4f4f5", borderRadius: 6, padding: "8px 12px", fontSize: 12, fontFamily: "monospace", resize: "vertical", boxSizing: "border-box", marginBottom: 12 }} />
      <button onClick={score} disabled={loading || !question.trim() || !answer.trim()}
        style={{ padding: "8px 20px", background: "#7c3aed", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
        {loading ? "Scoring…" : "Score my answer"}
      </button>
      {result?.error && <div style={{ color: "#f87171", fontSize: 12, marginTop: 12 }}>{result.error}</div>}
      {result && !result.error && (
        <div style={{ marginTop: 20, background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
          <div style={{ display: "flex", gap: 20, marginBottom: 14 }}>
            {[["Overall", result.score], ["Situation", result.situation_score], ["Task", result.task_score], ["Action", result.action_score], ["Result", result.result_score]].map(([l, v]: any) => (
              <div key={l} style={{ textAlign: "center" }}>
                <div style={{ fontSize: 22, fontWeight: 700, color: sc(v) }}>{v}/5</div>
                <div style={{ fontSize: 10, color: "#71717a" }}>{l}</div>
              </div>
            ))}
          </div>
          <div style={{ color: "#fbbf24", marginBottom: 10 }}>{result.verdict}</div>
          {result.missing?.length > 0 && <div style={{ marginBottom: 8 }}><div style={{ color: "#f87171", fontSize: 11, marginBottom: 4 }}>Missing:</div>{result.missing.map((m: string, i: number) => <div key={i} style={{ color: "#fca5a5", fontSize: 11, marginLeft: 10 }}>• {m}</div>)}</div>}
          {result.strengths?.length > 0 && <div style={{ marginBottom: 8 }}><div style={{ color: "#4ade80", fontSize: 11, marginBottom: 4 }}>Strengths:</div>{result.strengths.map((s: string, i: number) => <div key={i} style={{ color: "#86efac", fontSize: 11, marginLeft: 10 }}>• {s}</div>)}</div>}
          {result.improved_answer_hint && <div style={{ background: "#0f172a", borderRadius: 6, padding: "8px 12px", fontSize: 11, color: "#7dd3fc", marginTop: 8 }}>💡 {result.improved_answer_hint}</div>}
        </div>
      )}
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1, color: "#52525b" }}>{children}</div>;
}
