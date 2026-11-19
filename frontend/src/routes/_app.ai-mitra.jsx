import { API_URL } from "@/lib/api";
import { createFileRoute, useLocation } from "@tanstack/react-router";
import { useState, useRef, useEffect, useCallback } from "react";
import {
  Send, User, Copy, Check, CheckCircle2, Trash2, Leaf, Square,
  Microscope, Sparkles, BrainCircuit, ImagePlus,
  ClipboardPaste, Loader2, AlertTriangle,
  ChevronRight, Upload, X, Plus, RefreshCw,
  ThumbsUp, ThumbsDown, RotateCcw, MoreHorizontal,
  Globe, Zap, Paperclip, History, MessageSquare, Eye,
  MapPin, Thermometer, CloudSun, CloudRain, TrendingUp, Calendar, Sprout,
} from "lucide-react";
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { useAppData } from "@/lib/AppDataContext";
import { emitAiSyncRefresh } from "@/lib/aiSyncEvents";
import { consumeAiHandoff, resolveTaskDescriptor } from "@/lib/aiHandoff";
import { toast } from "sonner";

export const Route = createFileRoute("/_app/ai-mitra")({
  head: () => ({
    meta: [
      { title: "AI Mitra — KrishiMitra" },
      { name: "description", content: "Your personal AI farming assistant with crop disease detection." },
    ],
  }),
  component: AiMitraPage,
});

const CHART_COLORS = [
  "#d97757", "#c8a96e", "#5b8dee", "#e87c45", "#e05050", "#a97dd9",
];

const chartTooltip = {
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--color-foreground)",
};

const SUGGESTION_PROMPTS = [
  { icon: "🌾", title: "Rabi Crop Plan", desc: "Give me a full Rabi season wheat crop plan with a weekly schedule table." },
  { icon: "💰", title: "Cost of Cultivation", desc: "Typical per-acre cost of growing wheat in Punjab, by input, as a pie chart." },
  { icon: "📈", title: "Fertilizer Schedule", desc: "Give me a stage-wise fertilizer schedule for wheat in a table." },
  { icon: "🐛", title: "Pest Diagnosis", desc: "My tomato leaves have yellow spots. Identify and give a treatment plan." },
  { icon: "🧪", title: "Soil Correction", desc: "My soil pH is 5.2. Give me a correction plan in a table." },
  { icon: "🌦️", title: "Weather Impact", desc: "Compare how wheat, rice and cotton handle heavy rain — bar chart." },
];

// ── Chart helpers ─────────────────────────────────────────────────────────────
function parseChart(raw) {
  return raw.trim().split("\n").map(l => {
    const m = l.match(/^(.+?):\s*(\d+\.?\d*)/);
    return m ? { name: m[1].trim(), value: parseFloat(m[2]) } : null;
  }).filter(Boolean);
}

