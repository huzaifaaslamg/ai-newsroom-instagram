"""Discover recent global news and extract publisher article text."""
from __future__ import annotations

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests
import trafilatura

LOG = logging.getLogger(__name__)
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
USER_AGENT = "Mozilla/5.0 (compatible; AI-Newsroom/1.0; +https://github.com/huzaifaaslamg/ai-newsroom-instagram)"
TIMEOUT = 18
RETRY_DELAYS = (4, 10, 20)


def _get_with_retries(
    url: str,
    *,
    params: dict | None = None,
    allow_redirects: bool = True,
    retry_delays: tuple[int, ...] = RETRY_DELAYS,
) -> requests.Response:
    """Retry temporary upstream errors with bounded backoff."""
    for attempt in range(len(retry_delays) + 1):
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT,
                allow_redirects=allow_redirects,
            )
        except requests.RequestException:
            if attempt >= len(retry_delays):
                raise
            delay = retry_delays[attempt]
            LOG.warning("News source connection error; retrying in %ss.", delay)
            time.sleep(delay)
            continue

        if response.status_code not in (429, 500, 502, 503, 504):
            return response
        if attempt >= len(retry_delays):
            response.raise_for_status()

        retry_after = response.headers.get("Retry-After", "")
        try:
            delay = min(30, max(1, int(retry_after)))
        except (TypeError, ValueError):
            delay = retry_delays[attempt]
        LOG.warning(
            "News source returned HTTP %s; retrying in %ss (attempt %s/%s).",
            response.status_code,
            delay,
            attempt + 1,
            len(retry_delays),
        )
        time.sleep(delay)

    raise RuntimeError("News source retry loop ended unexpectedly.")


def _clean_title(value: str) -> str:
    return re.sub(
        r"[^a-z0-9 ]",
        "",
        re.sub(r"\s+", " ", value or "").strip().lower(),
    )


def _parse_gdelt_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _parse_rss_date(value: str | None):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _rss_description(value: str | None) -> str:
    """Convert the feed's HTML description into safe plain text."""
    decoded = html.unescape(value or "")
    plain = re.sub(r"<[^>]+>", " ", decoded)
    return re.sub(r"\s+", " ", plain).strip()


def _parse_google_news_rss(
    xml_content: bytes,
    hours: int = 24,
    limit: int = 35,
) -> list[dict]:
    """Parse Google News RSS XML into the common article-index format."""
    root = ET.fromstring(xml_content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(hours, 24) + 1)
    result = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or not url.startswith("https://"):
            continue

        published = _parse_rss_date(item.findtext("pubDate"))
        if published and published < cutoff:
            continue

        source_node = item.find("source")
        source_name = (
            (source_node.text or "").strip()
            if source_node is not None else ""
        )
        source_url = source_node.get("url", "") if source_node is not None else ""
        source_domain = urlparse(source_url).netloc or source_name or "Google News"
        result.append({
            "title": title[:300],
            "url": url,
            "date": published.isoformat() if published else "",
            "domain": source_domain,
            "source_country": "",
            "description": _rss_description(item.findtext("description")),
        })
        if len(result) >= limit:
            break
    return result


def _fetch_google_news_rss(hours: int = 24, limit: int = 35) -> list[dict]:
    """Backup headline index used when GDELT is rate-limited or empty."""
    query = (
        "(world OR politics OR business OR economy OR technology OR science "
        "OR health OR climate OR sports OR conflict) when:1d"
    )
    response = _get_with_retries(
        GOOGLE_NEWS_RSS_URL,
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
    )
    response.raise_for_status()
    result = _parse_google_news_rss(response.content, hours=hours, limit=limit)
    LOG.info("Google News RSS backup returned %s candidate headlines.", len(result))
    return result


