"use client";
import { useState, useEffect, useRef } from "react";

const BASE = "http://localhost:8001/api";
const INTERVIEW_STORAGE_KEY = "prepai_interview_v1";
const REVISION_STORAGE_KEY  = "prepai_revision_v1";

const TOPIC_LABELS: Record<string,string> = {
  dsa:"DSA", system_design:"System Design", java:"Java",
  python:"Python", aws:"AWS", behavioral:"Behavioral",
  projects:"Projects", general:"General",
};
const TOPIC_COLORS: Record<string,string> = {
  dsa:"#7c3aed", system_design:"#0ea5e9", java:"#f97316",
  python:"#10b981", aws:"#f59e0b", behavioral:"#ec4899",
  projects:"#06b6d4", general:"#6b7280",
};

type View = "mock_interview"|"chat"|"resume"|"stories"|"revision"|"progress"|"patterns"|"star";

// ── sessionStorage helpers ────────────────────────────────────────────────────
function ssGet<T>(key: string, fallback: T): T {
  try { const v = sessionStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
}
function ssSet(key: string, val: unknown) {
  try { sessionStorage.setItem(key, JSON.stringify(val)); } catch {}
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
function esc(s: string) { return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function renderMD(t: string): string {
  return t
    .replace(/```(\w*)\n?([\s\S]*?)```/g, (_,_l,c) =>
      `<pre style="background:#18181b;border:1px solid #3f3f46;border-radius:8px;padding:14px;overflow-x:auto;margin:10px 0"><code style="color:#e4e4e7;font-size:12px;font-family:monospace;line-height:1.6">${esc(c.trim())}</code></pre>`)
    .replace(/`([^`\n]+)`/g, `<code style="background:#27272a;color:#c4b5fd;padding:1px 6px;border-radius:4px;font-size:12px;font-family:monospace">$1</code>`)
    .replace(/\*\*(.+?)\*\*/g, `<strong style="color:#f4f4f5">$1</strong>`)
    .replace(/\*(.+?)\*/g, `<em style="color:#d4d4d8">$1</em>`)
    .replace(/^### (.+)$/gm, `<h3 style="color:#f4f4f5;font-size:13px;font-weight:600;margin:14px 0 6px;border-bottom:1px solid #27272a;padding-bottom:4px">$1</h3>`)
    .replace(/^## (.+)$/gm, `<h2 style="color:#f4f4f5;font-size:14px;font-weight:700;margin:16px 0 8px">$1</h2>`)
    .replace(/^(\d+)\. (.+)$/gm, `<div style="padding:2px 0;color:#e4e4e7;display:flex;gap:8px"><span style="color:#7c3aed;flex-shrink:0">$1.</span><span>$2</span></div>`)
    .replace(/^[-*] (.+)$/gm, `<div style="padding:2px 0 2px 14px;color:#e4e4e7;position:relative"><span style="position:absolute;left:4px;color:#7c3aed">•</span>$1</div>`)
    .replace(/\n\n/g, `<div style="height:8px"></div>`)
    .replace(/\n/g, `<br/>`);
}
function MD({ content }: { content: string }) {
  return <div style={{ lineHeight:1.75, color:"#e4e4e7", fontSize:13 }} dangerouslySetInnerHTML={{ __html: renderMD(content) }} />;
}

// ── App — keeps ALL views mounted, just shows/hides ───────────────────────────
// This is the KEY fix: views are never unmounted so state is never lost
export default function App() {
  const [view, setView] = useState<View>("mock_interview");
  const NAV: [View, string][] = [
    ["mock_interview", "🎯 Mock Interview"],
    ["chat",          "💬 Chat"],
    ["resume",        "📄 Resume"],
    ["stories",       "📖 Story Bank"],
    ["revision",      "🔁 Revision Qs"],
    ["progress",      "📈 Progress"],
    ["patterns",      "🔍 Patterns"],
    ["star",          "⭐ STAR Scorer"],
  ];
  return (
    <div style={{ display:"flex", height:"100vh", background:"#09090b", color:"#f4f4f5", fontFamily:"monospace", fontSize:13 }}>
      <aside style={{ width:190, borderRight:"1px solid #27272a", display:"flex", flexDirection:"column", flexShrink:0 }}>
        <div style={{ padding:"14px 16px", borderBottom:"1px solid #27272a", fontWeight:700, fontSize:14 }}>
          PrepAI <span style={{ fontSize:9, color:"#71717a", border:"1px solid #3f3f46", padding:"1px 5px", borderRadius:4, marginLeft:6 }}>local</span>
        </div>
        <nav style={{ padding:"8px", overflowY:"auto" }}>
          {NAV.map(([id, label]) => (
            <button key={id} onClick={() => setView(id)} style={{
              display:"block", width:"100%", textAlign:"left", padding:"8px 10px",
              borderRadius:6, border:"none", cursor:"pointer", fontSize:12, marginBottom:2,
              background: view === id ? "#27272a" : "transparent",
              color: view === id ? "#f4f4f5" : "#71717a",
            }}>{label}</button>
          ))}
        </nav>
      </aside>
      <main style={{ flex:1, display:"flex", flexDirection:"column", minWidth:0, overflow:"hidden", position:"relative" }}>
        {/* All views mounted simultaneously — display:none hides inactive ones */}
        <div style={{ display: view === "mock_interview" ? "flex" : "none", flex:1, flexDirection:"column", minWidth:0, overflow:"hidden" }}>
          <MockInterviewView />
        </div>
        <div style={{ display: view === "chat" ? "flex" : "none", flex:1, flexDirection:"column", minWidth:0, overflow:"hidden" }}>
          <ChatView />
        </div>
        <div style={{ display: view === "resume" ? "flex" : "none", flex:1, flexDirection:"column", overflow:"hidden" }}>
          <ResumeView />
        </div>
        <div style={{ display: view === "stories" ? "flex" : "none", flex:1, flexDirection:"column", overflow:"hidden" }}>
          <StoryBankView />
        </div>
        <div style={{ display: view === "revision" ? "flex" : "none", flex:1, flexDirection:"column", overflow:"hidden" }}>
          <RevisionView />
        </div>
        <div style={{ display: view === "progress" ? "flex" : "none", flex:1, flexDirection:"column", overflow:"hidden" }}>
          <ProgressView />
        </div>
        <div style={{ display: view === "patterns" ? "flex" : "none", flex:1, flexDirection:"column", overflow:"hidden" }}>
          <PatternGapsView />
        </div>
        <div style={{ display: view === "star" ? "flex" : "none", flex:1, flexDirection:"column", overflow:"hidden" }}>
          <StarView />
        </div>
      </main>
    </div>
  );
}

// ── MOCK INTERVIEW ────────────────────────────────────────────────────────────
const PERSONAS = [
  { id:"dsa",           label:"DSA",           desc:"LeetCode-style. One problem at a time. Edge cases + complexity.", color:"#7c3aed" },
  { id:"system_design", label:"System Design",  desc:"Requirements → components → trade-offs. Senior-level.", color:"#0ea5e9" },
  { id:"java",          label:"Java Backend",   desc:"Spring, JVM, concurrency, production scenarios.", color:"#f97316" },
  { id:"python",        label:"Python/Spark",   desc:"PySpark, pipelines, window functions, Delta Lake.", color:"#10b981" },
  { id:"aws",           label:"AWS",            desc:"Architecture decisions, service selection, failure modes.", color:"#f59e0b" },
  { id:"behavioral",    label:"Behavioral",     desc:"STAR-format. Uses story bank. Scores every answer.", color:"#ec4899" },
];

interface IVMsg { role:"interviewer"|"candidate"; content:string; score?:number; }
interface IVState {
  phase:"select"|"active"|"ended";
  sessionId:string|null;
  topic:string;
  difficulty:string;
  messages:IVMsg[];
  report:any|null;
}
const IV_DEFAULT: IVState = { phase:"select", sessionId:null, topic:"", difficulty:"medium", messages:[], report:null };

function MockInterviewView() {
  const [iv, setIv] = useState<IVState>(() => ssGet(INTERVIEW_STORAGE_KEY, IV_DEFAULT));
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingReport, setLoadingReport] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLTextAreaElement>(null);

  function saveIv(next: IVState) { setIv(next); ssSet(INTERVIEW_STORAGE_KEY, next); }
  function patch(p: Partial<IVState>) { setIv(prev => { const n = {...prev,...p}; ssSet(INTERVIEW_STORAGE_KEY,n); return n; }); }

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior:"smooth" }); }, [iv.messages, loading]);

  async function startInterview(topic: string) {
    setLoading(true);
    try {
      const d = await fetch(`${BASE}/interview/start`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ topic, difficulty: iv.difficulty }),
      }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });
      patch({ phase:"active", topic, sessionId:d.session_id, messages:[{ role:"interviewer", content:d.question }], report:null });
    } catch(e:any) { alert(`Failed: ${e.message}`); }
    finally { setLoading(false); }
  }

  async function submitAnswer() {
    const text = input.trim();
    if (!text || loading || !iv.sessionId) return;
    setInput(""); setLoading(true);
    const withUser: IVMsg[] = [...iv.messages, { role:"candidate", content:text }];
    patch({ messages: withUser });
    try {
      const d = await fetch(`${BASE}/interview/answer`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ session_id:iv.sessionId, answer:text }),
      }).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });
      const next: IVMsg[] = [
        ...withUser,
        { role:"interviewer", content:`**Score: ${d.score}/10**\n\n${d.feedback}`, score:d.score },
      ];
      if (d.next_question) {
        next.push({ role:"interviewer", content:`**Question ${d.question_number}:**\n\n${d.next_question}` });
        patch({ messages:next });
      } else {
        next.push({ role:"interviewer", content:"Interview complete. Click **Generate Report** for your full evaluation." });
        patch({ messages:next, phase:"ended" });
      }
    } catch(e:any) {
      patch({ messages:[...withUser, { role:"interviewer", content:`Error: ${e.message}` }] });
    } finally { setLoading(false); inputRef.current?.focus(); }
  }

  async function generateReport() {
    if (!iv.sessionId) return;
    setLoadingReport(true);
    try {
      const d = await fetch(`${BASE}/interview/report/${iv.sessionId}`, { method:"POST" }).then(r => r.json());
      patch({ report:d });
    } catch(e:any) { alert(`Report failed: ${e.message}`); }
    finally { setLoadingReport(false); }
  }

  function reset() { saveIv(IV_DEFAULT); setInput(""); }

  const persona = PERSONAS.find(p => p.id === iv.topic);
  const sc = (n:number) => n>=8?"#4ade80":n>=6?"#fbbf24":"#f87171";

  // ── Select screen ──
  if (iv.phase === "select") return (
    <div style={{ padding:28, overflowY:"auto", flex:1 }}>
      <h2 style={{ color:"#f4f4f5", fontWeight:700, margin:"0 0 8px 0" }}>🎯 Mock Interview</h2>
      <p style={{ color:"#71717a", fontSize:12, marginBottom:24 }}>
        Session auto-saves. Switch tabs freely — your interview will be here when you return.
      </p>
      <div style={{ marginBottom:20 }}>
        <div style={{ fontSize:11, color:"#71717a", marginBottom:8, fontWeight:600 }}>DIFFICULTY</div>
        <div style={{ display:"flex", gap:8 }}>
          {["easy","medium","hard"].map(d => {
            const col = d==="easy"?"#4ade80":d==="medium"?"#fbbf24":"#f87171";
            return (
              <button key={d} onClick={() => patch({ difficulty:d })} style={{
                padding:"6px 20px", borderRadius:6, fontSize:12, fontWeight:600, cursor:"pointer", textTransform:"capitalize",
                border:`1px solid ${iv.difficulty===d?col:"#3f3f46"}`,
                background: iv.difficulty===d ? `${col}20` : "transparent",
                color: iv.difficulty===d ? col : "#71717a",
              }}>{d}</button>
            );
          })}
        </div>
      </div>
      <div style={{ fontSize:11, color:"#71717a", marginBottom:10, fontWeight:600 }}>SELECT TYPE</div>
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
        {PERSONAS.map(p => (
          <button key={p.id} onClick={() => startInterview(p.id)} disabled={loading}
            style={{ background:"#18181b", border:`1px solid ${p.color}30`, borderRadius:10, padding:"16px 18px", cursor:"pointer", textAlign:"left" }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = p.color)}
            onMouseLeave={e => (e.currentTarget.style.borderColor = `${p.color}30`)}>
            <div style={{ color:p.color, fontWeight:700, fontSize:13, marginBottom:6 }}>{p.label}</div>
            <div style={{ color:"#71717a", fontSize:11, lineHeight:1.5 }}>{p.desc}</div>
            <div style={{ marginTop:10, fontSize:10, color:p.color }}>Start {iv.difficulty} →</div>
          </button>
        ))}
      </div>
      {loading && <div style={{ marginTop:16, color:"#71717a", fontSize:12 }}>Starting…</div>}
    </div>
  );

  // ── Active / Ended screen ──
  return (
    <div style={{ display:"flex", flex:1, minWidth:0, overflow:"hidden", flexDirection:"column" }}>
      {/* Header */}
      <div style={{ display:"flex", alignItems:"center", gap:10, padding:"10px 20px", borderBottom:"1px solid #27272a", flexShrink:0 }}>
        <div style={{ width:10, height:10, borderRadius:"50%", background:iv.phase==="active"?"#4ade80":"#f87171" }} />
        <span style={{ fontWeight:600, fontSize:12, color:"#f4f4f5" }}>{persona?.label} Interview</span>
        <span style={{ fontSize:11, color:"#71717a", border:"1px solid #3f3f46", padding:"1px 6px", borderRadius:4, textTransform:"capitalize" }}>{iv.difficulty}</span>
        <span style={{ fontSize:10, color:"#52525b" }}>{iv.messages.filter(m=>m.role==="candidate").length} answers</span>
        <span style={{ fontSize:10, color:"#3f3f46" }}>● auto-saved</span>
        <div style={{ marginLeft:"auto", display:"flex", gap:8 }}>
          {(iv.phase==="active"||iv.phase==="ended") && iv.messages.length>=4 && !iv.report && (
            <button onClick={generateReport} disabled={loadingReport} style={{ padding:"5px 14px", background:iv.phase==="ended"?"#7c3aed":"#1c1917", border:iv.phase==="ended"?"none":"1px solid #3f3f46", color:iv.phase==="ended"?"#fff":"#a8a29e", borderRadius:6, fontSize:11, cursor:"pointer", fontWeight:iv.phase==="ended"?600:400 }}>
              {loadingReport ? "Generating…" : "📊 Generate Report"}
            </button>
          )}
          <button onClick={reset} style={{ padding:"5px 14px", background:"transparent", border:"1px solid #3f3f46", color:"#71717a", borderRadius:6, fontSize:11, cursor:"pointer" }}>← New Interview</button>
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex:1, overflowY:"auto", padding:"20px 24px", display:"flex", flexDirection:"column", gap:16 }}>
        {iv.messages.map((msg, i) => (
          <div key={i} style={{ display:"flex", gap:12, flexDirection:msg.role==="candidate"?"row-reverse":"row", alignItems:"flex-start" }}>
            <div style={{
              width:30, height:30, borderRadius:"50%", flexShrink:0, marginTop:2,
              background: msg.role==="candidate" ? "#3f3f46" : persona?.color||"#4c1d95",
              display:"flex", alignItems:"center", justifyContent:"center", fontSize:10, fontWeight:700, color:"#fff",
            }}>{msg.role==="candidate"?"YOU":"IV"}</div>
            {msg.role==="candidate"
              ? <div style={{ maxWidth:"72%", background:"#27272a", borderRadius:10, padding:"10px 14px", color:"#e4e4e7", lineHeight:1.6, fontSize:13, wordBreak:"break-word" }}>{msg.content}</div>
              : <div style={{ flex:1, maxWidth:"88%" }}><MD content={msg.content} /></div>
            }
          </div>
        ))}
        {loading && (
          <div style={{ display:"flex", gap:12 }}>
            <div style={{ width:30, height:30, borderRadius:"50%", background:persona?.color||"#4c1d95", display:"flex", alignItems:"center", justifyContent:"center", fontSize:10, color:"#fff" }}>IV</div>
            <div style={{ paddingTop:6, color:"#71717a", fontSize:12 }}>Evaluating…</div>
          </div>
        )}
        {iv.report && !iv.report.error && (
          <div style={{ background:"#0f172a", border:"1px solid #1e3a5f", borderRadius:10, padding:20 }}>
            <div style={{ color:"#7dd3fc", fontWeight:700, fontSize:14, marginBottom:16 }}>📊 Interview Report</div>
            <div style={{ display:"grid", gridTemplateColumns:"repeat(5,1fr)", gap:10, marginBottom:16 }}>
              {[["Communication",iv.report.communication],["Technical",iv.report.technical_depth],["Trade-offs",iv.report.tradeoff_reasoning],["Problem Solving",iv.report.problem_solving],["Overall",iv.report.overall]].map(([l,v]:any)=>(
                <div key={l} style={{ textAlign:"center", background:"#0a0f1e", border:"1px solid #1e3a5f", borderRadius:8, padding:"10px 6px" }}>
                  <div style={{ fontSize:22, fontWeight:700, color:sc(v) }}>{v}/10</div>
                  <div style={{ fontSize:10, color:"#71717a", marginTop:2 }}>{l}</div>
                </div>
              ))}
            </div>
            {iv.report.strengths?.length>0 && <div style={{ marginBottom:12 }}><div style={{ color:"#4ade80", fontSize:11, fontWeight:600, marginBottom:6 }}>Strengths</div>{iv.report.strengths.map((s:string,i:number)=><div key={i} style={{ color:"#86efac", fontSize:12, marginBottom:4 }}>• {s}</div>)}</div>}
            {iv.report.weaknesses?.length>0 && <div style={{ marginBottom:12 }}><div style={{ color:"#f87171", fontSize:11, fontWeight:600, marginBottom:6 }}>Weaknesses</div>{iv.report.weaknesses.map((w:string,i:number)=><div key={i} style={{ color:"#fca5a5", fontSize:12, marginBottom:4 }}>• {w}</div>)}</div>}
            {iv.report.improvement_actions?.length>0 && <div><div style={{ color:"#fbbf24", fontSize:11, fontWeight:600, marginBottom:6 }}>Improvement Actions</div>{iv.report.improvement_actions.map((a:string,i:number)=><div key={i} style={{ color:"#fde68a", fontSize:12, marginBottom:4 }}>{i+1}. {a}</div>)}</div>}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      {iv.phase==="active" && (
        <div style={{ padding:"0 20px 20px", flexShrink:0 }}>
          <div style={{ border:`1px solid ${persona?.color||"#3f3f46"}50`, borderRadius:10, background:"#18181b" }}>
            <textarea ref={inputRef} value={input} onChange={e=>setInput(e.target.value)}
              onKeyDown={e=>{ if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); submitAnswer(); }}}
              placeholder="Type your answer… (↵ submit, shift+↵ newline)"
              rows={4} style={{ background:"transparent", border:"none", outline:"none", padding:"12px 14px 6px", color:"#f4f4f5", resize:"none", fontFamily:"monospace", fontSize:13, lineHeight:1.6, width:"100%", boxSizing:"border-box" }} />
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"0 12px 10px" }}>
              <span style={{ fontSize:10, color:"#52525b" }}>Session saved — switch tabs freely</span>
              <button onClick={submitAnswer} disabled={!input.trim()||loading} style={{
                padding:"6px 18px", borderRadius:6, fontSize:12, fontWeight:600, border:"none", cursor:input.trim()&&!loading?"pointer":"not-allowed",
                background: input.trim()&&!loading ? persona?.color||"#7c3aed" : "#27272a",
                color: input.trim()&&!loading ? "#fff" : "#52525b",
              }}>Submit</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── CHAT ──────────────────────────────────────────────────────────────────────
interface Msg { id:string; role:"user"|"assistant"; content:string; }
interface SessionSummary { id:string; title:string; topic?:string; message_count:number; }

function ChatView() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput]       = useState("");
  const [sessionId, setSessionId] = useState<string|undefined>();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [topic, setTopic]       = useState("");
  const [loading, setLoading]   = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef  = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { fetch(`${BASE}/chat/sessions`).then(r=>r.json()).then(setSessions).catch(()=>{}); }, []);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior:"smooth" }); }, [messages, loading]);

  async function loadSession(id: string) {
    const d = await fetch(`${BASE}/chat/sessions/${id}`).then(r=>r.json());
    setSessionId(d.id);
    setMessages(d.messages.map((m:any) => ({ id:m.id, role:m.role, content:m.content })));
  }

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput(""); setLoading(true);
    setMessages(prev => [...prev, { id:crypto.randomUUID(), role:"user", content:text }]);
    try {
      const d = await fetch(`${BASE}/chat/`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ session_id:sessionId, message:text, topic:topic||undefined, mode:"chat", use_rag:true }),
      }).then(r => { if(!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });
      setSessionId(d.session_id);
      setMessages(prev => [...prev, { id:d.message.id, role:"assistant", content:d.message.content }]);
      fetch(`${BASE}/chat/sessions`).then(r=>r.json()).then(setSessions).catch(()=>{});
    } catch(e:any) {
      setMessages(prev => [...prev, { id:crypto.randomUUID(), role:"assistant", content:`Error: ${e.message}` }]);
    } finally { setLoading(false); inputRef.current?.focus(); }
  }

  return (
    <div style={{ display:"flex", flex:1, minWidth:0, overflow:"hidden" }}>
      <div style={{ width:200, borderRight:"1px solid #27272a", display:"flex", flexDirection:"column", flexShrink:0 }}>
        <div style={{ padding:"8px" }}>
          <button onClick={() => { setSessionId(undefined); setMessages([]); }} style={{ width:"100%", padding:"7px 10px", background:"transparent", border:"1px solid #3f3f46", color:"#a1a1aa", borderRadius:6, cursor:"pointer", fontSize:11 }}>+ New session</button>
        </div>
        <div style={{ flex:1, overflowY:"auto" }}>
          {sessions.map(s => (
            <div key={s.id} onClick={() => loadSession(s.id)} style={{ padding:"8px 10px", cursor:"pointer", fontSize:11, borderBottom:"1px solid #18181b", background:sessionId===s.id?"#27272a":"transparent", color:sessionId===s.id?"#f4f4f5":"#a1a1aa" }}>
              <div style={{ overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{s.title}</div>
              <div style={{ fontSize:10, color:"#52525b" }}>{s.message_count} msgs</div>
            </div>
          ))}
        </div>
      </div>
      <div style={{ flex:1, display:"flex", flexDirection:"column", minWidth:0 }}>
        <div style={{ display:"flex", alignItems:"center", gap:10, padding:"8px 16px", borderBottom:"1px solid #27272a" }}>
          <select value={topic} onChange={e=>setTopic(e.target.value)} style={{ background:"#18181b", border:"1px solid #3f3f46", color:"#d4d4d8", borderRadius:6, padding:"4px 8px", fontSize:11, cursor:"pointer" }}>
            <option value="">All topics</option>
            {Object.entries(TOPIC_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <span style={{ marginLeft:"auto", fontSize:10, color:"#3f3f46" }}>progress Qs → DB · knowledge → RAG</span>
        </div>
        <div style={{ flex:1, overflowY:"auto", padding:"20px 24px", display:"flex", flexDirection:"column", gap:18 }}>
          {messages.length===0&&!loading&&<div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:"100%", color:"#52525b", fontSize:12 }}>Ask anything — topics, revision, concepts</div>}
          {messages.map(msg => (
            <div key={msg.id} style={{ display:"flex", gap:12, flexDirection:msg.role==="user"?"row-reverse":"row", alignItems:"flex-start" }}>
              <div style={{ width:28, height:28, borderRadius:"50%", flexShrink:0, background:msg.role==="user"?"#3f3f46":"#4c1d95", display:"flex", alignItems:"center", justifyContent:"center", fontSize:10, fontWeight:700, color:"#f4f4f5", marginTop:2 }}>{msg.role==="user"?"U":"AI"}</div>
              {msg.role==="user"
                ? <div style={{ maxWidth:"72%", background:"#27272a", borderRadius:10, padding:"10px 14px", color:"#e4e4e7", lineHeight:1.6, fontSize:13, wordBreak:"break-word" }}>{msg.content}</div>
                : <div style={{ flex:1, maxWidth:"88%" }}><MD content={msg.content} /></div>
              }
            </div>
          ))}
          {loading && <div style={{ display:"flex", gap:12 }}><div style={{ width:28, height:28, borderRadius:"50%", background:"#4c1d95", display:"flex", alignItems:"center", justifyContent:"center", fontSize:10, color:"#f4f4f5" }}>AI</div><div style={{ paddingTop:6, color:"#71717a", fontSize:12 }}>Thinking…</div></div>}
          <div ref={bottomRef} />
        </div>
        <div style={{ padding:"0 16px 16px" }}>
          <div style={{ border:"1px solid #3f3f46", borderRadius:10, background:"#18181b" }}>
            <textarea ref={inputRef} value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{ if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); send(); }}} placeholder="Ask anything…" rows={3} style={{ background:"transparent", border:"none", outline:"none", padding:"10px 14px 6px", color:"#f4f4f5", resize:"none", fontFamily:"monospace", fontSize:13, lineHeight:1.6, width:"100%", boxSizing:"border-box" }} />
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"0 10px 10px" }}>
              <span style={{ fontSize:10, color:"#52525b" }}>↵ send · shift+↵ newline</span>
              <button onClick={send} disabled={!input.trim()||loading} style={{ padding:"6px 16px", borderRadius:6, fontSize:12, fontWeight:600, background:input.trim()&&!loading?"#7c3aed":"#27272a", color:input.trim()&&!loading?"#fff":"#52525b", border:"none", cursor:input.trim()&&!loading?"pointer":"not-allowed" }}>Send</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── REVISION ──────────────────────────────────────────────────────────────────
interface RevState {
  tab:"generate"|"spaced"; topic:string; count:number;
  questions:any[]; dueQuestions:any[]; dueLoaded:boolean;
  revealed:number[]; showAnswer:number[]; updated:number[]; error:string;
}
const REV_DEFAULT: RevState = {
  tab:"generate", topic:"dsa", count:5,
  questions:[], dueQuestions:[], dueLoaded:false,
  revealed:[], showAnswer:[], updated:[], error:"",
};

function RevisionView() {
  const [st, setSt]             = useState<RevState>(() => ssGet(REVISION_STORAGE_KEY, REV_DEFAULT));
  const [loading, setLoading]   = useState(false);
  const [dueLoading, setDueLoading] = useState(false);

  function update(p: Partial<RevState>) {
    setSt(prev => { const n = {...prev,...p}; ssSet(REVISION_STORAGE_KEY, n); return n; });
  }

  useEffect(() => {
    if (st.tab==="spaced" && !st.dueLoaded && !dueLoading) loadDue();
  }, [st.tab]);

  async function loadDue() {
    setDueLoading(true);
    try {
      const d = await fetch(`${BASE}/analysis/revision/due-today-questions`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ limit:10 }),
      }).then(r => r.json());
      update({ dueQuestions:d.questions||[], dueLoaded:true });
    } catch(e:any) { update({ error:e.message, dueLoaded:true }); }
    finally { setDueLoading(false); }
  }

  async function generate() {
    setLoading(true);
    update({ questions:[], revealed:[], showAnswer:[], error:"" });
    try {
      const r = await fetch(`${BASE}/analysis/revision`, {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ topic:st.topic, count:st.count }),
      });
      if (!r.ok) { const e = await r.json(); update({ error:e.detail||"Failed" }); return; }
      const d = await r.json();
      update({ questions:d.questions||[], error:d.questions?.length?"":"No questions generated. Check notes are ingested." });
    } catch(e:any) { update({ error:e.message }); }
    finally { setLoading(false); }
  }

  async function markReviewed(itemId: number, confidence: number) {
    await fetch(`${BASE}/interview/revision/update`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ item_id:itemId, confidence }),
    });
    update({ updated:[...st.updated, itemId] });
  }

  function toggleReveal(i: number)  { update({ revealed:   st.revealed.includes(i)   ? st.revealed.filter(x=>x!==i)   : [...st.revealed, i]   }); }
  function toggleAnswer(i: number)  { update({ showAnswer: st.showAnswer.includes(i)  ? st.showAnswer.filter(x=>x!==i) : [...st.showAnswer, i] }); }

  const dc = (d:string) => d==="easy"?"#4ade80":d==="hard"?"#f87171":"#fbbf24";
  const cc = (c:number) => c>=4?"#4ade80":c>=3?"#fbbf24":"#f87171";

  function QCard({ q, i, itemId, conf, reviews }: { q:any; i:number; itemId?:number; conf?:number; reviews?:number; }) {
    return (
      <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:10, padding:18, opacity:itemId!=null&&st.updated.includes(itemId)?0.5:1 }}>
        <div style={{ display:"flex", gap:8, marginBottom:10, alignItems:"center", flexWrap:"wrap" }}>
          <span style={{ fontSize:10, background:TOPIC_COLORS[q.topic]||"#27272a", color:"#fff", padding:"2px 8px", borderRadius:4 }}>{TOPIC_LABELS[q.topic]||q.topic}</span>
          <span style={{ fontSize:10, color:dc(q.difficulty), border:`1px solid ${dc(q.difficulty)}40`, padding:"1px 6px", borderRadius:4 }}>{q.difficulty}</span>
          {conf!=null && <span style={{ fontSize:10, color:cc(conf) }}>conf {conf}/5</span>}
          {reviews!=null && <span style={{ fontSize:10, color:"#52525b" }}>{reviews}× reviewed</span>}
          <span style={{ fontSize:10, color:"#52525b", marginLeft:"auto" }}>Q{i+1}</span>
        </div>

        <div style={{ color:"#f4f4f5", fontSize:13, lineHeight:1.7, marginBottom:12 }}>{q.question}</div>

        <div style={{ display:"flex", gap:8, flexWrap:"wrap", marginBottom:8 }}>
          <button onClick={() => toggleReveal(i)} style={{ background:"transparent", border:"1px solid #3f3f46", color:st.revealed.includes(i)?"#7dd3fc":"#71717a", borderRadius:6, padding:"4px 12px", fontSize:11, cursor:"pointer" }}>
            💡 {st.revealed.includes(i)?"Hide hint":"Show hint"}
          </button>
          {q.expected_answer_points?.length>0 && (
            <button onClick={() => toggleAnswer(i)} style={{ background:"transparent", border:"1px solid #3f3f46", color:st.showAnswer.includes(i)?"#4ade80":"#71717a", borderRadius:6, padding:"4px 12px", fontSize:11, cursor:"pointer" }}>
              ✓ {st.showAnswer.includes(i)?"Hide answer":"Answer points"}
            </button>
          )}
        </div>

        {st.revealed.includes(i) && (
          <div style={{ background:"#0f172a", border:"1px solid #1e3a5f", borderRadius:6, padding:"8px 12px", fontSize:12, color:"#7dd3fc", marginBottom:8 }}>
            💡 <strong>Hint:</strong> {q.hint}
          </div>
        )}
        {st.showAnswer.includes(i) && q.expected_answer_points?.length>0 && (
          <div style={{ background:"#14532d20", border:"1px solid #166534", borderRadius:6, padding:"10px 14px", marginBottom:8 }}>
            <div style={{ fontSize:11, color:"#4ade80", marginBottom:6, fontWeight:600 }}>Expected answer points:</div>
            {q.expected_answer_points.map((p:string,j:number) => <div key={j} style={{ fontSize:12, color:"#86efac", marginBottom:4 }}>• {p}</div>)}
          </div>
        )}

        {itemId!=null && !st.updated.includes(itemId) && (
          <div style={{ display:"flex", gap:6, alignItems:"center", marginTop:8 }}>
            <span style={{ fontSize:11, color:"#52525b", marginRight:4 }}>Rate confidence:</span>
            {[1,2,3,4,5].map(c => (
              <button key={c} onClick={() => markReviewed(itemId,c)} style={{ width:28, height:28, borderRadius:6, fontSize:12, fontWeight:600, border:`1px solid ${cc(c)}40`, background:`${cc(c)}15`, color:cc(c), cursor:"pointer" }}>{c}</button>
            ))}
          </div>
        )}
        {itemId!=null && st.updated.includes(itemId) && (
          <div style={{ fontSize:11, color:"#4ade80", marginTop:8 }}>✓ Reviewed — next scheduled</div>
        )}
      </div>
    );
  }

  return (
    <div style={{ padding:24, overflowY:"auto", flex:1 }}>
      <h2 style={{ color:"#f4f4f5", fontWeight:700, margin:"0 0 16px 0" }}>🔁 Revision</h2>

      <div style={{ display:"flex", border:"1px solid #3f3f46", borderRadius:6, overflow:"hidden", marginBottom:20, width:"fit-content" }}>
        {([["generate","Generate Questions"],["spaced","Due Today"]] as const).map(([t,l]) => (
          <button key={t} onClick={() => update({ tab:t })} style={{ padding:"6px 16px", fontSize:12, border:"none", cursor:"pointer", background:st.tab===t?"#3f3f46":"transparent", color:st.tab===t?"#f4f4f5":"#71717a" }}>{l}</button>
        ))}
      </div>

      {st.tab==="generate" && (
        <>
          <p style={{ color:"#71717a", fontSize:12, marginBottom:16 }}>Real interview questions via LLM knowledge + your KB as context. <span style={{ color:"#3f3f46" }}>Persists across tab switches.</span></p>
          <div style={{ display:"flex", gap:10, marginBottom:20, alignItems:"center" }}>
            <select value={st.topic} onChange={e=>update({topic:e.target.value})} style={{ background:"#18181b", border:"1px solid #3f3f46", color:"#d4d4d8", borderRadius:6, padding:"6px 10px", fontSize:12, cursor:"pointer" }}>
              {Object.entries(TOPIC_LABELS).map(([k,v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <select value={st.count} onChange={e=>update({count:Number(e.target.value)})} style={{ background:"#18181b", border:"1px solid #3f3f46", color:"#d4d4d8", borderRadius:6, padding:"6px 10px", fontSize:12, cursor:"pointer" }}>
              {[3,5,8,10].map(n => <option key={n} value={n}>{n} questions</option>)}
            </select>
            <button onClick={generate} disabled={loading} style={{ padding:"6px 18px", background:"#7c3aed", color:"#fff", border:"none", borderRadius:6, cursor:"pointer", fontSize:12, fontWeight:600 }}>
              {loading ? "Generating (30-60s)…" : "Generate"}
            </button>
            {st.questions.length>0 && (
              <button onClick={() => update({questions:[],revealed:[],showAnswer:[]})} style={{ padding:"6px 12px", background:"transparent", border:"1px solid #3f3f46", color:"#71717a", borderRadius:6, fontSize:11, cursor:"pointer" }}>Clear</button>
            )}
          </div>
          {st.error && <div style={{ color:"#f87171", fontSize:12, marginBottom:12, background:"#18181b", padding:"8px 12px", borderRadius:6 }}>⚠️ {st.error}</div>}
          {st.questions.length===0&&!loading&&!st.error && <p style={{ color:"#52525b", fontSize:12 }}>Select topic and click Generate.</p>}
          <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
            {st.questions.map((q,i) => <QCard key={i} q={q} i={i} />)}
          </div>
        </>
      )}

      {st.tab==="spaced" && (
        <>
          <p style={{ color:"#71717a", fontSize:12, marginBottom:16 }}>Due-today items converted to real interview questions. Rate confidence 1-5 to schedule next review.</p>
          {dueLoading && <div style={{ color:"#71717a", fontSize:12, padding:16 }}>Generating questions from due items… (30-60s)</div>}
          {!dueLoading && st.dueLoaded && st.dueQuestions.length===0 && (
            <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16, color:"#71717a", fontSize:12 }}>Nothing due today. Come back tomorrow or run ingestion to add items.</div>
          )}
          {!dueLoading && st.dueQuestions.length>0 && (
            <>
              <div style={{ fontSize:11, color:"#52525b", marginBottom:14 }}>{st.dueQuestions.length} items due</div>
              <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
                {st.dueQuestions.map((q,i) => <QCard key={i} q={q} i={i} itemId={q.revision_item_id} conf={q.confidence_score} reviews={q.review_count} />)}
              </div>
            </>
          )}
          {st.dueLoaded && (
            <button onClick={() => { update({dueLoaded:false,dueQuestions:[],updated:[]}); loadDue(); }}
              style={{ marginTop:16, padding:"6px 14px", background:"transparent", border:"1px solid #3f3f46", color:"#71717a", borderRadius:6, fontSize:11, cursor:"pointer" }}>
              ↺ Refresh
            </button>
          )}
        </>
      )}
    </div>
  );
}

// ── RESUME ────────────────────────────────────────────────────────────────────
function ResumeView() {
  const [text, setText]     = useState("");
  const [resume, setResume] = useState<any>(null);
  const [loading, setLoading]   = useState(false);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`${BASE}/interview/resume`).then(r=>r.json()).then(d => { if (d.skills) setResume(d); }).finally(() => setLoading(false));
  }, []);

  async function upload() {
    if (!text.trim()) return;
    setUploading(true);
    try {
      const d = await fetch(`${BASE}/interview/resume/upload`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({text}) }).then(r=>r.json());
      setResume(d); setText("");
    } catch(e:any) { alert(`Upload failed: ${e.message}`); }
    finally { setUploading(false); }
  }

  return (
    <div style={{ padding:24, overflowY:"auto", flex:1 }}>
      <h2 style={{ color:"#f4f4f5", fontWeight:700, margin:"0 0 8px 0" }}>📄 Resume</h2>
      <p style={{ color:"#71717a", fontSize:12, marginBottom:20 }}>Paste your resume. The interview engine uses it for context-relevant questions (70% resume-based, 30% fundamentals).</p>
      {!resume && (
        <div>
          <textarea value={text} onChange={e=>setText(e.target.value)} placeholder="Paste your resume here…" rows={12}
            style={{ width:"100%", background:"#18181b", border:"1px solid #3f3f46", color:"#f4f4f5", borderRadius:8, padding:"10px 14px", fontSize:12, fontFamily:"monospace", resize:"vertical", boxSizing:"border-box", marginBottom:10, lineHeight:1.6 }} />
          <button onClick={upload} disabled={uploading||!text.trim()} style={{ padding:"8px 20px", background:"#7c3aed", color:"#fff", border:"none", borderRadius:6, cursor:"pointer", fontSize:12, fontWeight:600, opacity:uploading||!text.trim()?0.5:1 }}>
            {uploading ? "Extracting…" : "Upload & Extract"}
          </button>
        </div>
      )}
      {loading && <div style={{ color:"#71717a", fontSize:12 }}>Loading…</div>}
      {resume && (
        <div>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:14, marginBottom:14 }}>
            {[["Skills",resume.skills],["Technologies",resume.technologies]].map(([l,items]:any) => (
              <div key={l} style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16 }}>
                <div style={{ color:"#a1a1aa", fontWeight:600, fontSize:12, marginBottom:10 }}>{l}</div>
                <div style={{ display:"flex", flexWrap:"wrap", gap:6 }}>{(items||[]).map((s:string)=><span key={s} style={{ background:"#27272a", color:"#c4b5fd", padding:"3px 8px", borderRadius:4, fontSize:11 }}>{s}</span>)}</div>
              </div>
            ))}
          </div>
          <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16, marginBottom:14 }}>
            <div style={{ color:"#a1a1aa", fontWeight:600, fontSize:12, marginBottom:10 }}>Projects</div>
            {(resume.projects||[]).map((p:string,i:number)=><div key={i} style={{ color:"#e4e4e7", fontSize:12, marginBottom:6 }}>• {p}</div>)}
          </div>
          <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16, marginBottom:14 }}>
            <div style={{ color:"#a1a1aa", fontWeight:600, fontSize:12, marginBottom:10 }}>Achievements</div>
            {(resume.achievements||[]).map((a:string,i:number)=><div key={i} style={{ color:"#e4e4e7", fontSize:12, marginBottom:6 }}>• {a}</div>)}
          </div>
          <button onClick={() => setResume(null)} style={{ padding:"6px 14px", background:"transparent", border:"1px solid #3f3f46", color:"#71717a", borderRadius:6, fontSize:11, cursor:"pointer" }}>Replace resume</button>
        </div>
      )}
    </div>
  );
}

// ── STORY BANK ────────────────────────────────────────────────────────────────
function StoryBankView() {
  const [stories, setStories]   = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [searchQ, setSearchQ]   = useState("");
  const [form, setForm]         = useState({ title:"", situation:"", task:"", action:"", result:"", tags:"" });
  const [saving, setSaving]     = useState(false);

  useEffect(() => { loadStories(); }, []);
  async function loadStories() { const d = await fetch(`${BASE}/interview/stories`).then(r=>r.json()).catch(()=>[]); setStories(Array.isArray(d)?d:[]); }
  async function search() {
    if (!searchQ.trim()) { loadStories(); return; }
    const d = await fetch(`${BASE}/interview/stories/search?q=${encodeURIComponent(searchQ)}`).then(r=>r.json()).catch(()=>[]);
    setStories(Array.isArray(d)?d:[]);
  }
  async function save() {
    if (!form.title||!form.action) return;
    setSaving(true);
    try {
      await fetch(`${BASE}/interview/stories`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({...form, tags:form.tags.split(",").map(t=>t.trim()).filter(Boolean)}) });
      setForm({ title:"", situation:"", task:"", action:"", result:"", tags:"" }); setShowForm(false); loadStories();
    } catch(e:any) { alert(`Save failed: ${e.message}`); }
    finally { setSaving(false); }
  }
  async function del(id: number) { await fetch(`${BASE}/interview/stories/${id}`, { method:"DELETE" }); loadStories(); }

  return (
    <div style={{ padding:24, overflowY:"auto", flex:1 }}>
      <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:16 }}>
        <h2 style={{ color:"#f4f4f5", fontWeight:700, margin:0 }}>📖 Story Bank</h2>
        <button onClick={() => setShowForm(!showForm)} style={{ marginLeft:"auto", padding:"6px 14px", background:"#7c3aed", color:"#fff", border:"none", borderRadius:6, cursor:"pointer", fontSize:12, fontWeight:600 }}>{showForm?"Cancel":"+ Add Story"}</button>
      </div>
      <p style={{ color:"#71717a", fontSize:12, marginBottom:16 }}>STAR stories used automatically by the behavioral interviewer.</p>

      {showForm && (
        <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:10, padding:20, marginBottom:20 }}>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:10, marginBottom:10 }}>
            {[["title","Title (required)"],["tags","Tags (comma separated)"]].map(([k,ph]) => (
              <div key={k}><label style={{ fontSize:11, color:"#71717a", display:"block", marginBottom:4 }}>{ph}</label>
              <input value={(form as any)[k]} onChange={e=>setForm(f=>({...f,[k]:e.target.value}))} style={{ width:"100%", background:"#0f0f0f", border:"1px solid #3f3f46", color:"#f4f4f5", borderRadius:6, padding:"7px 10px", fontSize:12, fontFamily:"monospace", boxSizing:"border-box" }}/></div>
            ))}
          </div>
          {[["situation","Situation"],["task","Task"],["action","Action (required)"],["result","Result"]].map(([k,label]) => (
            <div key={k} style={{ marginBottom:10 }}><label style={{ fontSize:11, color:"#71717a", display:"block", marginBottom:4 }}>{label}</label>
            <textarea value={(form as any)[k]} onChange={e=>setForm(f=>({...f,[k]:e.target.value}))} rows={3} style={{ width:"100%", background:"#0f0f0f", border:"1px solid #3f3f46", color:"#f4f4f5", borderRadius:6, padding:"7px 10px", fontSize:12, fontFamily:"monospace", resize:"vertical", boxSizing:"border-box" }}/></div>
          ))}
          <button onClick={save} disabled={saving||!form.title||!form.action} style={{ padding:"8px 20px", background:"#7c3aed", color:"#fff", border:"none", borderRadius:6, cursor:"pointer", fontSize:12, fontWeight:600, opacity:saving||!form.title||!form.action?0.5:1 }}>{saving?"Saving…":"Save Story"}</button>
        </div>
      )}

      <div style={{ display:"flex", gap:8, marginBottom:16 }}>
        <input value={searchQ} onChange={e=>setSearchQ(e.target.value)} onKeyDown={e=>{ if(e.key==="Enter") search(); }} placeholder="Search by title or tags…" style={{ flex:1, background:"#18181b", border:"1px solid #3f3f46", color:"#f4f4f5", borderRadius:6, padding:"7px 12px", fontSize:12, fontFamily:"monospace" }} />
        <button onClick={search} style={{ padding:"7px 16px", background:"#27272a", border:"1px solid #3f3f46", color:"#a1a1aa", borderRadius:6, fontSize:12, cursor:"pointer" }}>Search</button>
        {searchQ && <button onClick={() => { setSearchQ(""); loadStories(); }} style={{ padding:"7px 12px", background:"transparent", border:"1px solid #3f3f46", color:"#71717a", borderRadius:6, fontSize:11, cursor:"pointer" }}>Clear</button>}
      </div>

      {stories.length===0 && <p style={{ color:"#52525b", fontSize:12 }}>No stories yet. Add your first STAR story above.</p>}
      <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
        {stories.map(s => (
          <div key={s.id} style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:10, padding:16 }}>
            <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:10 }}>
              <span style={{ color:"#f4f4f5", fontWeight:600, fontSize:13 }}>{s.title}</span>
              <div style={{ marginLeft:"auto", display:"flex", gap:6 }}>
                {(s.tags||[]).map((t:string) => <span key={t} style={{ fontSize:10, background:"#27272a", color:"#a1a1aa", padding:"1px 6px", borderRadius:4 }}>{t}</span>)}
                <button onClick={() => del(s.id)} style={{ fontSize:10, background:"transparent", border:"1px solid #3f3f46", color:"#71717a", padding:"2px 8px", borderRadius:4, cursor:"pointer" }}>Delete</button>
              </div>
            </div>
            {[["Situation",s.situation],["Task",s.task],["Action",s.action],["Result",s.result]].map(([l,v]) => v && (
              <div key={l} style={{ marginBottom:5 }}><span style={{ color:"#71717a", fontSize:11, fontWeight:600 }}>{l}: </span><span style={{ color:"#a1a1aa", fontSize:12 }}>{v}</span></div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── PROGRESS ──────────────────────────────────────────────────────────────────
function ProgressView() {
  const [dsa, setDsa]       = useState<any>(null);
  const [mastery, setMastery] = useState<any>({});
  const [today, setToday]   = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetch(`${BASE}/progress/dsa`).then(r=>r.json()).catch(()=>({})),
      fetch(`${BASE}/progress/mastery`).then(r=>r.json()).catch(()=>({})),
      fetch(`${BASE}/progress/today`).then(r=>r.json()).catch(()=>({})),
    ]).then(([d,m,t]) => { setDsa(d); setMastery(m); setToday(t); }).finally(() => setLoading(false));
  }, []);

  if (loading) return <Center>Loading…</Center>;
  const patterns  = dsa?.patterns_covered || {};
  const missing   = dsa?.missing_patterns || [];
  const difficulty = dsa?.difficulty_breakdown || {};

  return (
    <div style={{ padding:24, overflowY:"auto", flex:1 }}>
      <h2 style={{ color:"#f4f4f5", fontWeight:700, margin:"0 0 20px 0" }}>📈 My Progress</h2>
      <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:12, marginBottom:20 }}>
        {[["DSA Problems",dsa?.total_problems??0],["Patterns",Object.keys(patterns).length],["Topics Tracked",Object.values(mastery as any).reduce((s:number,d:any)=>s+(d.topic_count||0),0)],["Missing",missing.length]].map(([l,v]) => (
          <div key={l as string} style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:"14px 16px" }}>
            <div style={{ color:"#71717a", fontSize:11, marginBottom:4 }}>{l}</div>
            <div style={{ color:"#f4f4f5", fontSize:22, fontWeight:700 }}>{v}</div>
          </div>
        ))}
      </div>
      {today?.recommendations?.length>0 && (
        <div style={{ background:"#0f172a", border:"1px solid #1e3a5f", borderRadius:8, padding:16, marginBottom:16 }}>
          <div style={{ color:"#7dd3fc", fontWeight:600, marginBottom:12, fontSize:12 }}>📋 Study Today</div>
          {today.recommendations.map((r:any,i:number) => (
            <div key={i} style={{ marginBottom:8, paddingBottom:8, borderBottom:i<today.recommendations.length-1?"1px solid #1e3a5f":"none" }}>
              <div style={{ display:"flex", gap:8, alignItems:"center", marginBottom:2 }}>
                <span style={{ fontSize:10, background:TOPIC_COLORS[r.topic]||"#3f3f46", color:"#fff", padding:"1px 6px", borderRadius:4, flexShrink:0 }}>{TOPIC_LABELS[r.topic]||r.topic}</span>
                <span style={{ color:"#f4f4f5", fontSize:12 }}>{r.action}</span>
              </div>
              <div style={{ color:"#52525b", fontSize:10 }}>{r.reason}</div>
            </div>
          ))}
        </div>
      )}
      {Object.keys(mastery).length>0 && (
        <div style={{ marginBottom:16 }}>
          <div style={{ color:"#a1a1aa", fontWeight:600, fontSize:12, marginBottom:10 }}>📚 Topic Mastery</div>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
            {Object.entries(mastery as any).map(([cat,data]:any) => (
              <div key={cat} style={{ background:"#18181b", border:`1px solid ${TOPIC_COLORS[cat]||"#27272a"}40`, borderRadius:8, padding:14 }}>
                <div style={{ display:"flex", justifyContent:"space-between", marginBottom:8 }}>
                  <span style={{ color:TOPIC_COLORS[cat]||"#a1a1aa", fontWeight:600, fontSize:12 }}>{TOPIC_LABELS[cat]||cat}</span>
                  <span style={{ fontSize:11, color:"#71717a" }}>{data.topic_count} · {data.avg_mastery}/5</span>
                </div>
                <div style={{ height:4, background:"#27272a", borderRadius:2, marginBottom:8 }}>
                  <div style={{ height:"100%", width:`${(data.avg_mastery/5)*100}%`, background:TOPIC_COLORS[cat]||"#7c3aed", borderRadius:2 }} />
                </div>
                {data.strong_topics?.length>0 && <div style={{ fontSize:10, color:"#86efac", marginBottom:3 }}>✓ {data.strong_topics.slice(0,3).join(", ")}</div>}
                {data.weak_topics?.length>0   && <div style={{ fontSize:10, color:"#fca5a5" }}>✗ {data.weak_topics.slice(0,3).join(", ")}</div>}
              </div>
            ))}
          </div>
        </div>
      )}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:14 }}>
        <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16 }}>
          <div style={{ color:"#4ade80", fontWeight:600, marginBottom:10, fontSize:12 }}>✅ DSA Patterns</div>
          {Object.keys(patterns).length===0 && <p style={{ color:"#52525b", fontSize:11 }}>Run ingestion to populate.</p>}
          {Object.entries(patterns).sort((a:any,b:any)=>b[1]-a[1]).map(([p,c]:any) => (
            <div key={p} style={{ display:"flex", justifyContent:"space-between", marginBottom:5, fontSize:12 }}><span style={{ color:"#86efac" }}>{p}</span><span style={{ color:"#4ade80", fontWeight:600 }}>{c}×</span></div>
          ))}
        </div>
        <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16 }}>
          <div style={{ color:"#a1a1aa", fontWeight:600, marginBottom:10, fontSize:12 }}>Difficulty</div>
          {Object.entries(difficulty).map(([d,c]:any) => { const col=d==="Easy"?"#4ade80":d==="Medium"?"#fbbf24":"#f87171"; return <div key={d} style={{ display:"flex", justifyContent:"space-between", marginBottom:5, fontSize:12 }}><span style={{color:col}}>{d}</span><span style={{color:col,fontWeight:600}}>{c}</span></div>; })}
          {Object.keys(difficulty).length===0 && <p style={{ color:"#52525b", fontSize:11 }}>No data</p>}
        </div>
      </div>
      {missing.length>0 && (
        <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16, marginTop:14 }}>
          <div style={{ color:"#f87171", fontWeight:600, marginBottom:10, fontSize:12 }}>❌ Missing Patterns ({missing.length})</div>
          <div style={{ display:"flex", flexWrap:"wrap", gap:6 }}>
            {missing.map((p:string) => <span key={p} style={{ background:"#27272a", color:"#fca5a5", padding:"3px 8px", borderRadius:4, fontSize:11 }}>{p}</span>)}
          </div>
        </div>
      )}
    </div>
  );
}

// ── PATTERN GAPS ──────────────────────────────────────────────────────────────
function PatternGapsView() {
  const [data, setData]     = useState<any>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => { fetch(`${BASE}/progress/gaps`).then(r=>r.json()).then(setData).finally(()=>setLoading(false)); }, []);
  if (loading) return <Center>Loading…</Center>;
  if (!data)   return <Center>No data. Run ingestion first.</Center>;
  return (
    <div style={{ padding:24, overflowY:"auto", flex:1 }}>
      <h2 style={{ color:"#f4f4f5", fontWeight:700, margin:"0 0 8px 0" }}>🔍 DSA Pattern Coverage</h2>
      <p style={{ color:"#71717a", fontSize:12, marginBottom:20 }}>Coverage: <strong style={{ color:"#7dd3fc" }}>{data.coverage_percent}%</strong> of 19 senior-level patterns</p>
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:14 }}>
        <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16 }}>
          <div style={{ color:"#4ade80", fontWeight:600, marginBottom:12, fontSize:12 }}>✅ Covered</div>
          {Object.entries(data.covered_patterns||{}).map(([p,c]:any) => <div key={p} style={{ display:"flex", justifyContent:"space-between", marginBottom:6, fontSize:12 }}><span style={{ color:"#86efac" }}>{p}</span><span style={{ color:"#4ade80" }}>{c}×</span></div>)}
          {!Object.keys(data.covered_patterns||{}).length && <p style={{ color:"#52525b", fontSize:11 }}>No patterns yet.</p>}
        </div>
        <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16 }}>
          <div style={{ color:"#f87171", fontWeight:600, marginBottom:12, fontSize:12 }}>❌ Missing</div>
          {(data.missing_patterns||[]).map((p:string) => <div key={p} style={{ color:"#fca5a5", fontSize:12, marginBottom:6 }}>• {p}</div>)}
        </div>
        {Object.keys(data.weak_patterns||{}).length>0 && (
          <div style={{ background:"#18181b", border:"1px solid #27272a", borderRadius:8, padding:16, gridColumn:"1 / -1" }}>
            <div style={{ color:"#fbbf24", fontWeight:600, marginBottom:10, fontSize:12 }}>⚠️ Thin Coverage</div>
            <div style={{ display:"flex", flexWrap:"wrap", gap:6 }}>{Object.keys(data.weak_patterns).map((p:string) => <span key={p} style={{ background:"#27272a", color:"#fde68a", padding:"3px 8px", borderRadius:4, fontSize:11 }}>{p}</span>)}</div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── STAR SCORER ───────────────────────────────────────────────────────────────
function StarView() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer]     = useState("");
  const [result, setResult]     = useState<any>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState("");

  async function score() {
    if (!question.trim()||!answer.trim()||loading) return;
    setLoading(true); setResult(null); setError("");
    try {
      const r = await fetch(`${BASE}/analysis/star`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({question,answer}) });
      if (!r.ok) { const e = await r.json(); setError(e.detail||`HTTP ${r.status}`); return; }
      const d = await r.json();
      if (d.error) { setError(d.error); return; }
      setResult(d);
    } catch(e:any) { setError(e.message); }
    finally { setLoading(false); }
  }

  const sc = (n:number) => n>=4?"#4ade80":n>=3?"#fbbf24":"#f87171";

  return (
    <div style={{ padding:24, overflowY:"auto", flex:1, maxWidth:800 }}>
      <h2 style={{ color:"#f4f4f5", fontWeight:700, margin:"0 0 6px 0" }}>⭐ STAR Answer Scorer</h2>
      <p style={{ color:"#71717a", fontSize:12, marginBottom:20 }}>Strict scoring for a 6-year senior engineer.</p>
      <label style={{ fontSize:11, color:"#71717a", display:"block", marginBottom:4 }}>Behavioral question</label>
      <input value={question} onChange={e=>setQuestion(e.target.value)} placeholder="e.g. Tell me about a production incident you handled"
        style={{ width:"100%", background:"#18181b", border:"1px solid #3f3f46", color:"#f4f4f5", borderRadius:6, padding:"9px 12px", fontSize:12, fontFamily:"monospace", boxSizing:"border-box", marginBottom:14 }} />
      <label style={{ fontSize:11, color:"#71717a", display:"block", marginBottom:4 }}>Your STAR answer</label>
      <textarea value={answer} onChange={e=>setAnswer(e.target.value)} placeholder={"Situation:\nTask:\nAction:\nResult:"} rows={8}
        style={{ width:"100%", background:"#18181b", border:"1px solid #3f3f46", color:"#f4f4f5", borderRadius:6, padding:"9px 12px", fontSize:12, fontFamily:"monospace", resize:"vertical", boxSizing:"border-box", marginBottom:14, lineHeight:1.6 }} />
      <button onClick={score} disabled={loading||!question.trim()||!answer.trim()} style={{ padding:"9px 24px", background:"#7c3aed", color:"#fff", border:"none", borderRadius:6, cursor:"pointer", fontSize:12, fontWeight:600, opacity:loading||!question.trim()||!answer.trim()?0.5:1 }}>
        {loading ? "Scoring…" : "Score my answer"}
      </button>
      {error && <div style={{ marginTop:16, background:"#18181b", border:"1px solid #f87171", borderRadius:8, padding:"12px 16px", color:"#f87171", fontSize:12 }}>⚠️ {error}</div>}
      {result && (
        <div style={{ marginTop:20, background:"#18181b", border:"1px solid #27272a", borderRadius:10, padding:20 }}>
          <div style={{ display:"flex", gap:20, marginBottom:16, flexWrap:"wrap" }}>
            {[["Overall",result.score],["Situation",result.situation_score],["Task",result.task_score],["Action",result.action_score],["Result",result.result_score]].map(([l,v]:any) => (
              <div key={l} style={{ textAlign:"center" }}><div style={{ fontSize:24, fontWeight:700, color:sc(v) }}>{v??0}/5</div><div style={{ fontSize:10, color:"#71717a", marginTop:2 }}>{l}</div></div>
            ))}
          </div>
          <div style={{ color:"#fbbf24", marginBottom:12, fontSize:13, fontWeight:500 }}>{result.verdict}</div>
          {result.strengths?.length>0 && <div style={{ marginBottom:12 }}><div style={{ color:"#4ade80", fontSize:11, fontWeight:600, marginBottom:6 }}>Strengths</div>{result.strengths.map((s:string,i:number)=><div key={i} style={{ color:"#86efac", fontSize:12, marginBottom:4 }}>• {s}</div>)}</div>}
          {result.missing?.length>0 && <div style={{ marginBottom:12 }}><div style={{ color:"#f87171", fontSize:11, fontWeight:600, marginBottom:6 }}>Missing</div>{result.missing.map((m:string,i:number)=><div key={i} style={{ color:"#fca5a5", fontSize:12, marginBottom:4 }}>• {m}</div>)}</div>}
          {result.improved_answer_hint && <div style={{ background:"#0f172a", border:"1px solid #1e3a5f", borderRadius:6, padding:"10px 14px", fontSize:12, color:"#7dd3fc", marginTop:4 }}>💡 <strong>To score 5/5:</strong> {result.improved_answer_hint}</div>}
        </div>
      )}
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div style={{ display:"flex", alignItems:"center", justifyContent:"center", flex:1, color:"#52525b", fontSize:13 }}>{children}</div>;
}
