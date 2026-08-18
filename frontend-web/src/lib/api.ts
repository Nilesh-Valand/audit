import { getApiBaseUrl } from "./config";
import { ApiError, parseApiErrorBody } from "./errors";

export { getApiBaseUrl } from "./config";

const DEFAULT_TIMEOUT_MS = 12_000;

export type PaginatedResponse<T> = {
  total: number;
  page: number;
  page_size: number;
  items: T[];
};

export type Project = {
  id: number;
  domain: string;
  created_at: string;
  latest_run_id?: number | null;
  latest_run_status?: string | null;
  latest_run_finished_at?: string | null;
  latest_run_started_at?: string | null;
  overall_score?: number | null;
};

export type CrawlRun = {
  id: number;
  project_id: number;
  status: string;
  total_pages: number;
  started_at: string | null;
  finished_at: string | null;
};

export type CrawlRunProgress = {
  id: number;
  project_id: number;
  status: string;
  pages_crawled: number;
  max_pages?: number | null;
  started_at: string | null;
  finished_at: string | null;
  active: boolean;
  phase?: string | null;
  phase_current?: number | null;
  phase_total?: number | null;
  phase_label?: string | null;
  error_message?: string | null;
};

export type CrawlRunSummary = {
  overall_score: number | null;
  category_scores: Record<string, number>;
  total_pages: number;
  total_issues_by_severity: Record<string, number>;
};

export type ScoreItem = {
  category: string;
  score: number;
};

export type PageVitals = {
  mobile_performance_score: number | null;
  mobile_lcp_ms: number | null;
  mobile_inp_ms: number | null;
  mobile_cls: number | null;
  desktop_performance_score: number | null;
  desktop_lcp_ms: number | null;
  desktop_inp_ms: number | null;
  desktop_cls: number | null;
};

export type PageDetails = {
  id: number;
  url: string;
  title: string | null;
  meta_description: string | null;
  canonical_url: string | null;
  word_count: number | null;
  status_code: number | null;
  response_time_ms: number | null;
  vitals: PageVitals | null;
};

export type AuditIssue = {
  id: number;
  rule_id: string;
  category: string;
  severity: string;
  target_url: string | null;
  message: string;
  page_details: PageDetails | null;
};

export type CrawledPage = {
  id: number;
  url: string;
  title: string | null;
  status_code: number | null;
  word_count: number | null;
  response_time_ms: number | null;
  issue_count: number;
};

export type AuditReport = {
  project: { id: number; domain: string | null };
  crawl_date: string | null;
  overall_score: number | null;
  category_scores: Record<string, number>;
  summary: {
    total_pages: number;
    total_issues: number;
    site_issue_count: number;
    pages_with_issues: number;
    page_issue_count: number;
    summary_text: string;
    issues_by_severity: Record<string, number>;
  };
  site_issues: {
    id: string;
    rule: string;
    severity: string;
    category: string;
    message: string;
    scope: string;
  }[];
  page_issues: {
    url: string;
    issue_count: number;
    issues: {
      id: string;
      rule: string;
      severity: string;
      category: string;
      message: string;
      scope: string;
    }[];
  }[];
  categories: {
    name: string;
    score: number | null;
    issues: {
      url: string | null;
      rule: string;
      severity: string;
      message: string;
      scope?: string | null;
      category?: string | null;
      id?: string | null;
    }[];
  }[];
  recommendations: {
    rule: string;
    severity: string;
    category: string;
    message: string;
    pages_affected: number;
  }[];
};

export type ScoreHistoryItem = {
  crawl_run_id: number;
  date: string | null;
  overall_score: number | null;
  category_scores: Record<string, number>;
};

export type DiffIssue = {
  rule_id: string;
  category: string;
  severity: string;
  target_url: string | null;
  message: string;
};

export type CrawlRunDiff = {
  current_run_id: number;
  compare_to_run_id: number;
  new_issues: DiffIssue[];
  resolved_issues: DiffIssue[];
  persisting_issues: DiffIssue[];
  counts: {
    new: number;
    resolved: number;
    persisting: number;
  };
};

/** Response from POST /api/page-html (server-side page fetch for Current Page Check). */
export type PageHtmlResponse = {
  url: string;
  final_url: string;
  status_code: number;
  content_type: string | null;
  html: string;
};

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  timeoutMs?: number;
};

