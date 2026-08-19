import type { PageExtractResult, PageRuleResult, RuleSeverity } from "./pageCheckTypes";

type RuleDef = {
  id: string;
  category: string;
  severity: RuleSeverity;
  description: string;
  check: (data: PageExtractResult) => { passed: boolean; message: string };
};

const RULES: RuleDef[] = [
  {
    id: "missing_title",
    category: "technical",
    severity: "high",
    description: "Page is missing a title tag.",
    check: (data) => ({
      passed: Boolean(data.title?.trim()),
      message: data.title?.trim()
        ? `Title present (${data.title.trim().length} chars).`
        : "No document title found.",
    }),
  },
  {
    id: "missing_meta_description",
    category: "technical",
    severity: "medium",
    description: "Page is missing a meta description.",
    check: (data) => ({
      passed: Boolean(data.metaDescription?.trim()),
      message: data.metaDescription?.trim()
        ? `Meta description present (${data.metaDescription.trim().length} chars).`
        : "No meta description found.",
    }),
  },
  {
    id: "missing_h1",
    category: "technical",
    severity: "medium",
    description: "Page is missing an H1 heading.",
    check: (data) => ({
      passed: data.h1Count > 0,
      message:
        data.h1Count > 0
          ? `Found ${data.h1Count} H1 heading(s).`
          : "No H1 heading found on the page.",
    }),
  },
  {
    id: "multiple_h1",
    category: "technical",
    severity: "low",
    description: "Page contains multiple H1 headings.",
    check: (data) => ({
      passed: data.h1Count <= 1,
      message:
        data.h1Count <= 1
          ? "Single H1 (or none — see missing_h1)."
          : `Found ${data.h1Count} H1 headings; prefer one primary H1.`,
    }),
  },
  {
    id: "missing_schema",
    category: "structured_data",
    severity: "medium",
    description: "Page type likely needs schema but none was found.",
    check: (data) => ({
      passed: data.schemaTypes.length > 0,
      message:
        data.schemaTypes.length > 0
          ? `JSON-LD types: ${data.schemaTypes.join(", ")}.`
          : "No JSON-LD @type values detected.",
    }),
  },
  {
    id: "images_missing_alt",
    category: "accessibility",
    severity: "medium",
    description: "Images are missing alt attributes.",
    check: (data) => ({
      passed: data.imagesMissingAlt.count === 0,
      message:
        data.imagesMissingAlt.count === 0
          ? "All images have alt attributes."
          : `${data.imagesMissingAlt.count} image(s) missing alt text.`,
    }),
  },
  {
    id: "mixed_content",
    category: "security",
    severity: "critical",
    description: "HTTPS page references insecure HTTP resources.",
    check: (data) => {
      if (!data.isHttps) {
        return { passed: true, message: "Page is not HTTPS; mixed-content rule skipped." };
      }
      return {
        passed: data.mixedContentUrls.length === 0,
        message:
          data.mixedContentUrls.length === 0
            ? "No http:// subresources found on this HTTPS page."
            : `${data.mixedContentUrls.length} insecure http:// resource(s) found.`,
      };
    },
  },
  {
    id: "missing_og_tags",
    category: "on_page",
    severity: "medium",
    description: "Open Graph tags og:title, og:description, or og:image are missing.",
    check: (data) => {
      const missing: string[] = [];
      if (!data.ogTitle?.trim()) missing.push("og:title");
      if (!data.ogDescription?.trim()) missing.push("og:description");
      if (!data.ogImage?.trim()) missing.push("og:image");
      return {
        passed: missing.length === 0,
        message:
          missing.length === 0
            ? "Open Graph og:title, og:description, and og:image are present."
            : `Missing Open Graph tag(s): ${missing.join(", ")}.`,
      };
    },
  },
  {
    id: "missing_twitter_card",
    category: "on_page",
    severity: "low",
    description: "Twitter card tags are missing.",
    check: (data) => {
      const missing: string[] = [];
      if (!data.twitterCard?.trim()) missing.push("twitter:card");
      if (!data.twitterTitle?.trim()) missing.push("twitter:title");
      return {
        passed: missing.length === 0,
        message:
          missing.length === 0
            ? "Twitter card and title tags are present."
            : `Missing Twitter card tag(s): ${missing.join(", ")}.`,
      };
    },
  },
  {
    id: "missing_html_lang",
    category: "on_page",
    severity: "medium",
    description: "html lang attribute is missing.",
    check: (data) => ({
      passed: Boolean(data.htmlLang?.trim()),
      message: data.htmlLang?.trim()
        ? `html lang="${data.htmlLang.trim()}" is set.`
        : "The <html> tag is missing a lang attribute.",
    }),
  },
  {
    id: "missing_favicon",
    category: "on_page",
    severity: "low",
    description: "No favicon was detected.",
    check: (data) => ({
      passed: data.faviconPresent,
      message: data.faviconPresent
        ? "Favicon link detected in the document head."
        : "No favicon link detected (rel=icon / shortcut icon / apple-touch-icon).",
    }),
  },
  {
    id: "missing_image_dimensions",
    category: "performance",
    severity: "medium",
    description: "Image tags are missing width and/or height attributes.",
    check: (data) => ({
      passed: data.imagesMissingDimensionsCount === 0,
      message:
        data.imagesMissingDimensionsCount === 0
          ? "All <img> tags declare width and height attributes."
          : `${data.imagesMissingDimensionsCount} <img> tag(s) missing width and/or height attributes (can cause layout shift).`,
    }),
  },
  {
    id: "schema_invalid",
    category: "on_page",
    severity: "medium",
    description: "JSON-LD schema is malformed (parse validity only).",
    check: (data) => {
      if (data.schemaBlockCount === 0) {
        return {
          passed: true,
          message: "No JSON-LD blocks to validate (see missing_schema if applicable).",
        };
      }
      return {
        passed: data.schemaParseErrorCount === 0,
        message:
          data.schemaParseErrorCount === 0
            ? `${data.schemaBlockCount} JSON-LD block(s) parsed successfully.`
            : `${data.schemaParseErrorCount} of ${data.schemaBlockCount} JSON-LD block(s) failed to parse as JSON.`,
      };
    },
  },
];

export function evaluatePageRules(data: PageExtractResult): PageRuleResult[] {
  return RULES.map((rule) => {
    const result = rule.check(data);
    return {
      id: rule.id,
      category: rule.category,
      severity: rule.severity,
      description: rule.description,
      passed: result.passed,
      message: result.message,
    };
  });
}
