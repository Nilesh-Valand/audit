from app.models.project import Project
from app.models.crawl import Crawl, CrawlRun
from app.models.crawl_page import CrawlPage, CrawledPage
from app.models.page_link import PageLink
from app.models.site_issue import SiteIssue
from app.models.page_issue import PageIssue
from app.models.crawl_run_score import CrawlRunScore
from app.models.page_vital import PageVital
from app.models.sitemap_finding import SitemapFinding
from app.models.page_technical_details import PageTechnicalDetails

__all__ = [
    "Project",
    "Crawl",
    "CrawlRun",
    "CrawlPage",
    "CrawledPage",
    "PageLink",
    "SiteIssue",
    "PageIssue",
    "CrawlRunScore",
    "PageVital",
    "SitemapFinding",
    "PageTechnicalDetails",
]
