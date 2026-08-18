import { getStoredApiBaseUrl } from "./storage";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

/**
 * Resolve FastAPI base URL.
 * Preference order (client): localStorage override → NEXT_PUBLIC_API_BASE_URL → default.
 * On the server, only env / default (localStorage is unavailable).
 */
export function getApiBaseUrl(): string {
  const stored = getStoredApiBaseUrl();
  if (stored) return stored;

  const value = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (typeof value === "string" && value.trim()) {
    return value.trim().replace(/\/$/, "");
  }
  return DEFAULT_API_BASE_URL;
}