def fetch_recent_article_index(hours: int = 12, limit: int = 35) -> list[dict]:
    """Use GDELT once, then fall back to Google News RSS if it is unavailable."""
    params = {
        "query": (
            "sourcelang:english (world OR politics OR business OR economy "
            "OR technology OR science OR health OR climate OR sports OR conflict)"
        ),
        "mode": "ArtList",
        "format": "json",
        "sort": "DateDesc",
        "maxrecords": min(max(limit, 10), 250),
        "timespan": f"{hours}h",
    }

    articles = []
    try:
        # The DOC endpoint can enforce strict rate limits. Do not hammer it with
        # multiple retries; switch to the RSS backup immediately on HTTP 429.
        response = _get_with_retries(
            GDELT_URL, params=params, retry_delays=()
        )
        response.raise_for_status()
        payload = response.json()
        found = payload.get("articles", []) if isinstance(payload, dict) else []
        articles = found if isinstance(found, list) else []
        LOG.info("GDELT article index returned %s items.", len(articles))
    except (requests.RequestException, ValueError) as exc:
        LOG.warning("GDELT news index unavailable (%s); switching to RSS backup.", exc)

    if not articles:
        try:
            articles = _fetch_google_news_rss(hours=max(hours, 24), limit=limit)
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            LOG.error("Google News RSS backup is unavailable: %s", exc)
            return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(hours, 24) + 1)
    seen_urls, seen_titles, result = set(), set(), []
    for article in articles:
        url = (article.get("url") or "").strip()
        title = (article.get("title") or "").strip()
        if not url.startswith("https://") or not title:
            continue

        parsed = urlparse(url)
        normal_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        normal_title = _clean_title(title)
        published = _parse_gdelt_date(article.get("seendate"))
        if not published:
            published = _parse_rss_date(article.get("date"))
        if normal_url in seen_urls or normal_title in seen_titles:
            continue
        if published and published < cutoff:
            continue

        seen_urls.add(normal_url)
        seen_titles.add(normal_title)
        result.append({
            "title": title[:300],
            "url": url,
            "date": published.isoformat() if published else "",
            "domain": article.get("domain") or parsed.netloc,
            "source_country": article.get("sourcecountry") or "",
            "description": article.get("description", ""),
        })

    LOG.info("News index yielded %s unique usable URLs.", len(result))
    return result


def extract_article_text(url: str) -> str:
    response = _get_with_retries(url, allow_redirects=True)
    response.raise_for_status()
    if "text/html" not in response.headers.get("content-type", "").lower():
        return ""
    text = trafilatura.extract(
        response.text,
        include_comments=False,
        include_tables=False,
        include_links=False,
        favor_precision=True,
    )
    return re.sub(r"\n{3,}", "\n\n", text or "").strip()


def get_candidate_articles(max_candidates: int = 18) -> list[dict]:
    candidates = []
    for item in fetch_recent_article_index():
        if len(candidates) >= max_candidates:
            break
        try:
            article_text = extract_article_text(item["url"])
            # If a publisher blocks article extraction, a substantial RSS excerpt
            # may be used, but a headline alone is never enough.
            if len(article_text) < 500:
                excerpt = item.get("description", "")
                if len(excerpt) >= 250:
                    article_text = (
                        "[Publisher RSS excerpt; full article text unavailable] "
                        + excerpt
                    )
                else:
                    LOG.info("Skipping page with insufficient text: %s", item["url"])
                    continue

            candidates.append({
                "id": f"n{len(candidates) + 1:02d}",
                "title": item["title"],
                "url": item["url"],
                "date": item["date"],
                "domain": item["domain"],
                "source_country": item["source_country"],
                "article_text": article_text[:9000],
            })
            LOG.info("Prepared article %s from %s", len(candidates), item["domain"])
        except requests.RequestException as exc:
            LOG.warning("Could not fetch %s: %s", item["url"], exc)
        except Exception as exc:
            LOG.warning("Could not extract %s: %s", item["url"], exc)
        time.sleep(0.25)
    return candidates