function BarBlock({ raw }) {
  const data = parseChart(raw);
  if (!data.length) return null;
  return (
    <div className="my-4 overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5 bg-surface-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Bar Chart</span>
      </div>
      <div className="p-4">
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.5} />
            <XAxis dataKey="name" tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={chartTooltip} cursor={{ fill: "var(--color-primary)", opacity: 0.04 }} />
            <Bar dataKey="value" radius={[5, 5, 0, 0]}>
              {data.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function LineBlock({ raw }) {
  const data = parseChart(raw);
  if (!data.length) return null;
  return (
    <div className="my-4 overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5 bg-surface-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Trend</span>
      </div>
      <div className="p-4">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data} margin={{ top: 4, right: 8, left: -20, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" opacity={0.5} />
            <XAxis dataKey="name" tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={chartTooltip} />
            <Line type="monotone" dataKey="value" stroke="#d97757" strokeWidth={2.5} dot={{ fill: "#d97757", r: 3, strokeWidth: 0 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function PieBlock({ raw }) {
  const data = parseChart(raw);
  if (!data.length) return null;
  return (
    <div className="my-4 overflow-hidden rounded-2xl border border-border bg-surface">
      <div className="flex items-center gap-2 border-b border-border px-4 py-2.5 bg-surface-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Breakdown</span>
      </div>
      <div className="p-4 flex items-center justify-center">
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Tooltip contentStyle={chartTooltip} />
            <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={75} innerRadius={35} paddingAngle={3}>
              {data.map((_, i) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Markdown Parser ───────────────────────────────────────────────────────────
function Markdown({ text }) {
  if (!text) return null;

  const parts = text.split(/(```[\s\S]*?```)/g);

  return (
    <div className="prose-clean space-y-3 text-sm leading-7 text-foreground/90">
      {parts.map((part, idx) => {
        if (part.startsWith("```")) {
          const firstLine = part.slice(3, part.indexOf("\n")).trim();
          const content = part.slice(part.indexOf("\n") + 1, -3).trim();

          if (firstLine === "barchart") return <BarBlock key={idx} raw={content} />;
          if (firstLine === "linechart") return <LineBlock key={idx} raw={content} />;
          if (firstLine === "piechart") return <PieBlock key={idx} raw={content} />;

          return (
            <div key={idx} className="my-3 overflow-hidden rounded-xl border border-border bg-surface-2">
              {firstLine && (
                <div className="flex items-center justify-between border-b border-border px-4 py-1.5 bg-surface">
                  <span className="font-mono text-[11px] text-muted-foreground">{firstLine}</span>
                </div>
              )}
              <pre className="overflow-x-auto p-4 font-mono text-xs leading-relaxed text-foreground/90">
                <code>{content}</code>
              </pre>
            </div>
          );
        }
        return <FormattedText key={idx} text={part} />;
      })}
    </div>
  );
}

/** Resize an image file to fit maxSide px and return a JPEG data URL. */
function shrinkImage(file, maxSide, quality) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      try {
        const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
        canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", quality));
      } catch (err) {
        reject(err);
      } finally {
        URL.revokeObjectURL(url);
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("unreadable image"));
    };
    img.src = url;
  });
}

function FormattedText({ text }) {
  const lines = text.split("\n");
  const out = [];
  let i = 0;

  // Escape first: AI text is rendered as HTML, so any tags in it must be
  // shown as text, never executed (XSS). Then apply the small markdown set.
  const fmt = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;")
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code class="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-foreground">$1</code>');

  while (i < lines.length) {
    const line = lines[i];

    // Table
    if (line.includes("|") && lines[i + 1]?.match(/^\|?\s*[-:]+[-| :]*$/)) {
      const rows = [];
      const headers = line.split("|").map(c => c.trim()).filter(Boolean);
      i += 2;
      while (i < lines.length && lines[i].includes("|")) {
        rows.push(lines[i].split("|").map(c => c.trim()).filter(Boolean));
        i++;
      }
      out.push(
        <div key={`tbl${i}`} className="my-4 overflow-hidden rounded-2xl border border-border bg-surface shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-border bg-surface-2">
                  {headers.map((h, j) => (
                    <th key={j} className="px-4 py-3 font-semibold text-muted-foreground uppercase tracking-wider">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row, j) => (
                  <tr key={j} className="transition-colors hover:bg-surface-2/60">
                    {row.map((cell, k) => (
                      <td key={k} className="px-4 py-3 text-foreground" dangerouslySetInnerHTML={{ __html: fmt(cell) }} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      );
      continue;
    }

    // Heading 3
    if (line.startsWith("### ")) {
      out.push(
        <h3 key={i} className="mt-5 mb-2 font-display text-sm font-bold text-foreground tracking-tight">
          <span dangerouslySetInnerHTML={{ __html: fmt(line.replace("### ", "").replace(/\*\*/g, "")) }} />
        </h3>
      );
      i++; continue;
    }

    // Heading 2
    if (line.startsWith("## ")) {
      out.push(
        <h2 key={i} className="mt-6 mb-2.5 font-display text-base font-bold text-foreground tracking-tight">
          <span dangerouslySetInnerHTML={{ __html: fmt(line.replace("## ", "").replace(/\*\*/g, "")) }} />
        </h2>
      );
      i++; continue;
    }

    // Heading 1
    if (line.startsWith("# ")) {
      out.push(
        <h1 key={i} className="mt-7 mb-3 font-display text-lg font-bold text-foreground tracking-tight">
          <span dangerouslySetInnerHTML={{ __html: fmt(line.replace("# ", "").replace(/\*\*/g, "")) }} />
        </h1>
      );
      i++; continue;
    }

    // Bullet list
    if (line.match(/^[-*] /)) {
      const items = [];
      while (i < lines.length && lines[i].match(/^[-*] /)) {
        items.push({ content: lines[i].replace(/^[-*] /, "") });
        i++;
      }
      out.push(
        <ul key={`ul${i}`} className="my-2.5 space-y-1.5 list-none">
          {items.map((it, j) => (
            <li key={j} className="flex items-start gap-2.5">
              <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-primary/70" />
              <span className="text-sm leading-7 text-foreground/90" dangerouslySetInnerHTML={{ __html: fmt(it.content) }} />
            </li>
          ))}
        </ul>
      );
      continue;
    }

    // Ordered list
    if (line.match(/^\d+\. /)) {
      const items = [];
      while (i < lines.length && lines[i].match(/^\d+\. /)) { items.push(lines[i].replace(/^\d+\. /, "")); i++; }
      out.push(
        <ol key={`ol${i}`} className="my-2.5 space-y-2 list-none">
          {items.map((it, j) => (
            <li key={j} className="flex items-start gap-3">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-foreground/8 text-[11px] font-semibold text-foreground/60 mt-[3px]">{j + 1}</span>
              <span className="text-sm leading-7 text-foreground/90" dangerouslySetInnerHTML={{ __html: fmt(it) }} />
            </li>
          ))}
        </ol>
      );
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      out.push(<div key={i} className="h-3" />);
      i++; continue;
    }

    // Paragraph
    out.push(
      <p key={i} className="text-sm leading-7 text-foreground/90"
        dangerouslySetInnerHTML={{ __html: fmt(line) }} />
    );
    i++;
  }

  return <div className="space-y-0">{out}</div>;
}

// ── Thinking indicator ────────────────────────────────────────────────────────
function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map(i => (
        <span key={i} className="h-2 w-2 rounded-full bg-foreground/30"
          style={{ animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite` }} />
      ))}
      <style>{`@keyframes bounce { 0%,80%,100%{transform:translateY(0)} 40%{transform:translateY(-6px)} }`}</style>
    </div>
  );
}

// ── Message ───────────────────────────────────────────────────────────────────
function Message({ msg, onEdit, onRetry }) {
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(msg.text);
  const [elapsed, setElapsed] = useState(0);
  const time = new Date(parseInt(msg.id) || Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  useEffect(() => {
    let t;
    if (msg.isLoading) { const s = Date.now(); t = setInterval(() => setElapsed(((Date.now() - s) / 1000).toFixed(1)), 100); }
    return () => clearInterval(t);
  }, [msg.isLoading]);

  // User message — right-aligned pill
  if (msg.role === "user") {
    return (
      <div className="group flex justify-end mb-6">
        <div className="max-w-[85%] sm:max-w-[80%]">
          {editing ? (
            <div className="flex flex-col gap-2">
              <textarea
                className="w-full rounded-2xl border border-primary/40 bg-surface px-4 py-3 text-sm text-foreground outline-none resize-none focus:ring-1 focus:ring-primary/50"
                value={editText} onChange={e => setEditText(e.target.value)} rows={3} maxLength={4000} autoFocus />
              <div className="flex justify-end gap-2">
                <button onClick={() => setEditing(false)} className="rounded-xl border border-border px-4 py-1.5 text-sm text-muted-foreground hover:bg-surface-2 transition-colors">Cancel</button>
                <button onClick={() => { onEdit?.(msg.id, editText); setEditing(false); }} className="rounded-xl bg-foreground px-4 py-1.5 text-sm font-medium text-background hover:opacity-90 transition-opacity">Send</button>
              </div>
            </div>
          ) : (
            <>
              {msg.contextTitle && (
                <div className="mb-2 flex justify-end">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 border border-primary/25 px-3 py-1 text-[11px] font-semibold text-primary shadow-sm">
                    <Sparkles className="h-3 w-3" /> {msg.contextTitle}
                  </span>
                </div>
              )}
              <div className="rounded-3xl bg-surface border border-border px-5 py-3.5 text-sm leading-7 text-foreground whitespace-pre-wrap">
                {msg.text}
              </div>
              <div className="mt-1.5 flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                <button onClick={() => setEditing(true)}
                  className="rounded-lg px-2.5 py-1 text-xs text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors">
                  Edit
                </button>
                <button onClick={() => { navigator.clipboard.writeText(msg.text); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
                  className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors">
                  {copied ? <Check className="h-3.5 w-3.5 text-primary" /> : <Copy className="h-3.5 w-3.5" />}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  // AI message — left-aligned, no bubble
  return (
    <div className="group mb-8">
      {/* AI label */}
      <div className="flex items-center gap-2.5 mb-3">
        <div className="relative grid h-7 w-7 shrink-0 place-items-center rounded-md bg-primary/15 ring-1 ring-primary/30">
          <Leaf className="h-3.5 w-3.5 text-primary" />
          <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-primary" />
        </div>
        <span className="text-sm font-semibold text-foreground">AI Mitra</span>
        <span className="text-xs text-muted-foreground">{time}</span>
      </div>

      {/* Content */}
      <div className="pl-10">
        {msg.isLoading ? (
          msg.text ? (
            <>
              <Markdown text={msg.text} />
              <ThinkingDots />
            </>
          ) : (
            <div className="flex items-center gap-2.5">
              <ThinkingDots />
              {parseFloat(elapsed) > 3 && (
                <span className="font-mono text-xs text-muted-foreground/50">{elapsed}s</span>
              )}
            </div>
          )
        ) : (
          <Markdown text={msg.text} />
        )}

        {/* Action buttons — like Claude */}
        {!msg.isLoading && msg.role === "assistant" && (
          <div className="mt-4 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
            <button onClick={() => { navigator.clipboard.writeText(msg.text); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors">
              {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              {copied ? "Copied" : "Copy"}
            </button>
            <button onClick={() => onRetry?.(msg.id)}
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors">
              <RotateCcw className="h-3.5 w-3.5" />
              Retry
            </button>
            <button className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors">
              <ThumbsUp className="h-3.5 w-3.5" />
            </button>
            <button className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors">
              <ThumbsDown className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Disease Scanner ───────────────────────────────────────────────────────────
function DiseaseScanner({ token }) {
  const [dragging, setDragging] = useState(false);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);
  const zoneRef = useRef(null);

  const load = useCallback(f => {
    if (!f?.type.startsWith("image/")) { setError("Please upload an image file (JPG, PNG, or WEBP)."); return; }
    if (f.size > 10 * 1024 * 1024) { setError("Image exceeds 10MB limit. Please upload a smaller photo."); return; }
    setFile(f); setResult(null); setError(null);
    const r = new FileReader();
    r.onload = e => setPreview(e.target.result);
    r.readAsDataURL(f);
  }, []);

  const onPaste = useCallback(e => {
    for (const item of e.clipboardData?.items || []) {
      if (item.type.startsWith("image/")) { load(item.getAsFile()); return; }
    }
  }, [load]);

  useEffect(() => {
    const el = zoneRef.current;
    if (!el) return;
    el.addEventListener("paste", onPaste);
    return () => el.removeEventListener("paste", onPaste);
  }, [onPaste]);

  const { activeFarm, postScoped, fetchDashboardData } = useAppData();
  const [alertSaved, setAlertSaved] = useState(false);
  const [savingAlert, setSavingAlert] = useState(false);
  // The farmer decides whether the photo is from this farm; nothing is saved
  // automatically.
  const saveAsAlert = async () => {
    if (!result || !activeFarm || savingAlert) return;
    setSavingAlert(true);
    try {
      const crop = result.crop && !["Crop", "None", "Uncertain"].includes(result.crop) ? `${result.crop}: ` : "";
      const res = await postScoped("/alerts", {
        category: "crop_health",
        severity: "warning",
        riskScorePct: result.confidence > 0 ? Math.round(result.confidence * 100) : null,
        title: `${crop}${result.disease || "Disease detected"}`.slice(0, 255),
        message: (result.treatment || result.symptoms || "Disease spotted in a leaf photo. Inspect the crop.").slice(0, 4000),
      });
      if (!res || res.error || !res._id) throw new Error("save failed");
      setAlertSaved(true);
      fetchDashboardData?.();
      toast.success(`Added to Risk Alerts for ${activeFarm.name}`);
    } catch {
      toast.error("Couldn't save the alert. Please try again.");
    } finally {
      setSavingAlert(false);
    }
  };

  const analyze = async () => {
    if (!file) return;
    setLoading(true); setError(null); setResult(null); setAlertSaved(false);
    const form = new FormData();
    form.append("image", file);
    try {
      const res = await fetch(`${API_URL}/disease/predict`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.message || `Diagnosis service returned error ${res.status}`);
      }
      setResult(data);
    } catch (err) {
      setError(err.message || "Failed to analyze leaf image. Please check your network connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setPreview(null);
    setResult(null);
    setError(null);
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:py-8 overflow-y-auto h-full">
      <div className="mb-6">
        <h2 className="text-xl font-bold text-foreground">Crop Disease Scanner</h2>
        <p className="mt-1 text-sm text-muted-foreground">Upload or paste a photograph of crop foliage to detect diseases, evaluate plant health, and receive agronomic treatment.</p>
      </div>

      <div
        ref={zoneRef}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); load(e.dataTransfer.files?.[0]); }}
        onClick={() => fileRef.current?.click()}
        className={`relative flex min-h-[220px] cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed p-6 sm:p-8 text-center transition-all ${
          dragging ? "border-primary bg-primary/5" : "border-border bg-surface hover:border-primary/50"
        }`}>
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={e => load(e.target.files?.[0])} />
        {preview ? (
          <div className="flex flex-col items-center gap-3">
            <img src={preview} alt="Leaf preview" className="max-h-56 rounded-2xl object-contain shadow-sm border border-border" />
            <p className="text-xs text-muted-foreground">Click or drop another image to replace</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <div className="grid h-12 w-12 place-items-center rounded-2xl bg-primary/10 text-primary">
              <Upload className="h-6 w-6" />
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">Click to upload, or drag and drop</p>
              <p className="mt-1 text-xs text-muted-foreground">PNG, JPG, WEBP up to 10MB · Paste from clipboard supported</p>
            </div>
          </div>
        )}
      </div>

      {file && (
        <div className="mt-4 flex items-center justify-between gap-3 flex-wrap">
          <button
            type="button"
            onClick={handleReset}
            className="rounded-xl border border-border px-4 py-2 text-xs font-medium text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors cursor-pointer"
          >
            Clear Photo
          </button>

          <button
            type="button"
            onClick={analyze}
            disabled={loading}
            className="flex items-center gap-2 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 transition-opacity disabled:opacity-50 cursor-pointer"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Microscope className="h-4 w-4" />}
            {loading ? "Analyzing Foliage..." : "Run Diagnosis"}
          </button>
        </div>
      )}

      {error && (
        <div className="mt-5 flex items-start gap-3 rounded-2xl border border-destructive/20 bg-destructive/10 p-4 text-sm text-destructive">
          <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="font-semibold text-xs uppercase tracking-wider">Diagnosis Interrupted</p>
            <p className="mt-0.5 text-xs text-destructive/90">{error}</p>
          </div>
        </div>
      )}

      {result && (
        <div className="mt-6 rounded-3xl border border-border bg-surface p-5 sm:p-6 shadow-sm">
          {/* Header row with Status & Confidence */}
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border pb-4">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                  result.status === "healthy"
                    ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30"
                    : result.status === "invalid_image"
                    ? "bg-destructive/15 text-destructive border border-destructive/30"
                    : result.status === "uncertain"
                    ? "bg-amber-500/15 text-amber-700 dark:text-amber-300 border border-amber-500/30"
                    : "bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30"
                }`}>
                  {result.status === "healthy" && <CheckCircle2 className="h-3.5 w-3.5" />}
                  {result.status === "invalid_image" && <AlertTriangle className="h-3.5 w-3.5" />}
                  {result.status === "uncertain" && <AlertTriangle className="h-3.5 w-3.5" />}
                  {result.status === "diseased" && <Sparkles className="h-3.5 w-3.5" />}
                  <span>
                    {result.status === "healthy" && "Healthy Foliage"}
                    {result.status === "invalid_image" && "Non-Plant Image"}
                    {result.status === "uncertain" && "Uncertain Clarity"}
                    {result.status === "diseased" && "Disease Detected"}
                  </span>
                </span>

                {result.crop && result.crop !== "Crop" && result.crop !== "None" && result.crop !== "Uncertain" && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 border border-primary/25 px-2.5 py-0.5 text-xs font-medium text-primary">
                    <Sprout className="h-3 w-3" /> {result.crop}
                  </span>
                )}
              </div>

              <h3 className="text-lg font-bold text-foreground mt-2 leading-snug">
                {result.disease || "Diagnostic Result"}
              </h3>
            </div>

            {result.confidence > 0 && (
              <span className="rounded-full bg-surface-2 border border-border px-3 py-1 font-mono text-xs font-semibold text-foreground">
                {Math.round(result.confidence * 100)}% match
              </span>
            )}
          </div>

          {/* Observed symptoms */}
          {result.symptoms && (
            <div className="mt-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5 flex items-center gap-1.5">
                <Eye className="h-3.5 w-3.5 text-primary" /> Observed Symptoms
              </h4>
              <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">{result.symptoms}</p>
            </div>
          )}

          {/* Treatment plan */}
          {result.treatment && (
            <div className={`mt-5 rounded-2xl border p-4 ${
              result.status === "healthy"
                ? "border-emerald-500/20 bg-emerald-500/5 dark:bg-emerald-950/20"
                : result.status === "invalid_image"
                ? "border-border bg-surface-2"
                : "border-primary/20 bg-primary/5 dark:bg-primary/10"
            }`}>
              <h4 className="text-xs font-semibold uppercase tracking-wider text-primary mb-2 flex items-center gap-1.5">
                <Leaf className="h-3.5 w-3.5" />
                {result.status === "healthy" ? "Maintenance & Growth Advice" : "Recommended Agronomic Treatment"}
              </h4>
              <p className="text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap">{result.treatment}</p>
            </div>
          )}

          {/* Preventive measures */}
          {result.preventive_measures && (
            <div className="mt-4 pt-4 border-t border-border/70">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1.5 flex items-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> Preventive Measures
              </h4>
              <p className="text-xs leading-relaxed text-muted-foreground whitespace-pre-wrap">{result.preventive_measures}</p>
            </div>
          )}

          {result.status === "diseased" && activeFarm && (
            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border bg-surface-2 p-4">
              <p className="text-xs text-muted-foreground">Is this from {activeFarm.name}? Track it in Risk Alerts.</p>
              <button
                type="button"
                onClick={saveAsAlert}
                disabled={alertSaved || savingAlert}
                className="rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-60 cursor-pointer"
              >
                {alertSaved ? "Added to Risk Alerts ✓" : savingAlert ? "Saving…" : "Add to Risk Alerts"}
              </button>
            </div>
          )}

          {/* Disclaimer */}
          <div className="mt-5 pt-3 border-t border-border/50 text-center">
            <p className="text-[11px] text-muted-foreground/75 leading-relaxed">
              AI diagnosis is advisory. Inspect standing crops in person and consult local KVK experts before major chemical interventions.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Contextual Task Card (Responsive 5-state UI) ──────────────────────────────
function ContextualTaskCard({ task, loading, onStop, onRetry, onDismiss }) {
  if (!task) return null;

  const isPending = task.status === "pending";
  const isInProgress = task.status === "in_progress";
  const isCompleted = task.status === "completed";
  const isCancelled = task.status === "cancelled";
  const isFailed = task.status === "failed";

  const renderChipIcon = (type) => {
    switch (type) {
      case "location":
        return <MapPin className="h-3 w-3 text-primary shrink-0" />;
      case "temp":
        return <Thermometer className="h-3 w-3 text-amber-500 shrink-0" />;
      case "condition":
        return <CloudSun className="h-3 w-3 text-blue-500 shrink-0" />;
      case "rain":
        return <CloudRain className="h-3 w-3 text-sky-500 shrink-0" />;
      case "commodity":
      case "crop":
        return <Sprout className="h-3 w-3 text-emerald-500 shrink-0" />;
      case "stage":
        return <TrendingUp className="h-3 w-3 text-primary shrink-0" />;
      case "day":
      case "count":
        return <Calendar className="h-3 w-3 text-muted-foreground shrink-0" />;
      default:
        return <Sparkles className="h-3 w-3 text-primary shrink-0" />;
    }
  };

  return (
    <div className="w-full px-3 sm:px-6 pt-3 pb-1 shrink-0">
      <div
        role="status"
        aria-live="polite"
        className={`relative mx-auto max-w-3xl rounded-2xl border p-3.5 sm:p-4 shadow-sm transition-all duration-300 overflow-hidden ${
          isInProgress || isPending
            ? "border-primary/30 bg-primary/5 dark:bg-primary/10"
            : isCompleted
            ? "border-emerald-500/30 bg-emerald-500/5 dark:bg-emerald-950/20"
            : isCancelled
            ? "border-amber-500/30 bg-amber-500/5 dark:bg-amber-950/20"
            : "border-destructive/30 bg-destructive/5 dark:bg-destructive/950/20"
        }`}
      >
        {/* Top row: Status icon, Title, Status badge & Action buttons */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            {/* Status icon badge */}
            <div
              className={`h-9 w-9 shrink-0 rounded-xl flex items-center justify-center border shadow-xs transition-colors ${
                isInProgress || isPending
                  ? "bg-primary/15 border-primary/25 text-primary"
                  : isCompleted
                  ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-600 dark:text-emerald-400"
                  : isCancelled
                  ? "bg-amber-500/15 border-amber-500/30 text-amber-600 dark:text-amber-400"
                  : "bg-destructive/15 border-destructive/30 text-destructive"
              }`}
            >
              {isPending && (
                <span className="relative flex h-3 w-3">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-primary" />
                </span>
              )}
              {isInProgress && (
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
              )}
              {isCompleted && (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
              )}
              {isCancelled && (
                <Square className="h-3.5 w-3.5 fill-current text-amber-600 dark:text-amber-400" />
              )}
              {isFailed && (
                <AlertTriangle className="h-4 w-4 text-destructive" />
              )}
            </div>

            {/* Title & Status phrase */}
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm font-semibold text-foreground leading-snug">
                  {task.taskName || "AI Analysis"}
                </h3>
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
                    isInProgress
                      ? "bg-primary/15 text-primary"
                      : isPending
                      ? "bg-primary/10 text-primary/80"
                      : isCompleted
                      ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300"
                      : isCancelled
                      ? "bg-amber-500/15 text-amber-700 dark:text-amber-300"
                      : "bg-destructive/15 text-destructive"
                  }`}
                >
                  {isInProgress && "Analyzing"}
                  {isPending && "Queued"}
                  {isCompleted && "Completed"}
                  {isCancelled && "Stopped"}
                  {isFailed && "Failed"}
                </span>
              </div>

              <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">
                {isPending && `Preparing ${task.taskName || "Analysis"}...`}
                {isInProgress && `${task.actionLabel || `Analyzing ${task.taskName}`}...`}
                {isCompleted && (task.completedLabel || `${task.taskName} complete`)}
                {isCancelled && `${task.taskName || "Analysis"} stopped by user`}
                {isFailed && (task.error || "Generation could not be completed.")}
              </p>
            </div>
          </div>

          {/* Action buttons with minimum 32px touch target */}
          <div className="flex shrink-0 items-center gap-1.5 pt-0.5">
            {isInProgress && (
              <button
                type="button"
                onClick={onStop}
                className="h-8 min-h-[32px] px-3 rounded-xl border border-primary/30 bg-primary/10 text-xs font-semibold text-primary hover:bg-primary/20 transition-colors flex items-center gap-1.5 cursor-pointer shadow-xs active:scale-95"
                title="Stop analysis"
                aria-label="Stop analysis"
              >
                <Square className="h-3 w-3 fill-current" />
                <span>Stop</span>
              </button>
            )}

            {(isFailed || isCancelled) && onRetry && (
              <button
                type="button"
                onClick={onRetry}
                className="h-8 min-h-[32px] px-3 rounded-xl border border-primary/30 bg-primary/10 text-xs font-semibold text-primary hover:bg-primary/20 transition-colors flex items-center gap-1.5 cursor-pointer shadow-xs active:scale-95"
                title="Retry analysis"
                aria-label="Retry analysis"
              >
                <RefreshCw className="h-3 w-3" />
                <span>Retry</span>
              </button>
            )}

            {(isCompleted || isCancelled || isFailed) && onDismiss && (
              <button
                type="button"
                onClick={onDismiss}
                className="h-8 w-8 min-h-[32px] min-w-[32px] rounded-xl border border-border bg-surface text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors flex items-center justify-center cursor-pointer shadow-xs active:scale-95"
                title="Dismiss notification"
                aria-label="Dismiss task notification"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Error alert details when failed */}
        {isFailed && task.error && (
          <div className="mt-2.5 rounded-xl border border-destructive/20 bg-destructive/10 px-3 py-2 text-xs text-destructive flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <span className="font-semibold">Generation issue: </span>
              <span>{task.error}</span>
            </div>
          </div>
        )}

        {/* Metadata Chips / Tags row */}
        {((task.chips && task.chips.length > 0) || task.detail) && (
          <div className="mt-3 pt-2.5 border-t border-border/50 flex flex-wrap items-center gap-1.5 text-[11px]">
            {task.chips && task.chips.length > 0 ? (
              task.chips.map((chip, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center gap-1 rounded-full bg-surface border border-border/70 px-2.5 py-0.5 font-medium text-foreground/80 shadow-xs"
                >
                  {renderChipIcon(chip.type)}
                  <span>{chip.label}</span>
                </span>
              ))
            ) : task.detail ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-surface border border-border/70 px-2.5 py-0.5 font-medium text-foreground/80 shadow-xs">
                <Sparkles className="h-3 w-3 text-primary shrink-0" />
                <span>{task.detail}</span>
              </span>
            ) : null}
          </div>
        )}

        {/* Animated Progress Bar across bottom during in_progress */}
        {isInProgress && (
          <div className="absolute bottom-0 left-0 right-0 h-1 overflow-hidden bg-primary/15">
            <div
              className="h-full bg-primary rounded-full animate-indeterminate-bar"
            />
            <style>{`
              @keyframes krishiProgressIndeterminate {
                0% { transform: translateX(-100%); }
                50% { transform: translateX(110%); }
                100% { transform: translateX(250%); }
              }
              .animate-indeterminate-bar {
                width: 45%;
                animation: krishiProgressIndeterminate 1.8s infinite ease-in-out;
              }
            `}</style>
          </div>
        )}
      </div>
    </div>
  );
}

// ── History Drawer Component ──────────────────────────────────────────────────
function HistoryDrawer({
  isOpen,
  onClose,
  sessions,
  currentSessionId,
  onSelectSession,
  onDeleteSession,
  onNewChat,
  loading,
}) {
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 backdrop-blur-xs transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Slide-out Drawer */}
      <aside
        className="relative ml-auto flex h-full w-full max-w-sm flex-col bg-background shadow-2xl border-l border-border z-10 transition-transform duration-300 animate-in slide-in-from-right"
        role="dialog"
        aria-label="Conversation History"
      >
        {/* Drawer Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-border px-4 py-3.5 bg-surface-2">
          <div className="flex items-center gap-2">
            <History className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">Chat History</h2>
            {sessions.length > 0 && (
              <span className="rounded-full bg-primary/10 px-2 py-0.5 font-mono text-[11px] font-semibold text-primary">
                {sessions.length}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-lg text-muted-foreground hover:bg-surface hover:text-foreground transition-colors cursor-pointer"
            aria-label="Close history drawer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Quick New Chat Button */}
        <div className="p-3 border-b border-border/70">
          <button
            type="button"
            onClick={() => {
              onNewChat();
              onClose();
            }}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary text-primary-foreground py-2.5 px-4 text-xs font-semibold shadow-xs hover:opacity-90 active:scale-98 transition-all cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Start New Chat</span>
          </button>
        </div>

        {/* Sessions List */}
        <div className="flex-1 overflow-y-auto p-3 space-y-1.5 min-h-0">
          {loading ? (
            <div className="flex h-32 items-center justify-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              <span>Loading conversations...</span>
            </div>
          ) : sessions.length === 0 ? (
            <div className="flex h-48 flex-col items-center justify-center text-center px-4">
              <MessageSquare className="h-8 w-8 text-muted-foreground/40 mb-2" />
              <p className="text-xs font-medium text-foreground">No conversations yet</p>
              <p className="text-[11px] text-muted-foreground mt-0.5">Your questions and farming advisories will appear here.</p>
            </div>
          ) : (
            sessions.map(s => {
              const isSelected = s.sessionId === currentSessionId;
              const isConfirming = confirmDeleteId === s.sessionId;
              const dateStr = s.updated_at
                ? new Date(s.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })
                : "";

              return (
                <div
                  key={s.sessionId}
                  className={`group relative rounded-xl border p-3 transition-all ${
                    isSelected
                      ? "border-primary/50 bg-primary/5 dark:bg-primary/10 shadow-xs"
                      : "border-border bg-surface hover:border-border/80 hover:bg-surface-2"
                  }`}
                >
                  {isConfirming ? (
                    <div className="flex items-center justify-between gap-2 py-0.5">
                      <span className="text-xs text-destructive font-medium">Delete conversation?</span>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteSession(s.sessionId);
                            setConfirmDeleteId(null);
                          }}
                          className="rounded-lg bg-destructive px-2 py-1 text-[11px] font-semibold text-destructive-foreground hover:opacity-90 cursor-pointer"
                        >
                          Delete
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setConfirmDeleteId(null);
                          }}
                          className="rounded-lg border border-border bg-surface px-2 py-1 text-[11px] text-muted-foreground hover:bg-surface-2 cursor-pointer"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      className="flex items-start justify-between gap-2 cursor-pointer"
                      onClick={() => {
                        onSelectSession(s.sessionId);
                        onClose();
                      }}
                    >
                      <div className="min-w-0 flex-1">
                        <p className={`text-xs font-medium truncate ${isSelected ? "text-primary font-semibold" : "text-foreground"}`}>
                          {s.title || "Agricultural Chat"}
                        </p>
                        {s.preview && (
                          <p className="text-[11px] text-muted-foreground line-clamp-1 mt-0.5">
                            {s.preview}
                          </p>
                        )}
                        <div className="mt-1.5 flex items-center gap-2 text-[10px] text-muted-foreground/70">
                          {dateStr && <span>{dateStr}</span>}
                          {s.message_count > 0 && (
                            <>
                              <span>•</span>
                              <span>{s.message_count} {s.message_count === 1 ? "msg" : "msgs"}</span>
                            </>
                          )}
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteId(s.sessionId);
                        }}
                        className="opacity-0 group-hover:opacity-100 focus:opacity-100 p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-all cursor-pointer shrink-0"
                        title="Delete conversation"
                        aria-label={`Delete conversation ${s.title}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </aside>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
function AiMitraPage() {
  const { token, activeFarm, weatherSnapshot } = useAppData();
  const location = useLocation();
  const [tab, setTab] = useState("chat");
  const [input, setInput] = useState("");
  const [contextualTask, setContextualTask] = useState(() => {
    if (typeof window !== "undefined") {
      try {
        const saved = sessionStorage.getItem("krishimitra_active_task");
        return saved ? JSON.parse(saved) : null;
      } catch (e) {
        return null;
      }
    }
    return null;
  });
  const [messages, setMessages] = useState(() => {
    if (typeof window !== "undefined") {
      try {
        const saved = sessionStorage.getItem("krishimitra_active_task");
        if (saved) {
          const parsed = JSON.parse(saved);
          if (Array.isArray(parsed?.messages) && parsed.messages.length > 0) {
            return parsed.messages;
          }
        }
      } catch (e) {}
    }
    return [];
  });
  const [loading, setLoading] = useState(false);
  const scrollContainerRef = useRef(null);
  const textRef = useRef(null);
  const sessionId = useRef(contextualTask?.sessionId || "main-chat-session");
  const abortControllerRef = useRef(null);
  const fileInputRef = useRef(null);
  const [attachedImage, setAttachedImage] = useState(null);

  // Chat History state
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [loadingSessions, setLoadingSessions] = useState(false);

  const fetchSessions = useCallback(async () => {
    if (!token) return;
    setLoadingSessions(true);
    try {
      const res = await fetch(`${API_URL}/chat/sessions`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setSessions(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error("Failed to load sessions:", err);
    } finally {
      setLoadingSessions(false);
    }
  }, [token]);

  useEffect(() => {
    if (historyOpen) {
      fetchSessions();
    }
  }, [historyOpen, fetchSessions]);

  const handleSelectSession = (sid) => {
    if (!sid) return;
    if (contextualTask) {
      updateContextualTask(null);
      try { sessionStorage.removeItem("krishimitra_active_task"); } catch (e) {}
    }
    sessionId.current = sid;
    loadHistory(sid);
  };

  const handleDeleteSession = async (sid) => {
    if (!token || !sid) return;
    try {
      const res = await fetch(`${API_URL}/chat/${encodeURIComponent(sid)}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        setSessions(prev => prev.filter(s => s.sessionId !== sid));
        toast.success("Conversation deleted");
        if (sessionId.current === sid) {
          clear();
        }
      } else {
        toast.error("Failed to delete conversation");
      }
    } catch (err) {
      toast.error("Network error while deleting conversation");
    }
  };

  // Synchronous lock refs to protect against race conditions and effect re-runs
  const isAtBottomRef = useRef(true);
  const handoffProcessedRef = useRef(false);
  const handoffActiveRef = useRef(false);
  const isStreamingRef = useRef(false);

  const updateContextualTask = useCallback((updater) => {
    setContextualTask(prev => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      try {
        if (next) {
          sessionStorage.setItem("krishimitra_active_task", JSON.stringify(next));
        } else {
          sessionStorage.removeItem("krishimitra_active_task");
        }
      } catch (e) {}
      return next;
    });
  }, []);

  const scrollToBottom = useCallback((behavior = "instant") => {
    const el = scrollContainerRef.current;
    if (!el) return;
    // Welcome screen (no messages): keep its heading in view instead.
    if (el.querySelector("[data-welcome]")) {
      el.scrollTop = 0;
      return;
    }
    if (behavior === "instant") {
      el.scrollTop = el.scrollHeight;
    } else {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, []);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    // Considered near bottom if within 120px of bottom
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isAtBottomRef.current = distanceToBottom < 120;
  }, []);

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = null;
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Please attach a photo (JPEG, PNG or WEBP).");
      return;
    }
    if (file.size > 15 * 1024 * 1024) {
      toast.error("Image must be smaller than 15 MB");
      return;
    }
    try {
      // Phone photos are often 3–8 MB; shrink to ~1280 px JPEG so the upload
      // is quick on mobile data. The AI doesn't need more detail than that.
      setAttachedImage(await shrinkImage(file, 1280, 0.85));
    } catch {
      if (file.size > 5 * 1024 * 1024) {
        toast.error("Couldn't read this photo. Try a JPEG or PNG under 5 MB.");
        return;
      }
      const reader = new FileReader();
      reader.onload = (event) => setAttachedImage(event.target.result);
      reader.readAsDataURL(file);
    }
  };

  useEffect(() => {
    if (!loading && tab === "chat" && typeof window !== "undefined" && window.matchMedia?.("(pointer: fine)").matches) {
      textRef.current?.focus();
    }
  }, [loading, tab]);

  const loadHistory = async (sid) => {
    if (!token || !sid) return;
    if (handoffActiveRef.current || isStreamingRef.current) return;
    try {
      const res = await fetch(`${API_URL}/chat/${encodeURIComponent(sid)}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      if (handoffActiveRef.current || isStreamingRef.current) return;
      const history = await res.json();
      if (handoffActiveRef.current || isStreamingRef.current) return;
      const normalized = (Array.isArray(history) ? history : []).map(m => ({
        id: String(m.id || m._id || `${Date.now()}-${Math.random()}`),
        role: m.role, text: m.text || m.content || "", isLoading: false,
      }));
      setMessages(normalized);
      sessionId.current = sid;
      setTab("chat");

      // Position chat viewport at latest message upon history load
      isAtBottomRef.current = true;
      requestAnimationFrame(() => {
        scrollToBottom("instant");
        setTimeout(() => scrollToBottom("instant"), 60);
        setTimeout(() => scrollToBottom("instant"), 180);
      });
    } catch (err) {
      console.error("Failed to load chat history", err);
    }
  };

  const send = async (text, options = {}) => {
    if (!text || !text.trim()) return;

    if (options.isContextual) {
      handoffActiveRef.current = true;
    }
    isStreamingRef.current = true;

    // Track contextual task if passed or active
    const activeTaskId = options.contextualTaskId || (options.isContextual && contextualTask ? contextualTask.id : null);
    const currentSid = options.customSessionId || sessionId.current;
    sessionId.current = currentSid;

    let userMsg, aiMsg;
    if (options.presetMessages && options.presetMessages.length >= 2) {
      userMsg = options.presetMessages[0];
      aiMsg = options.presetMessages[1];
    } else {
      userMsg = {
        id: `user-${Date.now()}`,
        role: "user",
        text: text.trim(),
        contextTitle: options.contextTitle || null,
        imageBase64: attachedImage,
      };
      aiMsg = { id: `ai-${Date.now() + 1}`, role: "assistant", text: "", isLoading: true };

      if (options.isContextual) {
        setMessages([userMsg, aiMsg]);
      } else {
        setMessages(p => [...p, userMsg, aiMsg]);
      }
    }
    setLoading(true);

    if (activeTaskId) {
      updateContextualTask(prev => {
        if (!prev || prev.id !== activeTaskId) return prev;
        return {
          ...prev,
          status: "in_progress",
          startTime: prev.startTime || Date.now(),
          sessionId: currentSid,
          messages: [userMsg, aiMsg],
          error: null,
        };
      });
    }

    // Scroll to latest message immediately when user sends
    isAtBottomRef.current = true;
    requestAnimationFrame(() => scrollToBottom("smooth"));

    const payloadImage = attachedImage;
    setAttachedImage(null);
    abortControllerRef.current = new AbortController();

    let streamCompletedNormally = false;
    let streamErrorMessage = null;
    let fullText = "";

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          message: text.trim(),
          sessionId: currentSid,
          farmId: activeFarm?._id || null,
          weatherSnapshot: weatherSnapshot || null,
          imageBase64: payloadImage,
        }),
        signal: abortControllerRef.current.signal,
      });
      if (!res.ok) {
        const errorText = await res.text().catch(() => "");
        throw new Error(errorText || `Failed to connect to AI assistant (${res.status})`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (!streamCompletedNormally) {
        const { done, value } = await reader.read();
        if (done) {
          if (!streamErrorMessage) {
            streamCompletedNormally = true;
          }
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        let newlineIndex;
        while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newlineIndex).trim();
          buffer = buffer.slice(newlineIndex + 1);
          if (!line) continue;
          if (line.startsWith("data: ")) {
            const dataStr = line.slice(6).trim();
            if (dataStr === "[DONE]") {
              streamCompletedNormally = true;
              break;
            }
            try {
              const parsed = JSON.parse(dataStr);
              if (parsed.error) {
                streamErrorMessage = parsed.error;
                fullText = parsed.error;
                setMessages(p => {
                  const exists = p.some(m => m.id === aiMsg.id);
                  if (exists) {
                    return p.map(m => m.id === aiMsg.id ? { ...m, text: fullText, isLoading: false } : m);
                  }
                  return [userMsg, { ...aiMsg, text: fullText, isLoading: false }];
                });
              } else if (parsed.chunk) {
                fullText += parsed.chunk;
                setMessages(p => {
                  const exists = p.some(m => m.id === aiMsg.id);
                  if (exists) {
                    return p.map(m => m.id === aiMsg.id ? { ...m, text: fullText } : m);
                  }
                  return [userMsg, { ...aiMsg, text: fullText }];
                });
                if (activeTaskId) {
                  updateContextualTask(prev => {
                    if (!prev || prev.id !== activeTaskId) return prev;
                    return {
                      ...prev,
                      messages: [userMsg, { ...aiMsg, text: fullText, isLoading: true }],
                    };
                  });
                }
                // Only autoscroll if user hasn't scrolled up to read history
                if (isAtBottomRef.current) {
                  scrollToBottom("instant");
                }
              }
            } catch (e) {}
          }
        }
      }
      try {
        await reader.cancel();
      } catch (e) {}

      if (activeTaskId) {
        const isFailureText = !fullText ||
          fullText.includes("AI service is currently unavailable") ||
          fullText.includes("I do not have enough verified information in the KrishiMitra knowledge base");

        if (streamErrorMessage || isFailureText) {
          updateContextualTask(prev => (prev && prev.id === activeTaskId ? {
            ...prev,
            status: "failed",
            error: streamErrorMessage || "AI service is currently unavailable",
            endTime: Date.now(),
            messages: [userMsg, { ...aiMsg, text: fullText, isLoading: false }],
          } : prev));
        } else if (streamCompletedNormally && fullText.trim().length > 0) {
          updateContextualTask(prev => (prev && prev.id === activeTaskId ? {
            ...prev,
            status: "completed",
            endTime: Date.now(),
            messages: [userMsg, { ...aiMsg, text: fullText, isLoading: false }],
          } : prev));
        }
      }

      setMessages(p => {
        const exists = p.some(m => m.id === aiMsg.id);
        if (exists) {
          return p.map(m => m.id === aiMsg.id ? { ...m, text: fullText, isLoading: false } : m);
        }
        return [userMsg, { ...aiMsg, text: fullText, isLoading: false }];
      });
      emitAiSyncRefresh("chat");
      fetchSessions();
    } catch (err) {
      if (err.name === "AbortError") {
        const abortedText = fullText || "Generation stopped by user.";
        setMessages(p => p.map(m => m.id === aiMsg.id ? { ...m, text: abortedText, isLoading: false } : m));
        if (activeTaskId) {
          updateContextualTask(prev => (prev && prev.id === activeTaskId ? {
            ...prev,
            status: "cancelled",
            endTime: Date.now(),
            messages: [userMsg, { ...aiMsg, text: abortedText, isLoading: false }],
          } : prev));
        }
      } else {
        const errMsg = err.message || "Connection error.";
        setMessages(p => p.map(m => m.id === aiMsg.id ? { ...m, text: errMsg, isLoading: false } : m));
        if (activeTaskId) {
          updateContextualTask(prev => (prev && prev.id === activeTaskId ? {
            ...prev,
            status: "failed",
            error: errMsg,
            endTime: Date.now(),
            messages: [userMsg, { ...aiMsg, text: errMsg, isLoading: false }],
          } : prev));
        }
      }
    } finally {
      setLoading(false);
      isStreamingRef.current = false;
      handoffActiveRef.current = false;
      if (isAtBottomRef.current) {
        scrollToBottom("smooth");
      }
      setTimeout(() => {
        textRef.current?.focus();
      }, 50);
    }
  };

  const executeHandoff = useCallback((handoff) => {
    if (!handoff || !handoff.prompt) return;
    handoffActiveRef.current = true;
    const descriptor = resolveTaskDescriptor(handoff);
    const handoffSid = `task-${handoff.source || "feature"}-${Date.now()}`;
    sessionId.current = handoffSid;
    setTab("chat");

    const userMsg = {
      id: `user-${Date.now()}`,
      role: "user",
      text: handoff.prompt.trim(),
      contextTitle: handoff.contextTitle || null,
    };
    const aiMsg = { id: `ai-${Date.now() + 1}`, role: "assistant", text: "", isLoading: true };

    const initialTask = {
      ...descriptor,
      status: "in_progress",
      startTime: Date.now(),
      endTime: null,
      error: null,
      sessionId: handoffSid,
      messages: [userMsg, aiMsg],
    };
    updateContextualTask(initialTask);
    setMessages([userMsg, aiMsg]);

    send(handoff.prompt, {
      contextTitle: handoff.contextTitle,
      contextualTaskId: descriptor.id,
      customSessionId: handoffSid,
      isContextual: true,
      presetMessages: [userMsg, aiMsg],
    });
  }, [updateContextualTask]);

  // On mount & route navigation: check for single-use contextual handoff, URL search prompt, or standard history load
  useEffect(() => {
    let isCancelled = false;

    const handleInitialLoad = async () => {
      // 1. Consume any contextual handoff from Market, Weather, Crop Plan, etc.
      const handoff = consumeAiHandoff();
      if (handoff) {
        handoffActiveRef.current = true;
        executeHandoff(handoff);
        return;
      }

      // 2. If already streaming, let the stream proceed
      if (isStreamingRef.current) {
        return;
      }

      // 3. Active task resumption: check if an active task exists in sessionStorage
      const savedTaskRaw = typeof window !== "undefined" ? sessionStorage.getItem("krishimitra_active_task") : null;
      if (savedTaskRaw) {
        try {
          const savedTask = JSON.parse(savedTaskRaw);
          if (savedTask && (savedTask.status === "in_progress" || savedTask.status === "pending")) {
            if (messages.length === 0 && Array.isArray(savedTask.messages) && savedTask.messages.length > 0) {
              setMessages(savedTask.messages);
            }
            if (!isStreamingRef.current && savedTask.prompt) {
              sessionId.current = savedTask.sessionId || sessionId.current;
              handoffActiveRef.current = true;
              send(savedTask.prompt, {
                contextTitle: savedTask.contextTitle,
                contextualTaskId: savedTask.id,
                customSessionId: savedTask.sessionId,
                isContextual: true,
              });
            }
            return;
          } else if (savedTask && savedTask.sessionId) {
            sessionId.current = savedTask.sessionId;
          }
        } catch (e) {}
      }

      // 4. Fall back to search param ?prompt= if present
      const params = new URLSearchParams(window.location.search);
      const initialPrompt = params.get("prompt");
      if (initialPrompt && !handoffProcessedRef.current) {
        handoffProcessedRef.current = true;
        window.history.replaceState({}, document.title, window.location.pathname);
        const activeSid = `search-prompt-${Date.now()}`;
        sessionId.current = activeSid;
        setMessages([]);
        setTab("chat");
        send(initialPrompt);
        return;
      }

      // 5. Normal visit without handoff: load latest conversation only if messages is empty
      // and there is no active handoff or task running
      if (token && messages.length === 0 && !loading && !handoffActiveRef.current && !isStreamingRef.current && !contextualTask) {
        try {
          const res = await fetch(`${API_URL}/chat/sessions`, {
            headers: { Authorization: `Bearer ${token}` }
          });
          if (res.ok) {
            const list = await res.json();
            if (Array.isArray(list) && list.length > 0 && list[0].sessionId) {
              if (!isCancelled && !handoffActiveRef.current && !isStreamingRef.current) {
                loadHistory(list[0].sessionId);
                return;
              }
            }
          }
        } catch (e) {}
        if (!isCancelled && !handoffActiveRef.current && !isStreamingRef.current) {
          loadHistory("main-chat-session");
        }
      }
    };

    handleInitialLoad();

    // Listen for custom handoff event in case navigation happens within active SPA router
    const handleHandoffEvent = () => {
      const handoff = consumeAiHandoff();
      if (handoff) {
        handoffActiveRef.current = true;
        executeHandoff(handoff);
      }
    };
    window.addEventListener("krishi:ai-handoff", handleHandoffEvent);
    return () => {
      isCancelled = true;
      window.removeEventListener("krishi:ai-handoff", handleHandoffEvent);
    };
  }, [location.pathname, location.key, token, executeHandoff]);

  const handleInterrupt = (e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    if (abortControllerRef.current) abortControllerRef.current.abort();
  };

  const handleRetryContextualTask = () => {
    if (!contextualTask || !contextualTask.prompt) return;
    handoffActiveRef.current = true;
    const retryTaskId = contextualTask.id;
    updateContextualTask(prev => ({
      ...prev,
      status: "in_progress",
      error: null,
      startTime: Date.now(),
      endTime: null,
    }));
    send(contextualTask.prompt, {
      contextTitle: contextualTask.contextTitle,
      contextualTaskId: retryTaskId,
      customSessionId: sessionId.current,
      isContextual: true,
    });
  };

  const handleDismissContextualTask = () => {
    handoffActiveRef.current = false;
    updateContextualTask(null);
    try {
      sessionStorage.removeItem("krishimitra_active_task");
    } catch (e) {}
  };

  const handleSend = () => {
    if (!input.trim() || loading) return;
    const msg = input;
    setInput("");
    if (textRef.current) textRef.current.style.height = "44px";
    if (contextualTask && contextualTask.status !== "in_progress") {
      updateContextualTask(null);
      try {
        sessionStorage.removeItem("krishimitra_active_task");
      } catch (e) {}
    }
    send(msg);
  };
  const handleEdit = (id, newText) => {
    const idx = messages.findIndex(m => m.id === id);
    setMessages(p => p.slice(0, idx));
    send(newText);
  };
  const handleRetry = (id) => {
    const idx = messages.findIndex(m => m.id === id);
    const prevUser = [...messages].slice(0, idx).reverse().find(m => m.role === "user");
    if (!prevUser) return;
    setMessages(p => p.slice(0, idx));
    send(prevUser.text);
  };
  const clear = () => {
    handoffActiveRef.current = false;
    isStreamingRef.current = false;
    setMessages([]);
    updateContextualTask(null);
    sessionId.current = `chat-${Date.now()}`;
    try {
      sessionStorage.removeItem("krishimitra_active_task");
    } catch (e) {}
  };

  const hasActiveTask = Boolean(contextualTask);
  const isEmpty = messages.length === 0 && !hasActiveTask && !loading;

  return (
    <div
      className="flex overflow-hidden bg-background -mx-4 -my-6 lg:-mx-7 h-[calc(100dvh-57px)] sm:h-[calc(100vh-57px)]">
      
      {/* ── Main Content Area ── */}
      <div className="flex-1 flex flex-col min-w-0 min-h-0 bg-background relative">
        {/* ── Top bar ── */}
        <header className="flex shrink-0 items-center justify-between border-b border-border bg-background px-4 sm:px-6 py-3">
          <div className="flex items-center gap-3">
            {/* Brand logo */}
            <div className="flex items-center gap-2.5">
              <div className="relative grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary/15 ring-1 ring-primary/30">
                <Leaf className="h-4 w-4 text-primary" />
                <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-primary" />
              </div>
              <div className="leading-none hidden sm:block">
                <p className="text-sm font-semibold text-foreground">AI Mitra</p>
                <p className="text-[10px] text-muted-foreground">KrishiMitra AI</p>
              </div>
            </div>

            {/* Tab switcher */}
            <div className="sm:ml-2 flex items-center gap-0.5 rounded-lg border border-border bg-surface p-1">
              <button onClick={() => setTab("chat")}
                className={`flex items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 sm:px-3 py-1.5 min-h-[32px] text-xs font-medium transition-all cursor-pointer ${tab === "chat" ? "bg-foreground text-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
                <Sparkles className="h-3 w-3" /> Chat
              </button>
              <button onClick={() => setTab("disease")}
                className={`flex items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 sm:px-3 py-1.5 min-h-[32px] text-xs font-medium transition-all cursor-pointer ${tab === "disease" ? "bg-foreground text-background shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
                <Microscope className="h-3 w-3" /> Scan Leaf
              </button>
            </div>
          </div>
          
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setHistoryOpen(true)}
              className="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-surface-2 hover:text-foreground transition-colors shadow-xs cursor-pointer min-h-[34px]"
              aria-label="View previous chats"
              title="Chat History"
            >
              <History className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">History</span>
            </button>

            <button
              type="button"
              onClick={clear}
              className="flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 px-2.5 py-1.5 text-xs font-semibold transition-colors shadow-xs cursor-pointer min-h-[34px]"
              aria-label="Start new chat"
              title="Start a new chat"
            >
              <Plus className="h-3.5 w-3.5" />
              <span className="whitespace-nowrap"><span className="hidden min-[400px]:inline">New </span>Chat</span>
            </button>
          </div>
        </header>

        {/* ── Body ── */}
        {tab === "disease" ? (
          <div className="flex-1 overflow-hidden">
            <DiseaseScanner token={token} />
          </div>
        ) : (
          <>
            {/* Contextual Task Card (Card-Style 5-state UI) */}
            {contextualTask && (
              <ContextualTaskCard
                task={contextualTask}
                loading={loading}
                onStop={handleInterrupt}
                onRetry={handleRetryContextualTask}
                onDismiss={handleDismissContextualTask}
              />
            )}

            {/* Messages area with scroll tracking ref */}
            <div
              ref={scrollContainerRef}
              onScroll={handleScroll}
              className="flex-1 min-h-0 overflow-y-auto">
              {isEmpty ? (
                /* ── Welcome / suggestions ── */
                <div data-welcome className="flex min-h-full flex-col items-center px-4 py-5 sm:py-8">
                  <div className="my-auto w-full max-w-2xl">
                    {/* Hero */}
                    <div className="mb-5 sm:mb-8 pt-1 text-center">
                      <div className="mx-auto mb-3 sm:mb-4 relative grid h-12 w-12 sm:h-16 sm:w-16 place-items-center rounded-2xl bg-primary/15 ring-1 ring-primary/30 shadow-sm">
                        <Leaf className="h-6 w-6 sm:h-8 sm:w-8 text-primary" />
                        <span className="absolute -right-1 -top-1 h-3 w-3 rounded-full bg-primary pulse-dot" />
                      </div>
                      <h1 className="text-xl sm:text-2xl font-bold text-foreground">How can I help your farm?</h1>
                      <p className="mt-2 text-xs sm:text-sm text-muted-foreground">Ask anything about crops, soil, pests, costs, weather, or schedules.</p>
                    </div>

                    {/* Suggestions */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                      {SUGGESTION_PROMPTS.map((item, idx) => (
                        <button
                          key={idx}
                          onClick={() => send(item.desc)}
                          className="flex items-start gap-3 rounded-2xl border border-border bg-surface p-3 sm:p-3.5 text-left transition-all hover:border-primary/40 hover:bg-surface-2 cursor-pointer group">
                          <span className="text-lg sm:text-xl leading-none mt-0.5">{item.icon}</span>
                          <div className="min-w-0">
                            <p className="text-xs font-semibold text-foreground group-hover:text-primary transition-colors">{item.title}</p>
                            <p className="text-[11px] text-muted-foreground line-clamp-2 mt-0.5">{item.desc}</p>
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                /* ── Message list ── */
                <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:py-8">
                  {messages.map(m => (
                    <Message key={m.id} msg={m} onEdit={handleEdit} onRetry={handleRetry} />
                  ))}
                  <div className="h-6 sm:h-8" />
                </div>
              )}
            </div>

            {/* ── Input bar ── */}
            <div className="shrink-0 px-4 pb-4 sm:pb-5 pt-3 bg-background">
              <div className="mx-auto max-w-3xl">
                {/* Optional Suggestion Chips for Ongoing Conversations */}
                {!isEmpty && !loading && (
                  <div className="mb-2.5 flex items-center gap-1.5 overflow-x-auto py-1 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
                    <span className="text-[11px] font-medium text-muted-foreground shrink-0 flex items-center gap-1 mr-1">
                      <Sparkles className="h-3 w-3 text-primary" /> Suggestions:
                    </span>
                    {[
                      "Wheat fertilizer schedule",
                      "Cotton pest scouting",
                      "Drip irrigation timing",
                      "Soil pH balance tips",
                      "Best crops for clay soil"
                    ].map((chip) => (
                      <button
                        key={chip}
                        type="button"
                        onClick={() => {
                          setInput(chip);
                          textRef.current?.focus();
                        }}
                        className="shrink-0 rounded-full border border-border bg-surface px-3 py-1 text-[11px] text-muted-foreground hover:border-primary/40 hover:text-foreground hover:bg-surface-2 transition-all cursor-pointer shadow-2xs"
                      >
                        {chip}
                      </button>
                    ))}
                  </div>
                )}

                <div className={`relative flex flex-col rounded-3xl border bg-surface transition-all ${loading ? "border-foreground/20" : "border-border focus-within:border-foreground/30 focus-within:shadow-sm"}`}>
                  <input type="file" ref={fileInputRef} hidden accept="image/*" onChange={handleFileChange} />
                  {attachedImage && (
                    <div className="px-5 pt-5 pb-2">
                      <div className="relative inline-block">
                        <img src={attachedImage} alt="Attached" className="h-28 w-28 object-cover rounded-xl border-2 border-primary shadow-md" />
                        <button onClick={() => setAttachedImage(null)} className="absolute -top-3 -right-3 flex h-6 w-6 items-center justify-center bg-foreground text-background rounded-full shadow-md hover:scale-105 transition-transform">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                  )}
                  <style>{`
                    .chat-input-textarea::-webkit-scrollbar {
                      display: none;
                      width: 0px;
                      height: 0px;
                    }
                    .chat-input-textarea {
                      -ms-overflow-style: none;
                      scrollbar-width: none;
                    }
                  `}</style>
                  <textarea
                    ref={textRef}
                    value={input}
                    onChange={e => {
                      setInput(e.target.value);
                      e.target.style.height = "auto";
                      e.target.style.height = Math.max(44, Math.min(e.target.scrollHeight, 200)) + "px";
                    }}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
                    placeholder="Message AI Mitra..."
                    maxLength={4000}
                    disabled={loading}
                    rows={1}
                    className="chat-input-textarea w-full resize-none bg-transparent px-5 pt-4 pb-2 text-sm text-foreground placeholder:text-muted-foreground outline-none leading-7 max-h-[200px] overflow-y-auto [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden disabled:opacity-60"
                    style={{
                      height: "44px",
                      scrollbarWidth: "none",
                      msOverflowStyle: "none",
                    }}
                  />

                  {/* Bottom bar */}
                  <div className="flex items-center justify-between px-3 pb-3 pt-1">
                    <div className="flex items-center gap-0.5" />

                    <button
                      type="button"
                      onClick={loading ? handleInterrupt : handleSend}
                      disabled={(!input.trim() && !attachedImage) && !loading}
                      aria-label={loading ? "Stop generating" : "Send message"}
                      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-all cursor-pointer ${
                        loading
                          ? "bg-foreground text-background hover:opacity-85"
                          : (input.trim() || attachedImage)
                          ? "bg-foreground text-background hover:opacity-85"
                          : "bg-foreground/15 text-muted-foreground cursor-not-allowed"
                      }`}>
                      {loading ? <Square className="h-3.5 w-3.5 fill-current" /> : <Send className="h-3.5 w-3.5" />}
                    </button>
                  </div>
                </div>

                {/* Mobile disclaimer: cleanly formatted on two centered lines */}
                <div className="mt-2 pb-[max(0.625rem,env(safe-area-inset-bottom))] px-4 text-center text-[11px] leading-snug text-muted-foreground/70">
                  <p>AI Mitra may make mistakes.</p>
                  <p>Verify important farming decisions with local experts.</p>
                </div>
              </div>
            </div>
          </>
        )}

        {/* ── Slide-out Conversation History Drawer ── */}
        <HistoryDrawer
          isOpen={historyOpen}
          onClose={() => setHistoryOpen(false)}
          sessions={sessions}
          currentSessionId={sessionId.current}
          onSelectSession={handleSelectSession}
          onDeleteSession={handleDeleteSession}
          onNewChat={clear}
          loading={loadingSessions}
        />
      </div>
    </div>
  );
}
