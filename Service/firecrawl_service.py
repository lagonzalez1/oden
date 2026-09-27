import os
from typing import Any, List, Optional

from fastapi import HTTPException
from firecrawl import FirecrawlApp

from Schema.firecrawl_schema import (
    FirecrawlPageResult,
    FirecrawlSearchParams,
    build_search_params,
)

FIRECRAWL_URL = os.getenv("FIRECRAWL_API_URL", "http://firecrawl-api:3002")

_EXTRACT_PROMPT = (
    "Extract a concise title and a short summary relevant to the graph node context."
)
_MAX_SCRAPE_URLS = 3


class FirecrawlService:

    def __init__(self):
        self.app = FirecrawlApp(
            api_url=FIRECRAWL_URL,
            api_key="not_needed_locally",  # Authentication is disabled on self-hosted instances
        )

    def run(self, node: Any) -> List[FirecrawlPageResult]:
        if node is None:
            raise HTTPException(status_code=404, detail="Node not found")

        params = build_search_params(node)
        results = self._search(params)

        web_hits = self._web_hits(results)[:_MAX_SCRAPE_URLS]
        print(web_hits)
        pages: List[FirecrawlPageResult] = []

        for hit in web_hits:
            url = self._attr(hit, "url")
            if not url:
                continue
            fallback_title = self._attr(hit, "title") or url
            try:
                page = self._scrape_structured(url)
                if page is None:
                    pages.append(
                        FirecrawlPageResult(title=fallback_title, summary="", url=url)
                    )
                else:
                    if not page.url:
                        page = page.model_copy(update={"url": url})
                    pages.append(page)
            except Exception as e:
                print(f"Scrape failed for {url}: {e}")
                pages.append(
                    FirecrawlPageResult(title=fallback_title, summary="", url=url)
                )

        return pages

    def _search(self, params: FirecrawlSearchParams) -> Any:
        """Search only — titles/URLs; structured scrape happens per URL."""
        try:
            return self.app.search(query=params.query, limit=params.limit)
        except Exception as e:
            print(f"Search failed: {e}")
            raise HTTPException(status_code=500, detail=f"Search failed: {e}")

    def _scrape_structured(self, url: str) -> Optional[FirecrawlPageResult]:
        scrape_fn = getattr(self.app, "scrape", None) or getattr(
            self.app, "scrape_url", None
        )
        if scrape_fn is None:
            raise RuntimeError("Firecrawl client h-as neither scrape nor scrape_url")

        formats = [
            {
                "type": "json",
                "schema": FirecrawlPageResult.model_json_schema(),
                "prompt": _EXTRACT_PROMPT,
            }
        ]
        result = scrape_fn(url, formats=formats)
        payload = self._attr(result, "json")
        if not isinstance(payload, dict):
            return None

        title = payload.get("title") or ""
        summary = payload.get("summary") or ""
        page_url = payload.get("url") or url
        return FirecrawlPageResult(title=title, summary=summary, url=page_url)

    @staticmethod
    def _web_hits(results: Any) -> List[Any]:
        web = FirecrawlService._attr(results, "web")
        if web is None:
            return []
        return list(web)

    @staticmethod
    def _attr(obj: Any, key: str) -> Any:
        if obj is None:
            return None
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

