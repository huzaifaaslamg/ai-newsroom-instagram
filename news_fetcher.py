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


PUBLISHER_RSS_FEEDS = [
    ("BBC News", "https://feeds.bbci.co.uk/news/rss.xml"),
    ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("BBC Science", "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"),
    ("Al Jazeera English", "https://www.aljazeera.com/xml/rss/all.xml"),
    ("The Guardian World", "https://www.theguardian.com/world/rss"),
    ("The Guardian Business", "https://www.theguardian.com/business/rss"),
]


def _parse_publisher_rss(
    xml_content: bytes,
    feed_name: str,
    hours: int = 24,
    limit: int = 35,
) -> list[dict]:
    """Parse direct publisher RSS feeds with real article URLs and summaries."""
    root = ET.fromstring(xml_content)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(hours, 24) + 1)
    result = []

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        if not title or not url.startswith(("https://", "http://")):
            continue

        published = _parse_rss_date(item.findtext("pubDate"))
        if published and published < cutoff:
            continue

        description = item.findtext("description")
        # Some publishers put their summary in content:encoded rather than
        # description. Read it by local tag name to avoid namespace assumptions.
        if not description:
            for child in item:
                if child.tag.rsplit("}", 1)[-1] == "encoded" and child.text:
                    description = child.text
                    break

        source_node = item.find("source")
        source_name = (
            (source_node.text or "").strip()
            if source_node is not None else ""
        )
        domain = urlparse(url).netloc
        result.append({
            "title": title[:300],
            "url": url,
            "date": published.isoformat() if published else "",
            "domain": domain,
            "publisher": source_name or feed_name,
            "source_country": "",
            "description": _rss_description(description),
        })
        if len(result) >= limit:
            break

    return result


def _fetch_publisher_rss(hours: int = 24, limit: int = 35) -> list[dict]:
    """Fetch a small set of direct publisher feeds as the GDELT backup."""
    articles = []
    per_feed = max(5, min(12, (limit + len(PUBLISHER_RSS_FEEDS) - 1) // len(PUBLISHER_RSS_FEEDS)))
    for feed_name, feed_url in PUBLISHER_RSS_FEEDS:
        try:
            response = _get_with_retries(feed_url, retry_delays=(3,))
            response.raise_for_status()
            items = _parse_publisher_rss(
                response.content,
                feed_name=feed_name,
                hours=hours,
                limit=per_feed,
            )
            LOG.info("%s RSS returned %s usable items.", feed_name, len(items))
            articles.extend(items)
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            LOG.warning("%s RSS feed unavailable: %s", feed_name, exc)
        if len(articles) >= limit:
            break

    # Newest first, with URL deduplication across overlapping publisher feeds.
    articles.sort(key=lambda item: item.get("date", ""), reverse=True)
    seen_urls, seen_titles, unique = set(), set(), []
    for item in articles:
        url_key = item["url"].split("#", 1)[0].rstrip("/")
        title_key = _clean_title(item["title"])
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        unique.append(item)
        if len(unique) >= limit:
            break

    LOG.info("Publisher RSS backup returned %s unique headlines.", len(unique))
    return unique


def fetch_recent_article_index(hours: int = 12, limit: int = 35) -> list[dict]:
    """Use GDELT once, then fall back to direct publisher RSS feeds."""
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
        # GDELT has recently rate-limited the shared GitHub Actions runner.
        # Make one request only, then use publisher-owned RSS feeds.
        response = _get_with_retries(GDELT_URL, params=params, retry_delays=())
        response.raise_for_status()
        payload = response.json()
        found = payload.get("articles", []) if isinstance(payload, dict) else []
        articles = found if isinstance(found, list) else []
        LOG.info("GDELT article index returned %s items.", len(articles))
    except (requests.RequestException, ValueError) as exc:
        LOG.warning(
            "GDELT news index unavailable (%s); switching to publisher RSS backup.",
            exc,
        )

    if not articles:
        try:
            articles = _fetch_publisher_rss(hours=max(hours, 24), limit=limit)
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            LOG.error("Publisher RSS backup is unavailable: %s", exc)
            return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(hours, 24) + 1)
    seen_urls, seen_titles, result = set(), set(), []
    for article in articles:
        url = (article.get("url") or "").strip()
        title = (article.get("title") or "").strip()
        if not url.startswith(("https://", "http://")) or not title:
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
            "publisher": article.get("publisher") or article.get("domain") or parsed.netloc,
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
            # Publisher-owned RSS descriptions are legitimate short summaries.
            # Keep a minimum size so that headlines alone never reach Gemini.
            if len(article_text) < 500:
                excerpt = item.get("description", "")
                if len(excerpt) >= 120:
                    article_text = (
                        "[Publisher-provided RSS summary; full article text "
                        "was not available] " + excerpt
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
