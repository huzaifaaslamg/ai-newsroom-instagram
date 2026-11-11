"""Discover recent global news and extract publisher article text."""
from __future__ import annotations
import logging, re, time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import requests
import trafilatura

LOG = logging.getLogger(__name__)
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
USER_AGENT = "Mozilla/5.0 (compatible; AI-Newsroom/1.0; +https://github.com/huzaifaaslamg/ai-newsroom-instagram)"
TIMEOUT = 18

def _clean_title(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", value or "").strip().lower())

def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None

def fetch_recent_article_index(hours: int = 12, limit: int = 70) -> list[dict]:
    params = {
        "query": "sourcelang:english (world OR politics OR business OR economy OR technology OR science OR health OR climate OR sports OR conflict)",
        "mode": "ArtList", "format": "json", "sort": "DateDesc",
        "maxrecords": min(max(limit, 10), 250), "timespan": f"{hours}h",
    }
    response = requests.get(GDELT_URL, params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    response.raise_for_status()
    articles = response.json().get("articles", [])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours + 1)
    seen_urls, seen_titles, result = set(), set(), []
    for article in articles if isinstance(articles, list) else []:
        url = (article.get("url") or "").strip()
        title = (article.get("title") or "").strip()
        if not url.startswith("https://") or not title:
            continue
        parsed = urlparse(url)
        normal_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        normal_title = _clean_title(title)
        published = _parse_date(article.get("seendate"))
        if normal_url in seen_urls or normal_title in seen_titles:
            continue
        if published and published < cutoff:
            continue
        seen_urls.add(normal_url)
        seen_titles.add(normal_title)
        result.append({
            "title": title[:300], "url": url,
            "date": published.isoformat() if published else "",
            "domain": article.get("domain") or parsed.netloc,
            "source_country": article.get("sourcecountry") or "",
        })
    return result

def extract_article_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": USER_AGENT},
                            timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    if "text/html" not in response.headers.get("content-type", "").lower():
        return ""
    text = trafilatura.extract(response.text, include_comments=False,
        include_tables=False, include_links=False, favor_precision=True)
    return re.sub(r"\n{3,}", "\n\n", text or "").strip()

def get_candidate_articles(max_candidates: int = 18) -> list[dict]:
    candidates = []
    for item in fetch_recent_article_index():
        if len(candidates) >= max_candidates:
            break
        try:
            article_text = extract_article_text(item["url"])
            # Do not write a news post from a headline alone.
            if len(article_text) < 500:
                LOG.info("Skipping page with insufficient text: %s", item["url"])
                continue
            candidates.append({
                "id": f"n{len(candidates) + 1:02d}",
                "title": item["title"], "url": item["url"],
                "date": item["date"], "domain": item["domain"],
                "source_country": item["source_country"],
                "article_text": article_text[:9000],
            })
            LOG.info("Extracted article %s from %s", len(candidates), item["domain"])
        except requests.RequestException as exc:
            LOG.warning("Could not fetch %s: %s", item["url"], exc)
        except Exception as exc:
            LOG.warning("Could not extract %s: %s", item["url"], exc)
        time.sleep(0.25)
    return candidates
