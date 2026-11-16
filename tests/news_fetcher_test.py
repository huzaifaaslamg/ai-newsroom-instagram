"""Offline tests for the Google News RSS fallback."""
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import sys
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from news_fetcher import _parse_google_news_rss, fetch_recent_article_index


def test_rss_parser_extracts_source_and_description():
    published = format_datetime(datetime.now(timezone.utc))
    excerpt = (
        "A publisher-provided excerpt with enough detail to test the RSS backup. "
        "It contains useful reporting context, names the subject, and describes "
        "the reported development without relying on a headline alone."
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><item>
      <title>Sample global news development</title>
      <link>https://news.google.com/rss/articles/sample-id</link>
      <pubDate>{published}</pubDate>
      <source url="https://www.reuters.com">Reuters</source>
      <description>&lt;p&gt;{excerpt}&lt;/p&gt;</description>
    </item></channel></rss>""".encode("utf-8")

    articles = _parse_google_news_rss(xml)
    assert len(articles) == 1
    assert articles[0]["title"] == "Sample global news development"
    assert articles[0]["domain"] == "www.reuters.com"
    assert articles[0]["url"].startswith("https://news.google.com/")
    assert excerpt in articles[0]["description"]


def test_gdelt_error_uses_rss_backup():
    fallback_article = {
        "title": "Fallback headline",
        "url": "https://news.google.com/rss/articles/fallback",
        "date": datetime.now(timezone.utc).isoformat(),
        "domain": "www.example.com",
        "source_country": "",
        "description": "Fallback publisher excerpt.",
    }
    with patch("news_fetcher._get_with_retries", side_effect=requests.HTTPError("429")):
        with patch("news_fetcher._fetch_google_news_rss", return_value=[fallback_article]) as backup:
            articles = fetch_recent_article_index()
    assert backup.called
    assert len(articles) == 1
    assert articles[0]["title"] == "Fallback headline"


if __name__ == "__main__":
    test_rss_parser_extracts_source_and_description()
    test_gdelt_error_uses_rss_backup()
    print("News fallback tests passed.")
