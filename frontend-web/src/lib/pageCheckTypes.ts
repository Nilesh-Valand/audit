export type HeadingInfo = {
  tag: "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
  text: string;
};

export type PageExtractResult = {
  url: string;
  title: string | null;
  metaDescription: string | null;
  canonical: string | null;
  metaRobots: string | null;
  headings: HeadingInfo[];
  h1Count: number;
  schemaTypes: string[];
  schemaBlockCount: number;
  schemaParseErrorCount: number;
  imagesMissingAlt: { src: string; count: number };
  imagesMissingAltSamples: string[];
  imagesMissingDimensionsCount: number;
  imagesMissingDimensionsSamples: string[];
  internalLinkCount: number;
  externalLinkCount: number;
  wordCount: number;
  isHttps: boolean;
  mixedContentUrls: string[];
  ogTitle: string | null;
  ogDescription: string | null;
  ogImage: string | null;
  twitterCard: string | null;
  twitterTitle: string | null;
  htmlLang: string | null;
  faviconPresent: boolean;
};

export type RuleSeverity = "critical" | "high" | "medium" | "low";

export type PageRuleResult = {
  id: string;
  category: string;
  severity: RuleSeverity;
  description: string;
  passed: boolean;
  message: string;
};
