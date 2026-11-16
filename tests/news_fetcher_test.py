"""Offline tests for direct publisher RSS fallback."""
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import sys
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news_fetcher import _parse_publisher_rss, fetch_recent_article_index


def test_publisher_rss_parser_extracts_direct_url_and_summary():
    published = format_datetime(datetime.now(timezone.utc))
    summary = (
        "A sample publisher summary with enough information for a cautious "
        "news brief. It contains several sentences describing the event, "
        "the people involved, and the reported impact with attribution."
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><item>
      <title>Sample global news development</title>
      <link>https://www.bbc.com/news/articles/sample-story</link>
      <pubDate>{published}</pubDate>
      <description>&lt;p&gt;{summary}&lt;/p&gt;</description>
    </item></channel></rss>""".encode("utf-8")

    articles = _parse_publisher_rss(xml, "BBC World")
    assert len(articles) == 1
    assert articles[0]["title"] == "Sample global news development"
    assert articles[0]["domain"] == "www.bbc.com"
    assert articles[0]["url"] == "https://www.bbc.com/news/articles/sample-story"
    assert articles[0]["publisher"] == "BBC World"
    assert summary in articles[0]["description"]


def test_gdelt_error_uses_publisher_rss_backup():
    fallback_article = {
        "title": "Fallback headline",
        "url": "https://www.bbc.com/news/articles/fallback",
        "date": datetime.now(timezone.utc).isoformat(),
        "domain": "www.bbc.com",
        "publisher": "BBC News",
        "source_country": "",
        "description": "A detailed publisher RSS summary for the fallback test.",
    }
    with patch("news_fetcher._get_with_retries", side_effect=requests.HTTPError("429")):
        with patch("news_fetcher._fetch_publisher_rss", return_value=[fallback_article]) as backup:
            articles = fetch_recent_article_index()
    assert backup.called
    assert len(articles) == 1
    assert articles[0]["title"] == "Fallback headline"
    assert articles[0]["url"].startswith("https://www.bbc.com/")


if __name__ == "__main__":
    test_publisher_rss_parser_extracts_direct_url_and_summary()
    test_gdelt_error_uses_publisher_rss_backup()
    print("Publisher RSS fallback tests passed.")
