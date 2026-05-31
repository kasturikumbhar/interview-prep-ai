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

type View = "chat" | "progress" | "revision" | "patterns" | "star";
type Mode = "chat" | "interview";
interface Message { id: string; role: "user" | "assistant"; content: string; }
interface SessionSummary { id: string; title: string; topic?: string; message_count: number; }

// ── Markdown renderer ─────────────────────────────────────────────────────────
function escHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function renderMarkdown(text: string): string {
  return text
    // fenced code blocks
    .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
      `<pre style="background:#18181b;border:1px solid #3f3f46;border-radius:8px;padding:14px 16px;overflow-x:auto;margin:10px 0;"><code style="color:#e4e4e7;font-size:12px;font-family:'JetBrains Mono',monospace;line-height:1.6">${escHtml(code.trim())}</code></pre>`)
    // inline code
    .replace(/`([^`\n]+)`/g, `<code style="background:#27272a;color:#c4b5fd;padding:1px 6px;border-radius:4px;font-size:12px;font-family:monospace">$1</code>`)
    // bold
    .replace(/\*\*(.+?)\*\*/g, `<strong style="color:#f4f4f5;font-weight:600">$1</strong>`)
    // italic
    .replace(/\*(.+?)\*/g, `<em style="color:#d4d4d8">$1</em>`)
    // h3
    .replace(/^### (.+)$/gm, `<h3 style="color:#f4f4f5;font-size:13px;font-weight:600;margin:16px 0 6px 0;border-bottom:1px solid #27272a;padding-bottom:4px">$1</h3>`)
    // h2
    .replace(/^## (.+)$/gm, `<h2 style="color:#f4f4f5;font-size:14px;font-weight:700;margin:18px 0 8px 0;border-bottom:1px solid #3f3f46;padding-bottom:4px">$1</h2>`)
    // h1
    .replace(/^# (.+)$/gm, `<h1 style="color:#f4f4f5;font-size:16px;font-weight:700;margin:20px 0 10px 0">$1</h1>`)
    // numbered list
    .replace(/^(\d+)\. (.+)$/gm, `<div style="padding:3px 0 3px 0;color:#e4e4e7;display:flex;gap:8px"><span style="color:#7c3aed;flex-shrink:0">$1.</span><span>$2</span></div>`)
    // bullet list
    .replace(/^[-*] (.+)$/gm, `<div style="padding:3px 0 3px 16px;color:#e4e4e7;position:relative"><span style="position:absolute;left:4px;color:#7c3aed">•</span>$1</div>`)
    // blockquote
    .replace(/^> (.+)$/gm, `<div style="border-left:3px solid #7c3aed;padding:6px 12px;margin:6px 0;color:#a1a1aa;font-style:italic">$1</div>`)
    // double newlines → paragraph break
    .replace(/\n\n/g, `<div style="height:10px"></div>`)
    // single newlines
    .replace(/\n/g, `<br/>`);
}

function MarkdownMessage({ content }: { content: string }) {
  return (
    <div
      style={{ lineHeight: 1.75, color: "#e4e4e7", fontSize: 13 }}
      dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
    />
  );
}

// ── App ───────────────────────────────────────────────────────────────────────
export default function App() {
  const [view, setView] = useState<View>("chat");
  return (
    <div style={{ display: "flex", height: "100vh", background: "#09090b", color: "#f4f4f5", fontFamily: "monospace", fontSize: 13 }}>
      <aside style={{ width: 190, borderRight: "1px solid #27272a", display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div style={{ padding: "14px 16px", borderBottom: "1px solid #27272a", fontWeight: 700, fontSize: 14 }}>
          PrepAI
          <span style={{ fontSize: 9, color: "#71717a", border: "1px solid #3f3f46", padding: "1px 5px", borderRadius: 4, marginLeft: 6 }}>local</span>
        </div>
        <nav style={{ padding: "8px" }}>
          {([
            ["chat",     "💬 Chat"],
            ["progress", "📈 My Progress"],
            ["revision", "🔁 Revision Qs"],
            ["patterns", "🔍 Pattern Gaps"],
            ["star",     "⭐ STAR Scorer"],
          ] as [View, string][]).map(([id, label]) => (
            <button key={id} onClick={() => setView(id)} style={{
              display: "block", width: "100%", textAlign: "left",
              padding: "8px 10px", borderRadius: 6, border: "none",
              cursor: "pointer", fontSize: 12, marginBottom: 2,
              background: view === id ? "#27272a" : "transparent",
              color: view === id ? "#f4f4f5" : "#71717a",
            }}>{label}</button>
          ))}
        </nav>
      </aside>
      <main style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "hidden" }}>
        {view === "chat"     && <ChatView />}
        {view === "progress" && <ProgressView />}
        {view === "revision" && <RevisionView />}
        {view === "patterns" && <PatternGapsView />}
        {view === "star"     && <StarView />}
      </main>
    </div>
  );
}

// ── Chat ──────────────────────────────────────────────────────────────────────
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

  function newSession() {
    setSessionId(undefined); setMessages([]);
    inputRef.current?.focus();
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading) return;
    setInput(""); setLoading(true);
    setMessages(prev => [...prev, { id: crypto.randomUUID(), role: "user", content: text }]);
    try {
      const r = await fetch(`${BASE}/chat/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: text,
          topic: topic || undefined,
          mode,
          use_rag: true,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setSessionId(d.session_id);
      setMessages(prev => [...prev, { id: d.message.id, role: "assistant", content: d.message.content }]);
      fetchSessions();
    } catch (e: any) {
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(), role: "assistant",
        content: `**Error:** ${e.message}\n\nMake sure the backend is running on port 8000.`,
      }]);
    } finally { setLoading(false); inputRef.current?.focus(); }
  }

  const SUGGESTIONS = [
    ["What DSA patterns have I covered? Give gist of each.", "dsa"],
    ["What should I study today?", ""],
    ["What Java/Spring topics have I covered? Explain each briefly.", "java"],
    ["What are my weak areas across all topics?", ""],
    ["Explain Two Pointers pattern with mental model.", "dsa"],
    ["What AWS services have I learned? Key use cases.", "aws"],
  ];

  return (
    <div style={{ display: "flex", flex: 1, minWidth: 0, overflow: "hidden" }}>
      {/* Sessions */}
      <div style={{ width: 200, borderRight: "1px solid #27272a", display: "flex", flexDirection: "column", flexShrink: 0 }}>
        <div style={{ padding: "8px" }}>
          <button onClick={newSession} style={{ width: "100%", padding: "7px 10px", background: "transparent", border: "1px solid #3f3f46", color: "#a1a1aa", borderRadius: 6, cursor: "pointer", fontSize: 11 }}>+ New session</button>
        </div>
        <div style={{ flex: 1, overflowY: "auto" }}>
          {sessions.length === 0 && <p style={{ color: "#52525b", fontSize: 11, padding: "12px", textAlign: "center" }}>No sessions yet</p>}
          {sessions.map(s => (
            <div key={s.id} onClick={() => loadSession(s.id)} style={{
              padding: "8px 10px", cursor: "pointer", fontSize: 11,
              borderBottom: "1px solid #18181b",
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

      {/* Main chat area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {/* Toolbar */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 16px", borderBottom: "1px solid #27272a" }}>
          <select value={topic} onChange={e => setTopic(e.target.value)} style={{ background: "#18181b", border: "1px solid #3f3f46", color: "#d4d4d8", borderRadius: 6, padding: "4px 8px", fontSize: 11, cursor: "pointer" }}>
            <option value="">All topics</option>
            {Object.entries(TOPIC_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <div style={{ display: "flex", border: "1px solid #3f3f46", borderRadius: 6, overflow: "hidden" }}>
            {(["chat", "interview"] as Mode[]).map(m => (
              <button key={m} onClick={() => setMode(m)} style={{
                padding: "4px 10px", fontSize: 11, border: "none", cursor: "pointer",
                textTransform: "capitalize",
                background: mode === m ? "#3f3f46" : "transparent",
                color: mode === m ? "#f4f4f5" : "#71717a",
              }}>{m}</button>
            ))}
          </div>
          <span style={{ marginLeft: "auto", fontSize: 10, color: "#3f3f46" }}>progress Qs → DB · knowledge Qs → RAG</span>
        </div>

        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px 24px 12px", display: "flex", flexDirection: "column", gap: 20 }}>
          {messages.length === 0 && !loading && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", gap: 14 }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ color: "#f4f4f5", fontSize: 15, fontWeight: 600, marginBottom: 4 }}>PrepAI</div>
                <div style={{ color: "#52525b", fontSize: 12 }}>Personal Interview Preparation OS · Everything runs locally</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, width: "100%", maxWidth: 520 }}>
                {SUGGESTIONS.map(([q, t]) => (
                  <button key={q as string} onClick={() => {
                    setInput(q as string);
                    if (t) setTopic(t as string);
                    setTimeout(() => inputRef.current?.focus(), 50);
                  }} style={{
                    background: "#18181b", border: "1px solid #27272a", borderRadius: 8,
                    padding: "10px 12px", fontSize: 11, color: "#a1a1aa",
                    cursor: "pointer", textAlign: "left", lineHeight: 1.5,
                  }}>{q}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => (
            <div key={msg.id} style={{ display: "flex", gap: 12, flexDirection: msg.role === "user" ? "row-reverse" : "row", alignItems: "flex-start" }}>
              <div style={{
                width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
                background: msg.role === "user" ? "#3f3f46" : "#4c1d95",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 10, fontWeight: 700, color: "#f4f4f5", marginTop: 2,
              }}>{msg.role === "user" ? "U" : "AI"}</div>

              {msg.role === "user" ? (
                <div style={{
                  maxWidth: "72%", background: "#27272a", borderRadius: 10,
                  padding: "10px 14px", color: "#e4e4e7", lineHeight: 1.6,
                  wordBreak: "break-word", fontSize: 13,
                }}>{msg.content}</div>
              ) : (
                <div style={{ flex: 1, maxWidth: "88%", minWidth: 0 }}>
                  <MarkdownMessage content={msg.content} />
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div style={{ display: "flex", gap: 12 }}>
              <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#4c1d95", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#f4f4f5" }}>AI</div>
              <div style={{ paddingTop: 6, color: "#71717a", fontSize: 12 }}>Thinking — this may take 20-40s for detailed answers…</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div style={{ padding: "0 16px 16px" }}>
          <div style={{ border: "1px solid #3f3f46", borderRadius: 10, background: "#18181b" }}>
            <textarea
              ref={inputRef} value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
              placeholder="Ask anything — topics covered, patterns, revision, design problems…"
              rows={3}
              style={{ background: "transparent", border: "none", outline: "none", padding: "12px 14px 6px", color: "#f4f4f5", resize: "none", fontFamily: "monospace", fontSize: 13, lineHeight: 1.6, width: "100%", boxSizing: "border-box" }}
            />
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 10px 10px" }}>
              <span style={{ fontSize: 10, color: "#52525b" }}>↵ send · shift+↵ newline · detailed answers may take ~30s</span>
              <button onClick={sendMessage} disabled={!input.trim() || loading} style={{
                padding: "6px 16px", borderRadius: 6, fontSize: 12, fontWeight: 600,
                background: input.trim() && !loading ? "#7c3aed" : "#27272a",
                color: input.trim() && !loading ? "#fff" : "#52525b",
                border: "none", cursor: input.trim() && !loading ? "pointer" : "not-allowed",
              }}>Send</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Progress ──────────────────────────────────────────────────────────────────
function ProgressView() {
  const [dsa, setDsa] = useState<any>(null);
  const [mastery, setMastery] = useState<any>({});
  const [today, setToday] = useState<any>(null);
  const [weaknesses, setWeaknesses] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${BASE}/progress/dsa`).then(r => r.json()).catch(() => ({})),
      fetch(`${BASE}/progress/mastery`).then(r => r.json()).catch(() => ({})),
      fetch(`${BASE}/progress/today`).then(r => r.json()).catch(() => ({})),
      fetch(`${BASE}/progress/weaknesses`).then(r => r.json()).catch(() => ({})),
    ]).then(([d, m, t, w]) => {
      setDsa(d); setMastery(m); setToday(t); setWeaknesses(w);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <Center>Loading progress…</Center>;

  const patterns = dsa?.patterns_covered || {};
  const missing = dsa?.missing_patterns || [];
  const difficulty = dsa?.difficulty_breakdown || {};
  const hasMastery = Object.keys(mastery).length > 0;

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1 }}>
      <h2 style={{ color: "#f4f4f5", fontWeight: 700, margin: "0 0 20px 0" }}>📈 My Progress</h2>

      {/* Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
        {[
          ["DSA Problems", dsa?.total_problems ?? 0],
          ["Patterns Covered", Object.keys(patterns).length],
          ["Topics Tracked", Object.values(mastery as Record<string,any>).reduce((s: number, d: any) => s + (d.topic_count || 0), 0)],
          ["Missing Patterns", missing.length],
        ].map(([label, value]) => (
          <div key={label as string} style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: "14px 16px" }}>
            <div style={{ color: "#71717a", fontSize: 11, marginBottom: 4 }}>{label}</div>
            <div style={{ color: "#f4f4f5", fontSize: 22, fontWeight: 700 }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Today's plan */}
      {today?.recommendations?.length > 0 && (
        <div style={{ background: "#0f172a", border: "1px solid #1e3a5f", borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <div style={{ color: "#7dd3fc", fontWeight: 600, marginBottom: 12, fontSize: 12 }}>
            📋 Study Today — {today.pattern_coverage} DSA coverage
          </div>
          {today.recommendations.map((r: any, i: number) => (
            <div key={i} style={{ marginBottom: 10, paddingBottom: 10, borderBottom: i < today.recommendations.length - 1 ? "1px solid #1e3a5f" : "none" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 3 }}>
                <span style={{ fontSize: 10, background: TOPIC_COLORS[r.topic] || "#3f3f46", color: "#fff", padding: "1px 6px", borderRadius: 4, flexShrink: 0 }}>
                  {TOPIC_LABELS[r.topic] || r.topic || "general"}
                </span>
                <span style={{ color: "#f4f4f5", fontSize: 12 }}>{r.action}</span>
              </div>
              <div style={{ color: "#52525b", fontSize: 10, marginLeft: 0 }}>{r.reason}</div>
            </div>
          ))}
        </div>
      )}

      {/* Multi-topic mastery */}
      {hasMastery ? (
        <div style={{ marginBottom: 16 }}>
          <div style={{ color: "#a1a1aa", fontWeight: 600, fontSize: 12, marginBottom: 10 }}>📚 Topic Mastery from your KB notes</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {Object.entries(mastery as Record<string,any>).map(([cat, data]: any) => (
              <div key={cat} style={{ background: "#18181b", border: `1px solid ${TOPIC_COLORS[cat] || "#27272a"}40`, borderRadius: 8, padding: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                  <span style={{ color: TOPIC_COLORS[cat] || "#a1a1aa", fontWeight: 600, fontSize: 12 }}>{TOPIC_LABELS[cat] || cat}</span>
                  <span style={{ fontSize: 11, color: "#71717a" }}>{data.topic_count} topics · {data.avg_mastery}/5</span>
                </div>
                <div style={{ height: 4, background: "#27272a", borderRadius: 2, marginBottom: 10 }}>
                  <div style={{ height: "100%", width: `${(data.avg_mastery / 5) * 100}%`, background: TOPIC_COLORS[cat] || "#7c3aed", borderRadius: 2 }} />
                </div>
                {data.strong_topics?.length > 0 && <div style={{ fontSize: 10, color: "#86efac", marginBottom: 3 }}>✓ {data.strong_topics.slice(0, 4).join(", ")}</div>}
                {data.weak_topics?.length > 0 && <div style={{ fontSize: 10, color: "#fca5a5" }}>✗ {data.weak_topics.slice(0, 3).join(", ")}</div>}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <div style={{ color: "#71717a", fontSize: 12 }}>
            No topic mastery data yet. Add your KB markdown files to <code style={{ color: "#c4b5fd" }}>data/notes/</code> and re-run ingestion.
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
          <div style={{ color: "#4ade80", fontWeight: 600, marginBottom: 10, fontSize: 12 }}>✅ DSA Patterns</div>
          {Object.keys(patterns).length === 0 && <p style={{ color: "#52525b", fontSize: 11 }}>No patterns detected yet.</p>}
          {Object.entries(patterns).sort((a: any, b: any) => b[1] - a[1]).map(([p, c]: any) => (
            <div key={p} style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 12 }}>
              <span style={{ color: "#86efac" }}>{p}</span>
              <span style={{ color: "#4ade80", fontWeight: 600 }}>{c}×</span>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
            <div style={{ color: "#a1a1aa", fontWeight: 600, marginBottom: 10, fontSize: 12 }}>Difficulty</div>
            {Object.entries(difficulty).map(([d, c]: any) => {
              const col = d === "Easy" ? "#4ade80" : d === "Medium" ? "#fbbf24" : "#f87171";
              return (
                <div key={d} style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 12 }}>
                  <span style={{ color: col }}>{d}</span>
                  <span style={{ color: col, fontWeight: 600 }}>{c}</span>
                </div>
              );
            })}
            {Object.keys(difficulty).length === 0 && <p style={{ color: "#52525b", fontSize: 11 }}>No data</p>}
          </div>

          {weaknesses?.kb_weaknesses?.length > 0 && (
            <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
              <div style={{ color: "#f87171", fontWeight: 600, marginBottom: 10, fontSize: 12 }}>⚠️ Weaknesses</div>
              {weaknesses.kb_weaknesses.slice(0, 4).map((w: any, i: number) => (
                <div key={i} style={{ fontSize: 11, color: "#fca5a5", marginBottom: 4 }}>• {w.weakness}</div>
              ))}
            </div>
          )}
        </div>
      </div>

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

// ── Revision Questions ────────────────────────────────────────────────────────
function RevisionView() {
  const [topic, setTopic] = useState("dsa");
  const [count, setCount] = useState(5);
  const [questions, setQuestions] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [revealed, setRevealed] = useState<Set<number>>(new Set());
  const [showAnswer, setShowAnswer] = useState<Set<number>>(new Set());
  const [error, setError] = useState("");

  async function generate() {
    setLoading(true); setQuestions([]); setRevealed(new Set()); setShowAnswer(new Set()); setError("");
    try {
      const r = await fetch(`${BASE}/analysis/revision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic, count }),
      });
      if (!r.ok) {
        const e = await r.json();
        setError(e.detail || "Failed to generate questions");
        return;
      }
      const d = await r.json();
      setQuestions(d.questions || []);
      if ((d.questions || []).length === 0) setError("No questions generated. Check your notes are ingested.");
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }

  const dc = (d: string) => d === "easy" ? "#4ade80" : d === "hard" ? "#f87171" : "#fbbf24";

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1 }}>
      <h2 style={{ color: "#f4f4f5", fontWeight: 700, margin: "0 0 8px 0" }}>🔁 Revision Questions</h2>
      <p style={{ color: "#71717a", fontSize: 12, marginBottom: 16 }}>
        Senior-level questions generated from your personal knowledge base. Not generic — grounded in what you've actually studied.
      </p>

      <div style={{ display: "flex", gap: 10, marginBottom: 20, alignItems: "center" }}>
        <select value={topic} onChange={e => setTopic(e.target.value)} style={{ background: "#18181b", border: "1px solid #3f3f46", color: "#d4d4d8", borderRadius: 6, padding: "6px 10px", fontSize: 12, cursor: "pointer" }}>
          {Object.entries(TOPIC_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select value={count} onChange={e => setCount(Number(e.target.value))} style={{ background: "#18181b", border: "1px solid #3f3f46", color: "#d4d4d8", borderRadius: 6, padding: "6px 10px", fontSize: 12, cursor: "pointer" }}>
          {[3, 5, 8, 10].map(n => <option key={n} value={n}>{n} questions</option>)}
        </select>
        <button onClick={generate} disabled={loading} style={{ padding: "6px 18px", background: "#7c3aed", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600 }}>
          {loading ? "Generating (30-60s)…" : "Generate"}
        </button>
      </div>

      {error && <div style={{ color: "#f87171", fontSize: 12, marginBottom: 12, background: "#18181b", padding: "8px 12px", borderRadius: 6 }}>⚠️ {error}</div>}
      {questions.length === 0 && !loading && !error && <p style={{ color: "#52525b", fontSize: 12 }}>Click Generate to create interview-level questions from your notes.</p>}

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {questions.map((q, i) => (
          <div key={i} style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 10, padding: 18 }}>
            <div style={{ display: "flex", gap: 8, marginBottom: 10, alignItems: "center" }}>
              <span style={{ fontSize: 10, background: TOPIC_COLORS[q.topic] || "#27272a", color: "#fff", padding: "2px 8px", borderRadius: 4 }}>
                {TOPIC_LABELS[q.topic] || q.topic}
              </span>
              <span style={{ fontSize: 10, color: dc(q.difficulty), border: `1px solid ${dc(q.difficulty)}40`, padding: "1px 6px", borderRadius: 4 }}>
                {q.difficulty}
              </span>
              <span style={{ fontSize: 11, color: "#52525b", marginLeft: "auto" }}>Q{i + 1}</span>
            </div>

            <div style={{ color: "#f4f4f5", fontSize: 13, lineHeight: 1.7, marginBottom: 12 }}>{q.question}</div>

            <div style={{ display: "flex", gap: 8 }}>
              {!revealed.has(i) ? (
                <button onClick={() => setRevealed(prev => new Set([...prev, i]))} style={{ background: "transparent", border: "1px solid #3f3f46", color: "#71717a", borderRadius: 6, padding: "4px 12px", fontSize: 11, cursor: "pointer" }}>
                  Show hint
                </button>
              ) : (
                <div style={{ background: "#0f172a", border: "1px solid #1e3a5f", borderRadius: 6, padding: "8px 12px", fontSize: 12, color: "#7dd3fc", flex: 1 }}>
                  💡 <strong>Hint:</strong> {q.hint}
                </div>
              )}
              {q.expected_answer_points?.length > 0 && (
                <button onClick={() => setShowAnswer(prev => {
                  const n = new Set([...prev]); n.has(i) ? n.delete(i) : n.add(i); return n;
                })} style={{ background: "transparent", border: "1px solid #3f3f46", color: "#71717a", borderRadius: 6, padding: "4px 12px", fontSize: 11, cursor: "pointer" }}>
                  {showAnswer.has(i) ? "Hide answer points" : "Show answer points"}
                </button>
              )}
            </div>

            {showAnswer.has(i) && q.expected_answer_points?.length > 0 && (
              <div style={{ marginTop: 10, background: "#14532d20", border: "1px solid #166534", borderRadius: 6, padding: "10px 14px" }}>
                <div style={{ fontSize: 11, color: "#4ade80", marginBottom: 6, fontWeight: 600 }}>Expected answer points:</div>
                {q.expected_answer_points.map((p: string, j: number) => (
                  <div key={j} style={{ fontSize: 12, color: "#86efac", marginBottom: 4 }}>• {p}</div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
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
  if (!data) return <Center>No data. Run ingestion first.</Center>;

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
            <div key={p} style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: 12 }}>
              <span style={{ color: "#86efac" }}>{p}</span>
              <span style={{ color: "#4ade80" }}>{c} solutions</span>
            </div>
          ))}
          {Object.keys(data.covered_patterns || {}).length === 0 && <p style={{ color: "#52525b", fontSize: 11 }}>No patterns detected. Add DSA solution files and re-ingest.</p>}
        </div>
        <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16 }}>
          <div style={{ color: "#f87171", fontWeight: 600, marginBottom: 12, fontSize: 12 }}>❌ Missing ({(data.missing_patterns || []).length})</div>
          {(data.missing_patterns || []).map((p: string) => (
            <div key={p} style={{ color: "#fca5a5", fontSize: 12, marginBottom: 6 }}>• {p}</div>
          ))}
        </div>
        {Object.keys(data.weak_patterns || {}).length > 0 && (
          <div style={{ background: "#18181b", border: "1px solid #27272a", borderRadius: 8, padding: 16, gridColumn: "1 / -1" }}>
            <div style={{ color: "#fbbf24", fontWeight: 600, marginBottom: 10, fontSize: 12 }}>⚠️ Thin Coverage — only 1 solution each</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {Object.keys(data.weak_patterns).map((p: string) => (
                <span key={p} style={{ background: "#27272a", color: "#fde68a", padding: "3px 8px", borderRadius: 4, fontSize: 11 }}>{p}</span>
              ))}
            </div>
          </div>
        )}
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
  const [error, setError] = useState("");

  async function score() {
    if (!question.trim() || !answer.trim() || loading) return;
    setLoading(true); setResult(null); setError("");
    try {
      const r = await fetch(`${BASE}/analysis/star`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, answer }),
      });
      if (!r.ok) {
        const e = await r.json();
        setError(e.detail || `HTTP ${r.status}`);
        return;
      }
      const d = await r.json();
      if (d.error) { setError(d.error); return; }
      setResult(d);
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  }

  const sc = (n: number) => n >= 4 ? "#4ade80" : n >= 3 ? "#fbbf24" : "#f87171";

  return (
    <div style={{ padding: 24, overflowY: "auto", flex: 1, maxWidth: 800 }}>
      <h2 style={{ color: "#f4f4f5", fontWeight: 700, margin: "0 0 6px 0" }}>⭐ STAR Answer Scorer</h2>
      <p style={{ color: "#71717a", fontSize: 12, marginBottom: 20 }}>Strict scoring for a 6-year senior engineer. Generic answers score 2-3 even if structured correctly.</p>

      <label style={{ fontSize: 11, color: "#71717a", display: "block", marginBottom: 4 }}>Behavioral question</label>
      <input
        value={question} onChange={e => setQuestion(e.target.value)}
        placeholder="e.g. Tell me about a time you handled a production incident"
        style={{ width: "100%", background: "#18181b", border: "1px solid #3f3f46", color: "#f4f4f5", borderRadius: 6, padding: "9px 12px", fontSize: 12, fontFamily: "monospace", boxSizing: "border-box", marginBottom: 14 }}
      />

      <label style={{ fontSize: 11, color: "#71717a", display: "block", marginBottom: 4 }}>Your STAR answer</label>
      <textarea
        value={answer} onChange={e => setAnswer(e.target.value)}
        placeholder={"Situation: [context]\nTask: [your responsibility]\nAction: [what you did specifically]\nResult: [measurable outcome]"}
        rows={8}
        style={{ width: "100%", background: "#18181b", border: "1px solid #3f3f46", color: "#f4f4f5", borderRadius: 6, padding: "9px 12px", fontSize: 12, fontFamily: "monospace", resize: "vertical", boxSizing: "border-box", marginBottom: 14, lineHeight: 1.6 }}
      />

      <button onClick={score} disabled={loading || !question.trim() || !answer.trim()} style={{
        padding: "9px 24px", background: "#7c3aed", color: "#fff",
        border: "none", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600,
        opacity: loading || !question.trim() || !answer.trim() ? 0.5 : 1,
      }}>
        {loading ? "Scoring (20-40s)…" : "Score my answer"}
      </button>

      {error && (
        <div style={{ marginTop: 16, background: "#18181b", border: "1px solid #f87171", borderRadius: 8, padding: "12px 16px", color: "#f87171", fontSize: 12 }}>
          ⚠️ {error}
        </div>
      )}

      {result && (
        <div style={{ marginTop: 20, background: "#18181b", border: "1px solid #27272a", borderRadius: 10, padding: 20 }}>
          {/* Scores */}
          <div style={{ display: "flex", gap: 20, marginBottom: 16, flexWrap: "wrap" }}>
            {[
              ["Overall", result.score],
              ["Situation", result.situation_score],
              ["Task", result.task_score],
              ["Action", result.action_score],
              ["Result", result.result_score],
            ].map(([l, v]: any) => (
              <div key={l} style={{ textAlign: "center" }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: sc(v) }}>{v ?? "?"}/5</div>
                <div style={{ fontSize: 10, color: "#71717a", marginTop: 2 }}>{l}</div>
              </div>
            ))}
          </div>

          <div style={{ color: "#fbbf24", marginBottom: 12, fontSize: 13, fontWeight: 500 }}>{result.verdict}</div>

          {result.strengths?.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ color: "#4ade80", fontSize: 11, fontWeight: 600, marginBottom: 6 }}>Strengths</div>
              {result.strengths.map((s: string, i: number) => (
                <div key={i} style={{ color: "#86efac", fontSize: 12, marginBottom: 4 }}>• {s}</div>
              ))}
            </div>
          )}

          {result.missing?.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ color: "#f87171", fontSize: 11, fontWeight: 600, marginBottom: 6 }}>Missing</div>
              {result.missing.map((m: string, i: number) => (
                <div key={i} style={{ color: "#fca5a5", fontSize: 12, marginBottom: 4 }}>• {m}</div>
              ))}
            </div>
          )}

          {result.improved_answer_hint && (
            <div style={{ background: "#0f172a", border: "1px solid #1e3a5f", borderRadius: 6, padding: "10px 14px", fontSize: 12, color: "#7dd3fc", marginTop: 4 }}>
              💡 <strong>To score 5/5:</strong> {result.improved_answer_hint}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1, color: "#52525b", fontSize: 13 }}>
      {children}
    </div>
  );
}
