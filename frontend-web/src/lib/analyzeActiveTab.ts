import { extractPageSeoData } from "./extractPageSeoData";
import type { PageExtractResult } from "./pageCheckTypes";

/** Minimal tab shape — replaces chrome.tabs.Tab (Phase 2). */
export type TabInfo = {
  id?: number;
  url?: string;
  title?: string | null;
};

function isHttpUrl(url: string | undefined): boolean {
  return Boolean(url && /^https?:\/\//i.test(url));
}

function ensureBaseHref(html: string, pageUrl: string): string {
  if (/<base\b/i.test(html)) return html;
  if (/<head[^>]*>/i.test(html)) {
    return html.replace(/<head([^>]*)>/i, `<head$1><base href="${pageUrl}">`);
  }
  return `<head><base href="${pageUrl}"></head>${html}`;
}

/**
 * Run the same extractPageSeoData logic against fetched HTML inside a sandboxed
 * iframe (replaces chrome.scripting.executeScript / analyzeActiveTab).
 */
export async function analyzeHtml(
  html: string,
  pageUrl: string,
): Promise<{ tab: TabInfo; data: PageExtractResult }> {
  if (typeof window === "undefined" || typeof document === "undefined") {
    throw new Error("analyzeHtml() must run in the browser.");
  }
  if (!isHttpUrl(pageUrl)) {
    throw new Error("Cannot inject into browser internal pages. Open a normal website tab.");
  }

  const prepared = ensureBaseHref(html, pageUrl);

  return new Promise((resolve, reject) => {
    const iframe = document.createElement("iframe");
    iframe.setAttribute("sandbox", "allow-same-origin");
    iframe.style.cssText =
      "position:fixed;left:-99999px;top:0;width:1px;height:1px;opacity:0;border:0";

    const blob = new Blob([prepared], { type: "text/html" });
    const blobUrl = URL.createObjectURL(blob);

    const cleanup = () => {
      URL.revokeObjectURL(blobUrl);
      iframe.remove();
    };

    iframe.onload = () => {
      try {
        const win = iframe.contentWindow;
        if (!win) {
          throw new Error("Content script returned no data. The page may block script injection.");
        }
        const iframeFunction = (
          win as unknown as {
            Function: new (...args: string[]) => (...fnArgs: unknown[]) => unknown;
          }
        ).Function;
        const run = new iframeFunction(`return (${extractPageSeoData.toString()})();`);
        const data = run() as PageExtractResult;
        if (!data) {
          throw new Error("Content script returned no data. The page may block script injection.");
        }
        data.url = pageUrl;
        resolve({
          tab: { url: pageUrl, title: data.title },
          data,
        });
      } catch (error) {
        reject(error instanceof Error ? error : new Error(String(error)));
      } finally {
        cleanup();
      }
    };

    iframe.onerror = () => {
      cleanup();
      reject(new Error("Content script returned no data. The page may block script injection."));
    };

    document.body.appendChild(iframe);
    iframe.src = blobUrl;
  });
}