function buildUrl(path: string, query?: RequestOptions["query"]) {
  const base = getApiBaseUrl();
  const url = new URL(`${base}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { body, query, timeoutMs = DEFAULT_TIMEOUT_MS, ...rest } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(buildUrl(path, query), {
      ...rest,
      signal: rest.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(rest.headers ?? {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });

    if (!res.ok) {
      const errorText = await res.text();
      throw new ApiError(res.status, parseApiErrorBody(res.status, errorText));
    }

    if (res.status === 204) {
      return undefined as T;
    }

    const text = await res.text();
    if (!text) {
      return undefined as T;
    }

    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ApiError(res.status, "Backend returned invalid JSON.");
    }
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s (${path})`);
    }
    if (
      error instanceof TypeError ||
      (error instanceof Error && /failed to fetch|networkerror|fetch failed/i.test(error.message))
    ) {
      throw new Error(`Failed to fetch ${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", body }),
  delete: <T = void>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "DELETE" }),
};

export type ExportFormat = "pdf" | "csv" | "xlsx";

const EXPORT_META: Record<
  ExportFormat,
  { pathSuffix: string; mime: string; defaultExt: string; timeoutMs: number }
> = {
  pdf: {
    pathSuffix: "pdf",
    mime: "application/pdf",
    defaultExt: "pdf",
    timeoutMs: 180_000,
  },
  csv: {
    pathSuffix: "csv",
    mime: "text/csv",
    defaultExt: "csv",
    timeoutMs: 60_000,
  },
  xlsx: {
    pathSuffix: "xlsx",
    mime: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    defaultExt: "xlsx",
    timeoutMs: 120_000,
  },
};

function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;
  const utfMatch = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (utfMatch?.[1]) {
    try {
      return decodeURIComponent(utfMatch[1].trim());
    } catch {
      /* fall through */
    }
  }
  const plainMatch = /filename="?([^";]+)"?/i.exec(header);
  if (plainMatch?.[1]) return plainMatch[1].trim();
  return fallback;
}

/**
 * Fetch an export endpoint as a blob and trigger a browser download
 * (replaces chrome.downloads.download).
 */
export async function downloadCrawlExport(
  crawlRunId: number,
  format: ExportFormat,
): Promise<void> {
  const meta = EXPORT_META[format];
  const path = `/api/crawl-runs/${crawlRunId}/export/${meta.pathSuffix}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), meta.timeoutMs);

  let blobUrl: string | null = null;

  try {
    const res = await fetch(buildUrl(path), {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new ApiError(res.status, parseApiErrorBody(res.status, text));
    }

    const blob = await res.blob();
    const fallbackName = `crawl-run-${crawlRunId}-export.${meta.defaultExt}`;
    const filename = filenameFromDisposition(
      res.headers.get("Content-Disposition"),
      fallbackName,
    );

    blobUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = blobUrl;
    anchor.download = filename;
    anchor.rel = "noopener";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`Export timed out after ${meta.timeoutMs / 1000}s (${format.toUpperCase()})`);
    }
    if (
      error instanceof TypeError ||
      (error instanceof Error && /failed to fetch|networkerror|fetch failed/i.test(error.message))
    ) {
      throw new Error(`Failed to fetch ${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
    if (blobUrl) {
      window.setTimeout(() => URL.revokeObjectURL(blobUrl!), 60_000);
    }
  }
}

export const apiClient = {
  health: () => api.get<{ status: string }>("/api/health"),
  listProjects: (query?: { page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<Project>>("/api/projects", { query }),
  createProject: (domain: string) => api.post<Project>("/api/projects", { domain }),
  deleteProject: (id: number) => api.delete(`/api/projects/${id}`),
  listCrawlRuns: (query?: { project_id?: number; page?: number; page_size?: number }) =>
    api.get<PaginatedResponse<CrawlRun>>("/api/crawl-runs", { query }),
  createCrawlRun: (payload: {
    project_id: number;
    start_url: string;
    max_pages: number;
    max_depth?: number;
    enable_pagespeed?: boolean | null;
  }) =>
    api.post<{ crawl_run_id: number; status: string }>("/api/crawl-runs", payload, {
      timeoutMs: 30_000,
    }),
  deleteCrawlRun: (id: number) => api.delete(`/api/crawl-runs/${id}`),
  getCrawlRun: (id: number) =>
    api.get<CrawlRunProgress>(`/api/crawl-runs/${id}`, { timeoutMs: 15_000 }),
  runAudit: (id: number) =>
    api.post<{ crawl_run_id: number; issues_created: number; scores_created: number }>(
      `/api/crawl-runs/${id}/run-audit`,
      undefined,
      { timeoutMs: 120_000 },
    ),
  getSummary: (id: number) =>
    api.get<CrawlRunSummary>(`/api/crawl-runs/${id}/summary`, { timeoutMs: 30_000 }),
  getReport: (id: number) =>
    api.get<AuditReport>(`/api/crawl-runs/${id}/report`, { timeoutMs: 60_000 }),
  getScores: (id: number) => api.get<{ items: ScoreItem[] }>(`/api/crawl-runs/${id}/scores`),
  getScoreHistory: (projectId: number) =>
    api.get<{ items: ScoreHistoryItem[] }>(`/api/projects/${projectId}/score-history`),
  getCrawlRunDiff: (id: number, compareTo: number) =>
    api.get<CrawlRunDiff>(`/api/crawl-runs/${id}/diff`, { query: { compare_to: compareTo } }),
  getIssues: (
    id: number,
    query?: { category?: string; severity?: string; page?: number; page_size?: number },
  ) => api.get<PaginatedResponse<AuditIssue>>(`/api/crawl-runs/${id}/issues`, { query }),
  getPages: (
    id: number,
    query?: {
      status_code?: number;
      issue_category?: string;
      search?: string;
      sort_by?: string;
      sort_order?: string;
      page?: number;
      page_size?: number;
    },
  ) => api.get<PaginatedResponse<CrawledPage>>(`/api/crawl-runs/${id}/pages`, { query }),
  /**
   * Server-side HTML fetch for Current Page Check.
   * Requires FastAPI `POST /api/page-html` (not implemented yet — see page contract).
   */
  fetchPageHtml: (url: string) =>
    api.post<PageHtmlResponse>(
      "/api/page-html",
      { url },
      { timeoutMs: 60_000 },
    ),
  downloadExport: downloadCrawlExport,
};
