/**
 * Originally injected into the active tab via chrome.scripting.executeScript({ func }).
 * Kept self-contained (no imports / outer-scope refs) so it can also run inside a
 * sandboxed iframe via Function() for the web analyzeHtml() path.
 */
export function extractPageSeoData(): import("./pageCheckTypes").PageExtractResult {
  const abs = (value: string | null | undefined): string => {
    if (!value) return "";
    try {
      return new URL(value, document.baseURI).href;
    } catch {
      return value;
    }
  };

  const metaContent = (selector: string): string | null => {
    const el = document.querySelector(selector);
    const content = el?.getAttribute("content")?.trim();
    return content || null;
  };

  const title = document.title?.trim() || null;
  const metaDescription =
    metaContent('meta[name="description" i]') ||
    metaContent('meta[property="og:description" i]');
  const canonical =
    document.querySelector('link[rel="canonical" i]')?.getAttribute("href")?.trim() || null;
  const metaRobots =
    metaContent('meta[name="robots" i]') || metaContent('meta[name="googlebot" i]');

  const ogTitle = metaContent('meta[property="og:title" i]');
  const ogDescription = metaContent('meta[property="og:description" i]');
  const ogImage = metaContent('meta[property="og:image" i]');
  const twitterCard =
    metaContent('meta[name="twitter:card" i]') || metaContent('meta[property="twitter:card" i]');
  const twitterTitle =
    metaContent('meta[name="twitter:title" i]') || metaContent('meta[property="twitter:title" i]');

  const htmlLang = document.documentElement.getAttribute("lang")?.trim() || null;

  const faviconPresent = Boolean(
    document.querySelector(
      'link[rel="icon" i], link[rel="shortcut icon" i], link[rel="apple-touch-icon" i], link[rel*="icon" i]',
    ),
  );

  const headings: { tag: "h1" | "h2" | "h3" | "h4" | "h5" | "h6"; text: string }[] = [];
  document.querySelectorAll("h1, h2, h3, h4, h5, h6").forEach((node) => {
    const tag = node.tagName.toLowerCase() as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
    const text = (node.textContent || "").replace(/\s+/g, " ").trim();
    if (text) headings.push({ tag, text });
  });
  const h1Count = headings.filter((h) => h.tag === "h1").length;

  const schemaTypes: string[] = [];
  let schemaBlockCount = 0;
  let schemaParseErrorCount = 0;
  document.querySelectorAll('script[type="application/ld+json"]').forEach((script) => {
    const raw = script.textContent?.trim();
    if (!raw) return;
    schemaBlockCount += 1;
    try {
      const parsed = JSON.parse(raw) as unknown;
      const visit = (node: unknown) => {
        if (!node) return;
        if (Array.isArray(node)) {
          node.forEach(visit);
          return;
        }
        if (typeof node !== "object") return;
        const obj = node as Record<string, unknown>;
        const typeVal = obj["@type"];
        if (typeof typeVal === "string") schemaTypes.push(typeVal);
        else if (Array.isArray(typeVal)) {
          typeVal.forEach((t) => {
            if (typeof t === "string") schemaTypes.push(t);
          });
        }
        if (obj["@graph"]) visit(obj["@graph"]);
      };
      visit(parsed);
    } catch {
      schemaParseErrorCount += 1;
    }
  });

  const imagesMissingAltSamples: string[] = [];
  let imagesMissingAltCount = 0;
  const imagesMissingDimensionsSamples: string[] = [];
  let imagesMissingDimensionsCount = 0;
  document.querySelectorAll("img").forEach((img) => {
    const src = abs(img.getAttribute("src")) || "(no src)";
    const alt = img.getAttribute("alt");
    if (alt === null || alt.trim() === "") {
      imagesMissingAltCount += 1;
      if (imagesMissingAltSamples.length < 8) {
        imagesMissingAltSamples.push(src);
      }
    }

    const widthAttr = img.getAttribute("width");
    const heightAttr = img.getAttribute("height");
    const hasWidth = widthAttr !== null && widthAttr.trim() !== "";
    const hasHeight = heightAttr !== null && heightAttr.trim() !== "";
    if (!hasWidth || !hasHeight) {
      imagesMissingDimensionsCount += 1;
      if (imagesMissingDimensionsSamples.length < 8) {
        imagesMissingDimensionsSamples.push(src);
      }
    }
  });

  const pageHost = location.hostname.replace(/^www\./i, "").toLowerCase();
  let internalLinkCount = 0;
  let externalLinkCount = 0;
  document.querySelectorAll("a[href]").forEach((anchor) => {
    const href = anchor.getAttribute("href")?.trim();
    if (
      !href ||
      href.startsWith("#") ||
      href.startsWith("mailto:") ||
      href.startsWith("tel:") ||
      href.startsWith("javascript:")
    ) {
      return;
    }
    try {
      const url = new URL(href, document.baseURI);
      if (!/^https?:$/i.test(url.protocol)) return;
      const host = url.hostname.replace(/^www\./i, "").toLowerCase();
      if (host === pageHost) internalLinkCount += 1;
      else externalLinkCount += 1;
    } catch {
      // ignore bad hrefs
    }
  });

  const clone = document.body ? (document.body.cloneNode(true) as HTMLElement) : null;
  if (clone) {
    clone
      .querySelectorAll("script, style, noscript, svg, iframe, canvas, template")
      .forEach((el) => el.remove());
  }
  const visibleText = (clone?.innerText || document.body?.innerText || "")
    .replace(/\s+/g, " ")
    .trim();
  const wordCount = visibleText ? visibleText.split(/\s+/).filter(Boolean).length : 0;

  const isHttps = location.protocol === "https:";
  const mixedContentUrls: string[] = [];
  if (isHttps) {
    const attrs = [
      ["img", "src"],
      ["script", "src"],
      ["iframe", "src"],
      ["source", "src"],
      ["video", "src"],
      ["audio", "src"],
      ["link", "href"],
    ] as const;
    for (const [tag, attr] of attrs) {
      document.querySelectorAll(`${tag}[${attr}]`).forEach((el) => {
        const value = el.getAttribute(attr);
        if (!value) return;
        const resolved = abs(value);
        if (resolved.startsWith("http://") && mixedContentUrls.length < 20) {
          mixedContentUrls.push(resolved);
        }
      });
    }
  }

  return {
    url: location.href,
    title,
    metaDescription,
    canonical: canonical ? abs(canonical) : null,
    metaRobots,
    headings,
    h1Count,
    schemaTypes: Array.from(new Set(schemaTypes)),
    schemaBlockCount,
    schemaParseErrorCount,
    imagesMissingAlt: { src: "aggregate", count: imagesMissingAltCount },
    imagesMissingAltSamples,
    imagesMissingDimensionsCount,
    imagesMissingDimensionsSamples,
    internalLinkCount,
    externalLinkCount,
    wordCount,
    isHttps,
    mixedContentUrls: Array.from(new Set(mixedContentUrls)),
    ogTitle,
    ogDescription,
    ogImage,
    twitterCard,
    twitterTitle,
    htmlLang,
    faviconPresent,
  };
}
