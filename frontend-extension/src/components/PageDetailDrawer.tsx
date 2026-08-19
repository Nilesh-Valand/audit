import { useEffect, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ExternalLink,
  FileText,
  Globe,
  HelpCircle,
  Layers,
  RefreshCw,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { apiClient, type AiContentScan, type SinglePageDetail } from "@/lib/api";
import { formatBackendError } from "@/lib/errors";

function SeverityBadge({ severity }: { severity: string }) {
  const key = severity.toLowerCase();
  const cls =
    key === "critical" || key === "high"
      ? "bg-red-100 text-red-800 border-red-200"
      : key === "medium"
        ? "bg-amber-100 text-amber-800 border-amber-200"
        : "bg-sky-100 text-sky-800 border-sky-200";
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold capitalize ${cls}`}
    >
      {severity}
    </span>
  );
}

function StatusCodePill({ code }: { code: number | null | undefined }) {
  if (code == null) return <span className="text-gray-400">—</span>;
  const tone =
    code >= 200 && code < 300
      ? "bg-emerald-100 text-emerald-800 border-emerald-200"
      : code >= 300 && code < 400
        ? "bg-amber-100 text-amber-800 border-amber-200"
        : "bg-red-100 text-red-800 border-red-200";
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-0.5 text-xs font-semibold tabular-nums ${tone}`}>
      {code}
    </span>
  );
}

