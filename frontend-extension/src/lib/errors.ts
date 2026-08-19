import { getApiBaseUrl } from "./config";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export function isBackendUnreachableError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  if (error.name === "AbortError") return true;
  const message = error.message.toLowerCase();
  return (
    message.includes("failed to fetch") ||
    message.includes("networkerror") ||
    message.includes("network request failed") ||
    message.includes("load failed") ||
    message.includes("err_connection") ||
    message.includes("fetch failed") ||
    message.includes("can't reach backend")
  );
}

export function isTimeoutError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return message.includes("timed out") || message.includes("timeout");
}

/** Extract a human-readable detail from FastAPI / plain error payloads. */
export function parseApiErrorBody(status: number, body: string): string {
  const trimmed = body.trim();
  if (!trimmed) {
    return `Request failed with status ${status}.`;
  }

  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (typeof parsed === "string") return parsed;
    if (parsed && typeof parsed === "object") {
      const detail = (parsed as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        const parts = detail
          .map((item) => {
            if (typeof item === "string") return item;
            if (item && typeof item === "object") {
              const msg = (item as { msg?: unknown }).msg;
              const loc = (item as { loc?: unknown }).loc;
              const where = Array.isArray(loc) ? loc.join(".") : "";
              if (typeof msg === "string") return where ? `${where}: ${msg}` : msg;
            }
            return null;
          })
          .filter(Boolean);
        if (parts.length) return parts.join("; ");
      }
      if ("message" in (parsed as object) && typeof (parsed as { message: unknown }).message === "string") {
        return (parsed as { message: string }).message;
      }
    }
  } catch {
    /* not JSON — fall through */
  }

  // Cap very long HTML/text bodies for UI display.
  return trimmed.length > 400 ? `${trimmed.slice(0, 400)}…` : trimmed;
}

export function formatBackendError(error: unknown): string {
  const baseUrl = getApiBaseUrl();

  if (isTimeoutError(error)) {
    return `Request timed out talking to ${baseUrl}. The backend may be busy generating a report or crawling — try again in a moment, or check Settings.`;
  }

  if (isBackendUnreachableError(error)) {
    return `Can't reach backend at ${baseUrl} — make sure it's running (uvicorn app.main:app) or update the URL in Settings`;
  }

  if (error instanceof ApiError) {
    if (error.status === 404) {
      return error.detail || "The requested resource was not found.";
    }
    if (error.status === 409) {
      return error.detail || "This action conflicts with the current crawl state.";
    }
    if (error.status >= 500) {
      return `Backend error (${error.status}): ${error.detail}`;
    }
    return error.detail || `Request failed (${error.status}).`;
  }

  return error instanceof Error ? error.message : "Something went wrong.";
}

/** True when the UI should offer a Settings deep-link (connectivity problems). */
export function shouldLinkToSettings(error: unknown): boolean {
  return isBackendUnreachableError(error) || isTimeoutError(error);
}
