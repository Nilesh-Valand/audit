from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from protego import Protego

from app.config import settings
from app.crawler.extractor import (
    ExtractedPage,
    RedirectHop,
    extract_page_data,
    is_http_url,
    rendered_content_differs,
)
from app.crawler.storage import CrawlStorage
from app.crawler.normalize import normalize_url, prefer_www_from_seed

logger = logging.getLogger(__name__)

# Cap resource HEADs used for approximate page weight.
_MAX_WEIGHT_RESOURCES = 40
SITEMAP_CRAWL_LIMIT = 5_000

try:
    from playwright.sync_api import Browser, Error as PlaywrightError, sync_playwright
except Exception:  # pragma: no cover - import may fail when browsers are not installed
    Browser = None  # type: ignore[misc, assignment]
    PlaywrightError = Exception
    sync_playwright = None


@dataclass(slots=True)
class CrawlResult:
    page: ExtractedPage
    discovered_urls: list[str]


def _normalize_host(hostname: str) -> str:
    return hostname.lower().removeprefix("www.")


class CrawlerService:
    def __init__(
        self,
        *,
        start_url: str,
        max_pages: int = 200,
        max_depth: int = 10,
        concurrency: int | None = None,
        request_delay: float | None = None,
        thin_content_threshold: int | None = None,
        user_agent: str | None = None,
        storage: CrawlStorage | None = None,
        render_js_when_thin: bool = True,
        progress_callback: Callable[[], None] | None = None,
    ) -> None:
        parsed = urlparse(start_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("start_url must be a valid absolute http/https URL.")

        self.start_url = start_url
        self.root_host = parsed.hostname
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.effective_max_depth = max(max_depth, 50 if max_pages >= 100 else max_depth)
        self.concurrency = concurrency or settings.CRAWLER_CONCURRENCY
        self.request_delay = request_delay if request_delay is not None else settings.CRAWLER_REQUEST_DELAY
        self.max_crawl_delay = settings.CRAWLER_MAX_CRAWL_DELAY
        self.thin_content_threshold = (
            thin_content_threshold
            if thin_content_threshold is not None
            else settings.CRAWLER_THIN_CONTENT_THRESHOLD
        )
        self.user_agent = user_agent or settings.CRAWLER_USER_AGENT
        self.storage = storage or CrawlStorage(flush_size=settings.CRAWLER_FLUSH_SIZE)
        self.render_js_when_thin = render_js_when_thin
        self.progress_callback = progress_callback
        self.flush_interval = settings.CRAWLER_FLUSH_INTERVAL
        self.prefer_www = prefer_www_from_seed(start_url)

        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._last_request_at: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._robots_cache: dict[str, Protego] = {}

        self._pw_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="playwright"
        )
        self._sync_playwright = None
        self._browser: Browser | None = None
        self._playwright_failed = False

    async def crawl(self, crawl_run_id: int) -> None:
        self.storage.set_run_started(crawl_run_id, max_pages=self.max_pages)

        timeout = httpx.Timeout(20.0, connect=10.0)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Upgrade-Insecure-Requests": "1",
        }
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout,
            headers=headers,
        ) as client:
            flush_stop = asyncio.Event()
            flush_task = asyncio.create_task(self._periodic_flush(flush_stop))

            start_normalized = normalize_url(self.start_url, prefer_www=self.prefer_www)

            # Pre-discover sitemaps to seed queue with all site URLs right away
            sitemap_urls = await self._discover_sitemap_urls(client, self.start_url)
            logger.info("Discovered %d URLs from sitemaps for start URL %s", len(sitemap_urls), self.start_url)

            queue: deque[tuple[str, int]] = deque([(start_normalized, 0)])
            visited: set[str] = {start_normalized}
            for sm_url in sitemap_urls:
                norm_sm = normalize_url(sm_url, prefer_www=self.prefer_www)
                if norm_sm not in visited:
                    visited.add(norm_sm)
                    queue.append((norm_sm, 1))

            stored_urls: set[str] = set()
            lock = asyncio.Lock()
            seed_handled = False

            async def worker() -> None:
                nonlocal seed_handled
                while True:
                    async with lock:
                        if len(stored_urls) >= self.max_pages or not queue:
                            return
                        url, depth = queue.popleft()

                    try:
                        result = await self._crawl_single_url(client, url)
                    except Exception as exc:
                        logger.exception("Failed crawling %s: %s", url, exc)
                        continue

                    if result is None:
                        continue

                    raw_final = result.page.url or url
                    final_key = normalize_url(raw_final, prefer_www=self.prefer_www)

                    async with lock:
                        # Update prefer_www & root_host dynamically if seed URL redirected (e.g. calltool.com -> www.calltool.com)
                        if not seed_handled and _normalize_host(urlparse(raw_final).hostname or "") == _normalize_host(self.root_host):
                            final_host = urlparse(raw_final).hostname or self.root_host
                            self.root_host = final_host
                            self.prefer_www = prefer_www_from_seed(raw_final)
                            seed_handled = True

                        if final_key in stored_urls:
                            continue

                        if len(stored_urls) >= self.max_pages:
                            return

                        result.page.raw_url = raw_final
                        result.page.url = final_key
                        stored_urls.add(final_key)
                        visited.add(final_key)

                        await self.storage.add(crawl_run_id, result.page)
                        await self.storage.flush()

                        current_count = len(stored_urls)

                        self.storage.set_run_phase(
                            crawl_run_id,
                            phase="crawling",
                            current=current_count,
                            total=self.max_pages,
                        )

                        if self.progress_callback is not None:
                            self.progress_callback()

                        if depth < self.effective_max_depth:
                            for discovered_url in result.discovered_urls:
                                discovered_key = normalize_url(
                                    discovered_url, prefer_www=self.prefer_www
                                )
                                if discovered_key not in visited:
                                    visited.add(discovered_key)
                                    queue.append((discovered_key, depth + 1))

            try:
                # Launch workers continuously up to self.concurrency
                tasks: set[asyncio.Task[None]] = set()
                while len(stored_urls) < self.max_pages:
                    async with lock:
                        if not queue and not tasks:
                            break
                        while queue and len(tasks) < self.concurrency and len(stored_urls) + len(tasks) < self.max_pages:
                            task = asyncio.create_task(worker())
                            tasks.add(task)

                    if not tasks:
                        break

                    done, tasks = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                    for completed in done:
                        # Propagate unhandled errors if worker failed
                        try:
                            await completed
                        except Exception as exc:
                            logger.exception("Worker task encountered error: %s", exc)

                await self.storage.flush()
            except Exception:
                await self.storage.flush()
                self.storage.set_run_failed(crawl_run_id)
                raise
            finally:
                flush_stop.set()
                try:
                    await flush_task
                except Exception:
                    logger.exception("Periodic flush task ended with an error")
                await self._close_playwright()

    async def _discover_sitemap_urls(self, client: httpx.AsyncClient, start_url: str) -> list[str]:
        parsed = urlparse(start_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        sitemap_targets: set[str] = {
            f"{origin}/sitemap.xml",
            f"{origin}/sitemap_index.xml",
            f"{origin}/sitemap-index.xml",
        }

        # Check robots.txt for Sitemap: directives
        robots_url = f"{origin}/robots.txt"
        try:
            resp = await client.get(robots_url)
            if resp.status_code < 400 and resp.text:
                parser = Protego.parse(resp.text)
                for sm in parser.sitemaps:
                    if is_http_url(sm):
                        sitemap_targets.add(sm.strip())
        except Exception:
            pass

        extracted_urls: list[str] = []
        visited_sitemaps: set[str] = set()

        async def _walk(sm_url: str) -> None:
            if len(extracted_urls) >= SITEMAP_CRAWL_LIMIT:
                return
            norm_sm = normalize_url(sm_url, seed_url=start_url)
            if norm_sm in visited_sitemaps:
                return
            visited_sitemaps.add(norm_sm)

            try:
                r = await client.get(sm_url)
                if r.status_code >= 400 or not r.content:
                    return
                root = ET.fromstring(r.content)
            except Exception:
                return

            tag = root.tag.split("}", 1)[-1].lower()
            if tag == "sitemapindex":
                child_locs = [
                    node.text.strip()
                    for node in root.findall(".//{*}sitemap/{*}loc")
                    if node.text and node.text.strip()
                ]
                for child in child_locs:
                    if len(extracted_urls) >= SITEMAP_CRAWL_LIMIT:
                        break
                    await _walk(child)
            elif tag == "urlset":
                for loc in root.findall(".//{*}url/{*}loc"):
                    if len(extracted_urls) >= SITEMAP_CRAWL_LIMIT:
                        break
                    if loc.text and loc.text.strip():
                        target = loc.text.strip()
                        host = urlparse(target).hostname
                        if host and _normalize_host(host) == _normalize_host(self.root_host):
                            extracted_urls.append(target)

        await asyncio.gather(*(_walk(target) for target in list(sitemap_targets)), return_exceptions=True)
        return extracted_urls

    async def _crawl_single_url(self, client: httpx.AsyncClient, url: str) -> CrawlResult | None:
        async with self._semaphore:
            if not await self._is_allowed_by_robots(client, url):
                return None

            raw_page = await self._fetch_with_httpx(client, url)
            if raw_page is None:
                return None

            final_page = raw_page
            if self._should_render_js(raw_page):
                rendered_page = await self._fetch_with_playwright(client, url)
                if rendered_page is not None:
                    rendered_page.js_rendered = True
                    rendered_page.rendered_diff_significant = rendered_content_differs(
                        raw_page, rendered_page
                    )
                    if not rendered_page.redirect_chain and raw_page.redirect_chain:
                        rendered_page.redirect_chain = list(raw_page.redirect_chain)
                        rendered_page.redirect_hops = raw_page.redirect_hops
                    final_page = rendered_page

            if final_page.html is not None:
                try:
                    await self._enrich_page_signals(client, final_page)
                except Exception:
                    logger.exception("Page signal enrichment failed for %s", url)

            discovered_urls = [
                link.target_url for link in final_page.links if link.is_internal
            ]
            return CrawlResult(page=final_page, discovered_urls=discovered_urls)

    async def _fetch_with_httpx(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> ExtractedPage | None:
        host = urlparse(url).hostname or self.root_host
        await self._respect_host_delay(host)

        started = time.perf_counter()
        try:
            response = await client.get(url)
        except httpx.HTTPError:
            elapsed_ms = (time.perf_counter() - started) * 1000
            return ExtractedPage(
                url=url,
                html=None,
                status_code=None,
                response_time_ms=elapsed_ms,
                redirect_hops=0,
                title=None,
                meta_description=None,
                canonical_url=None,
                meta_robots=None,
            )

        elapsed_ms = (time.perf_counter() - started) * 1000
        redirect_chain = _redirect_chain_from_response(response)
        content_type = response.headers.get("content-type", "").lower()
        if "html" not in content_type:
            return ExtractedPage(
                url=str(response.url),
                html=None,
                status_code=response.status_code,
                response_time_ms=elapsed_ms,
                redirect_hops=len(response.history),
                title=None,
                meta_description=None,
                canonical_url=None,
                meta_robots=None,
                redirect_chain=redirect_chain,
                html_bytes=_response_size_bytes(response),
            )

        html_text = response.text
        return extract_page_data(
            url=str(response.url),
            html=html_text,
            status_code=response.status_code,
            response_time_ms=elapsed_ms,
            root_host=self.root_host,
            redirect_hops=len(response.history),
            html_bytes=_response_size_bytes(response) or len(html_text.encode("utf-8", errors="replace")),
            redirect_chain=redirect_chain,
        )

    async def _fetch_with_playwright(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> ExtractedPage | None:
        del client  # HTTP client not used; Playwright fetches the page itself.
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                self._pw_executor, self._fetch_with_playwright_sync, url
            )
        except Exception as exc:
            logger.warning("Playwright render failed for %s: %s", url, exc)
            return None

    def _fetch_with_playwright_sync(self, url: str) -> ExtractedPage | None:
        browser = self._ensure_browser_sync()
        if browser is None:
            return None

        page = browser.new_page(user_agent=self.user_agent)
        try:
            started = time.perf_counter()
            response = page.goto(url, wait_until="domcontentloaded", timeout=10000)
            html = page.content()
            elapsed_ms = (time.perf_counter() - started) * 1000
            return extract_page_data(
                url=page.url,
                html=html,
                status_code=response.status if response else None,
                response_time_ms=elapsed_ms,
                root_host=self.root_host,
                redirect_hops=0,
                html_bytes=len(html.encode("utf-8", errors="replace")),
            )
        except PlaywrightError:
            return None
        finally:
            page.close()

    def _ensure_browser_sync(self) -> Browser | None:
        if self._browser is not None:
            return self._browser
        if sync_playwright is None or not self.render_js_when_thin:
            return None
        if self._playwright_failed:
            return None

        try:
            self._sync_playwright = sync_playwright().start()
            self._browser = self._sync_playwright.chromium.launch(headless=True)
            return self._browser
        except Exception as exc:
            logger.warning(
                "Playwright unavailable, continuing with HTML crawl only: %s", exc
            )
            self._playwright_failed = True
            self._browser = None
            self._sync_playwright = None
            return None

    async def _close_playwright(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._pw_executor, self._close_playwright_sync)
        finally:
            self._pw_executor.shutdown(wait=False, cancel_futures=False)

    def _close_playwright_sync(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._sync_playwright is not None:
            try:
                self._sync_playwright.stop()
            except Exception:
                pass
            self._sync_playwright = None

    async def _enrich_page_signals(self, client: httpx.AsyncClient, page: ExtractedPage) -> None:
        if page.favicon_in_html:
            page.favicon_present = True
        else:
            page.favicon_present = await self._probe_default_favicon(client, page.url)

        page.resource_request_count = self._count_resource_requests(page)
        page.total_page_weight_bytes = await self._estimate_page_weight(client, page)

    def _count_resource_requests(self, page: ExtractedPage) -> int:
        """Approximate subresource count: HTML document + unique CSS/JS/images."""
        seen: set[str] = set()
        count = 1  # HTML document itself
        for url in [*page.stylesheet_urls, *page.script_urls, *(img.src for img in page.images)]:
            if not is_http_url(url) or url in seen:
                continue
            seen.add(url)
            count += 1
        return count

    async def _probe_default_favicon(self, client: httpx.AsyncClient, page_url: str) -> bool:
        parsed = urlparse(page_url)
        favicon_url = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
        try:
            response = await client.head(favicon_url)
            if response.status_code < 400:
                return True
            if response.status_code in {405, 501}:
                response = await client.get(favicon_url)
                return response.status_code < 400
            return False
        except httpx.HTTPError:
            return False

    async def _estimate_page_weight(self, client: httpx.AsyncClient, page: ExtractedPage) -> int:
        total = page.html_bytes or 0
        resource_urls: list[str] = []
        seen: set[str] = set()

        for url in [*page.stylesheet_urls, *page.script_urls, *(img.src for img in page.images)]:
            if not is_http_url(url) or url in seen:
                continue
            seen.add(url)
            resource_urls.append(url)
            if len(resource_urls) >= _MAX_WEIGHT_RESOURCES:
                break

        if not resource_urls:
            return total

        sizes = await asyncio.gather(
            *(self._resource_size_bytes(client, url) for url in resource_urls)
        )
        size_by_url = {url: size for url, size in zip(resource_urls, sizes, strict=True)}
        for image in page.images:
            if image.src in size_by_url:
                image.size_bytes = size_by_url[image.src] or None
        return total + sum(sizes)

    async def _resource_size_bytes(self, client: httpx.AsyncClient, url: str) -> int:
        if not is_http_url(url):
            return 0
        try:
            response = await client.head(url)
            if response.status_code in {405, 501}:
                response = await client.get(url)
            if response.status_code >= 400:
                return 0
            size = _response_size_bytes(response)
            if size is not None:
                return size
            if response.request.method.upper() == "HEAD":
                return 0
            return len(response.content)
        except Exception:
            return 0

    async def _is_allowed_by_robots(self, client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return False

        if host not in self._robots_cache:
            robots_url = f"{parsed.scheme}://{host}/robots.txt"
            try:
                response = await client.get(robots_url)
                body = response.text if response.status_code < 400 else ""
            except httpx.HTTPError:
                body = ""
            self._robots_cache[host] = Protego.parse(body)

        return self._robots_cache[host].can_fetch(url, self.user_agent)

    async def _respect_host_delay(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            last_request_at = self._last_request_at.get(host)
            crawl_delay = 0.0
            parser = self._robots_cache.get(host)
            if parser is not None:
                raw_delay = parser.crawl_delay(self.user_agent)
                try:
                    crawl_delay = float(raw_delay) if raw_delay is not None else 0.0
                except (TypeError, ValueError):
                    crawl_delay = 0.0
                crawl_delay = min(crawl_delay, self.max_crawl_delay)
            effective_delay = max(self.request_delay, crawl_delay)
            if last_request_at is not None:
                wait_time = effective_delay - (now - last_request_at)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
            self._last_request_at[host] = time.monotonic()

    def _should_render_js(self, page: ExtractedPage) -> bool:
        return (
            self.render_js_when_thin
            and not self._playwright_failed
            and page.html is not None
            and (page.status_code is None or page.status_code < 400)
            and page.word_count < self.thin_content_threshold
            and sync_playwright is not None
        )

    async def _periodic_flush(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self.flush_interval)
            except asyncio.TimeoutError:
                try:
                    await self.storage.flush()
                except Exception:
                    logger.exception("Periodic crawl flush failed")


def _redirect_chain_from_response(response: httpx.Response) -> list[RedirectHop]:
    hops: list[RedirectHop] = []
    for prior in response.history:
        hops.append(RedirectHop(url=str(prior.url), status_code=prior.status_code))
    return hops


def _response_size_bytes(response: httpx.Response) -> int | None:
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            return max(0, int(content_length))
        except ValueError:
            pass
    try:
        content = response.content
    except Exception:
        return None
    return len(content)