export function PageDetailDrawer({
  crawlRunId,
  pageId,
  onClose,
}: {
  crawlRunId: number;
  pageId: number | null;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<SinglePageDetail | null>(null);
  const [aiScan, setAiScan] = useState<AiContentScan | null>(null);
  const [loading, setLoading] = useState(false);
  const [scanningAi, setScanningAi] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "technical" | "issues" | "ai">(
    "overview",
  );

  useEffect(() => {
    if (pageId == null) {
      setDetail(null);
      setAiScan(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    apiClient
      .getPageDetail(crawlRunId, pageId)
      .then((res) => {
        if (cancelled) return;
        setDetail(res);
        if (res.ai_content_scan) {
          setAiScan(res.ai_content_scan);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setError(formatBackendError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [crawlRunId, pageId]);

  // Handle escape key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  async function handleRunAiScan() {
    if (pageId == null) return;
    setScanningAi(true);
    try {
      const scanRes = await apiClient.scanPageAiContent(crawlRunId, pageId);
      setAiScan(scanRes);
    } catch (err) {
      setError(formatBackendError(err));
    } finally {
      setScanningAi(false);
    }
  }

  if (pageId == null) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-slate-900/40 backdrop-blur-xs transition-opacity">
      <div className="absolute inset-0" onClick={onClose} />

      <aside className="absolute inset-y-0 right-0 flex max-w-full pl-10">
        <div className="w-screen max-w-2xl bg-white shadow-2xl flex flex-col border-l border-slate-200">
          {/* Top Bar Header */}
          <div className="border-b border-slate-100 px-6 py-5 flex items-start justify-between gap-4 bg-slate-50/60">
            <div className="space-y-1 min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold text-slate-900 truncate">
                  {detail?.title || (loading ? "Loading page details…" : "Page Details")}
                </h2>
                {detail?.status_code != null && <StatusCodePill code={detail.status_code} />}
              </div>
              {detail?.url && (
                <div className="flex items-center gap-2">
                  <a
                    href={detail.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-mono text-brand-600 hover:underline truncate inline-flex items-center gap-1"
                  >
                    <span>{detail.url}</span>
                    <ExternalLink className="h-3 w-3 shrink-0" />
                  </a>
                </div>
              )}
            </div>

            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200/60 hover:text-slate-700 transition"
              aria-label="Close panel"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Navigation Tabs */}
          <div className="border-b border-slate-100 px-6 bg-white flex gap-6 text-sm font-medium overflow-x-auto">
            <button
              type="button"
              onClick={() => setActiveTab("overview")}
              className={`py-3 border-b-2 transition shrink-0 ${
                activeTab === "overview"
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              Overview & Content
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("technical")}
              className={`py-3 border-b-2 transition shrink-0 ${
                activeTab === "technical"
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              Technical & Social
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("issues")}
              className={`py-3 border-b-2 transition shrink-0 inline-flex items-center gap-1.5 ${
                activeTab === "issues"
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              <span>Issues</span>
              {detail?.issues && detail.issues.length > 0 && (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                  {detail.issues.length}
                </span>
              )}
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("ai")}
              className={`py-3 border-b-2 transition shrink-0 inline-flex items-center gap-1.5 ${
                activeTab === "ai"
                  ? "border-brand-600 text-brand-700"
                  : "border-transparent text-slate-500 hover:text-slate-800"
              }`}
            >
              <Sparkles className="h-3.5 w-3.5 text-amber-500" />
              <span>AI Content Scan</span>
              {aiScan && (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">
                  {aiScan.overall_pct}%
                </span>
              )}
            </button>
          </div>

          {/* Body Content */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {loading ? (
              <div className="flex items-center justify-center py-16 text-sm text-slate-500 gap-2">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand-600 border-t-transparent" />
                <span>Loading page details…</span>
              </div>
            ) : error ? (
              <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                {error}
              </div>
            ) : detail ? (
              <>
                {/* TAB 1: OVERVIEW & CONTENT */}
                {activeTab === "overview" && (
                  <div className="space-y-5">
                    {/* Metrics Grid */}
                    <div className="grid grid-cols-3 gap-3">
                      <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                        <span className="text-xs font-medium text-slate-500">Word Count</span>
                        <p className="mt-1 text-lg font-semibold text-slate-900">
                          {detail.word_count ?? "—"}
                        </p>
                      </div>
                      <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                        <span className="text-xs font-medium text-slate-500">Response Time</span>
                        <p className="mt-1 text-lg font-semibold text-slate-900">
                          {detail.response_time_ms != null
                            ? `${Math.round(detail.response_time_ms)} ms`
                            : "—"}
                        </p>
                      </div>
                      <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5">
                        <span className="text-xs font-medium text-slate-500">Indexable</span>
                        <p className="mt-1 text-sm font-semibold">
                          {detail.is_indexable ? (
                            <span className="text-emerald-700">Yes</span>
                          ) : (
                            <span className="text-red-600">No (Noindex)</span>
                          )}
                        </p>
                      </div>
                    </div>

                    {/* Metadata Card */}
                    <div className="rounded-xl border border-slate-200 p-4 space-y-4">
                      <div>
                        <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">
                          Page Title
                        </span>
                        <p className="mt-1 text-sm font-medium text-slate-900">
                          {detail.title || <span className="text-slate-400">Missing</span>}
                        </p>
                      </div>

                      <div>
                        <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">
                          Meta Description
                        </span>
                        <p className="mt-1 text-sm text-slate-700 leading-relaxed">
                          {detail.meta_description || (
                            <span className="text-slate-400">Missing meta description</span>
                          )}
                        </p>
                      </div>

                      <div className="grid grid-cols-2 gap-4 pt-2 border-t border-slate-100">
                        <div>
                          <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">
                            Canonical URL
                          </span>
                          <p className="mt-1 text-xs font-mono text-slate-800 truncate">
                            {detail.canonical_url || <span className="text-slate-400">None</span>}
                          </p>
                        </div>
                        <div>
                          <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">
                            Meta Robots
                          </span>
                          <p className="mt-1 text-xs font-mono text-slate-800">
                            {detail.meta_robots || <span className="text-slate-400">Default (index, follow)</span>}
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* Headings Structure */}
                    <div className="rounded-xl border border-slate-200 p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                          <FileText className="h-4 w-4 text-brand-600" />
                          <span>H1 Headings</span>
                        </span>
                        <span className="text-xs text-slate-500 font-mono">
                          {detail.h1_list?.length || (detail.h1 ? 1 : 0)} found
                        </span>
                      </div>
                      {detail.h1_list && detail.h1_list.length > 0 ? (
                        <ul className="space-y-1.5 pl-3 border-l-2 border-brand-200">
                          {detail.h1_list.map((h, idx) => (
                            <li key={idx} className="text-xs font-medium text-slate-800">
                              {h}
                            </li>
                          ))}
                        </ul>
                      ) : detail.h1 ? (
                        <p className="text-xs font-medium text-slate-800 pl-3 border-l-2 border-brand-200">
                          {detail.h1}
                        </p>
                      ) : (
                        <p className="text-xs text-amber-700 bg-amber-50 p-2.5 rounded-lg border border-amber-100">
                          No H1 heading tag found on this page.
                        </p>
                      )}
                    </div>
                  </div>
                )}

                {/* TAB 2: TECHNICAL & SOCIAL */}
                {activeTab === "technical" && (
                  <div className="space-y-5">
                    {/* Open Graph Card */}
                    <div className="rounded-xl border border-slate-200 p-4 space-y-3">
                      <h3 className="text-xs font-semibold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                        <Globe className="h-4 w-4 text-sky-600" />
                        <span>Open Graph (Social Preview)</span>
                      </h3>
                      <div className="space-y-2 text-xs">
                        <div>
                          <span className="font-medium text-slate-500">og:title:</span>{" "}
                          <span className="text-slate-800 font-mono">{detail.og_title || "—"}</span>
                        </div>
                        <div>
                          <span className="font-medium text-slate-500">og:description:</span>{" "}
                          <span className="text-slate-800">{detail.og_description || "—"}</span>
                        </div>
                        {detail.og_image && (
                          <div>
                            <span className="font-medium text-slate-500 block mb-1">og:image:</span>
                            <img
                              src={detail.og_image}
                              alt="Open Graph Preview"
                              className="max-h-36 rounded-lg border border-slate-200 object-cover"
                              onError={(e) => (e.currentTarget.style.display = "none")}
                            />
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Technical Signals Grid */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5 space-y-1">
                        <span className="text-xs text-slate-500">HTML Language</span>
                        <p className="text-sm font-semibold text-slate-800 font-mono">
                          {detail.html_lang || "Not specified"}
                        </p>
                      </div>
                      <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5 space-y-1">
                        <span className="text-xs text-slate-500">Favicon Link</span>
                        <p className="text-sm font-semibold text-slate-800">
                          {detail.favicon_present ? "Present" : "Missing"}
                        </p>
                      </div>
                      <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5 space-y-1">
                        <span className="text-xs text-slate-500">Head Scripts</span>
                        <p className="text-sm font-semibold text-slate-800 tabular-nums">
                          {detail.render_blocking_scripts_in_head} render-blocking
                        </p>
                      </div>
                      <div className="rounded-xl border border-slate-100 bg-slate-50/60 p-3.5 space-y-1">
                        <span className="text-xs text-slate-500">Head Stylesheets</span>
                        <p className="text-sm font-semibold text-slate-800 tabular-nums">
                          {detail.stylesheets_in_head}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* TAB 3: ISSUES */}
                {activeTab === "issues" && (
                  <div className="space-y-3">
                    {detail.issues.length === 0 ? (
                      <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-5 text-center space-y-1">
                        <CheckCircle2 className="h-6 w-6 text-emerald-600 mx-auto" />
                        <p className="text-sm font-semibold text-emerald-900">
                          No issues detected on this page!
                        </p>
                        <p className="text-xs text-emerald-700">
                          All automated SEO checks passed cleanly for this URL.
                        </p>
                      </div>
                    ) : (
                      detail.issues.map((issue) => (
                        <div
                          key={issue.id}
                          className="rounded-xl border border-slate-200 bg-white p-4 space-y-2"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-semibold font-mono text-slate-700">
                              {issue.rule_id}
                            </span>
                            <SeverityBadge severity={issue.severity} />
                          </div>
                          <p className="text-sm font-medium text-slate-900">{issue.message}</p>
                        </div>
                      ))
                    )}
                  </div>
                )}

                {/* TAB 4: RULE-BASED AI CONTENT DETECTOR & SUGGESTIONS */}
                {activeTab === "ai" && (
                  <div className="space-y-6">
                    {/* Header Verdict Card */}
                    <div className="rounded-2xl border border-amber-200 bg-gradient-to-br from-amber-50/90 via-orange-50/50 to-yellow-50/90 p-5 space-y-4 shadow-sm">
                      <div className="flex items-center justify-between gap-4">
                        <div className="flex items-center gap-3">
                          <div className="rounded-xl bg-amber-500 p-2.5 text-white shadow-sm">
                            <Sparkles className="h-6 w-6" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <h3 className="text-base font-bold text-amber-950">
                                Rule-Based AI Content Verdict
                              </h3>
                              <span className="rounded-md bg-amber-200/80 px-2 py-0.5 text-[10px] font-bold text-amber-900">
                                Deterministic Rules
                              </span>
                            </div>
                            <p className="text-xs text-amber-800">
                              Evaluated with 8 linguistic rules (no LLM score bias)
                            </p>
                          </div>
                        </div>

                        <button
                          type="button"
                          onClick={handleRunAiScan}
                          disabled={scanningAi}
                          className="rounded-xl bg-amber-600 px-3.5 py-2 text-xs font-semibold text-white shadow-xs hover:bg-amber-700 disabled:opacity-60 inline-flex items-center gap-1.5"
                        >
                          <RefreshCw className={`h-3.5 w-3.5 ${scanningAi ? "animate-spin" : ""}`} />
                          <span>{scanningAi ? "Scanning…" : "Re-run Rule Scan"}</span>
                        </button>
                      </div>

                      {aiScan && (
                        <div className="grid grid-cols-3 gap-3 pt-1">
                          <div className="rounded-xl bg-white/90 p-3.5 border border-amber-100 shadow-2xs">
                            <span className="text-xs font-medium text-amber-800">AI Likelihood Score</span>
                            <div className="mt-1 flex items-baseline gap-1">
                              <span className="text-2xl font-bold text-amber-950 tabular-nums">
                                {aiScan.overall_pct}%
                              </span>
                            </div>
                          </div>
                          <div className="rounded-xl bg-white/90 p-3.5 border border-amber-100 shadow-2xs">
                            <span className="text-xs font-medium text-amber-800">Confidence Rating</span>
                            <p className="mt-1 text-lg font-bold text-amber-950">
                              {aiScan.confidence}
                            </p>
                          </div>
                          <div className="rounded-xl bg-white/90 p-3.5 border border-amber-100 shadow-2xs">
                            <span className="text-xs font-medium text-amber-800">Words Scanned</span>
                            <p className="mt-1 text-lg font-bold text-amber-950 tabular-nums">
                              {aiScan.word_count}
                            </p>
                          </div>
                        </div>
                      )}
                    </div>

                    {aiScan && (
                      <>
                        {/* Detected Rule Patterns */}
                        <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
                          <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                            <Layers className="h-4 w-4 text-brand-600" />
                            <span>8 Evaluated Rule Patterns</span>
                          </h4>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                            {aiScan.detected_patterns.map((p, idx) => (
                              <div
                                key={idx}
                                className="rounded-lg border border-slate-100 bg-slate-50/60 p-3 flex flex-col justify-between space-y-1.5"
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <span className="text-xs font-semibold text-slate-900">{p.pattern}</span>
                                  <SeverityBadge severity={p.severity} />
                                </div>
                                {p.examples && p.examples.length > 0 ? (
                                  <div className="text-[11px] font-mono text-slate-600 bg-white p-1.5 rounded border border-slate-100 truncate">
                                    {p.examples.join(", ")}
                                  </div>
                                ) : (
                                  <span className="text-[11px] text-slate-400">No flag threshold reached</span>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Actionable Suggestions & Improved Directions */}
                        <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
                          <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                            <Zap className="h-4 w-4 text-amber-600" />
                            <span>Improvement Suggestions & Directions</span>
                          </h4>
                          {aiScan.suggestions.length === 0 ? (
                            <p className="text-xs text-slate-500">
                              No generic or robotic sentence patterns requiring rewrites.
                            </p>
                          ) : (
                            <div className="space-y-3">
                              {aiScan.suggestions.map((s, idx) => (
                                <div
                                  key={idx}
                                  className="rounded-xl border border-amber-100 bg-amber-50/40 p-3.5 space-y-2 text-xs"
                                >
                                  {s.detected_sentence && (
                                    <div className="font-medium text-slate-900 italic border-l-2 border-amber-400 pl-2">
                                      "{s.detected_sentence}"
                                    </div>
                                  )}
                                  <div className="text-amber-900">
                                    <strong>Issue:</strong> {s.issue}
                                  </div>
                                  <div className="text-slate-800">
                                    <strong>Suggestion:</strong> {s.suggestion}
                                  </div>
                                  {s.improved_direction && (
                                    <div className="rounded-lg bg-white p-2.5 border border-amber-200/60 text-slate-900">
                                      <strong className="text-emerald-700 block mb-0.5">
                                        Improved Direction:
                                      </strong>
                                      {s.improved_direction}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* Sentence-by-Sentence Breakdown */}
                        {aiScan.sentence_scores.length > 0 && (
                          <div className="rounded-xl border border-slate-200 bg-white p-4 space-y-3">
                            <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                              <FileText className="h-4 w-4 text-sky-600" />
                              <span>Sentence-by-Sentence AI Heatmap</span>
                            </h4>
                            <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                              {aiScan.sentence_scores.map((sent) => {
                                const tone =
                                  sent.ai_likelihood >= 60
                                    ? "bg-red-50 text-red-900 border-red-200"
                                    : sent.ai_likelihood >= 30
                                      ? "bg-amber-50 text-amber-900 border-amber-200"
                                      : "bg-slate-50 text-slate-800 border-slate-100";
                                return (
                                  <div
                                    key={sent.index}
                                    className={`rounded-lg border p-2.5 text-xs space-y-1 ${tone}`}
                                  >
                                    <div className="flex items-center justify-between font-mono text-[10px] opacity-75">
                                      <span>Sentence #{sent.index}</span>
                                      <span>{sent.ai_likelihood}% AI likelihood</span>
                                    </div>
                                    <p className="font-medium leading-relaxed">{sent.text}</p>
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </>
            ) : null}
          </div>
        </div>
      </aside>
    </div>
  );
}
