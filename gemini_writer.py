"""Create source-grounded bilingual news copy with the Gemini API."""
from __future__ import annotations
import json
import os
import re
from google import genai
from google.genai import types

def _extract_json(text: str) -> dict:
    value = (text or "").strip()
    value = re.sub(r"^```json\s*|^```\s*", "", value, flags=re.I)
    value = value.replace("```", "")
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Gemini did not return a JSON object.")
    return json.loads(value[start:end + 1])

def _unique_sources(stories: list[dict]) -> list[dict]:
    sources, seen = [], set()
    for story in stories:
        for source in story["sources"]:
            if source["url"] not in seen:
                seen.add(source["url"])
                sources.append({key: source.get(key, "") for key in (
                    "title", "url", "date", "domain", "source_country"
                )})
    return sources

def create_news_brief(candidates: list[dict], slot: str, local_date: str) -> dict:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Add it in GitHub Settings > Secrets and variables > Actions.")
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    client = genai.Client(api_key=api_key)
    source_pack = [{
        "id": item["id"], "headline": item["title"],
        "publisher_domain": item["domain"], "published_at": item.get("date", ""),
        "source_url": item["url"], "article_text": item["article_text"][:5200],
    } for item in candidates]

    prompt = f"""
You are the editorial desk of a careful independent global news briefing.
Prepare the {slot.upper()} edition for {local_date}. The audience is international,
including readers in Pakistan. Coverage is broad: world affairs, politics,
business, economy, technology, science, health, climate, and sports.

Use ONLY supplied article text. Do not use outside knowledge, invent figures or
quotes, or add context unsupported by these articles. Do not state allegations as
proven facts. Be particularly cautious with elections, conflict, crime, deaths,
public health and financial claims. Include a sensitive or disputed claim only
when at least two distinct supplied publishers corroborate it; otherwise omit it.
Exclude opinion pieces, clickbait, old stories and weak rewrites. Prefer a mix of
subjects and publishers. Never invent a source.

Select 5 distinct stories if possible (minimum 4), most important first. For each:
candidate_id (a supplied primary ID); corroborating_candidate_ids (other supplied
IDs independently supporting the same event); category; headline_en (under 13
words); headline_ur (natural Urdu); summary_en and summary_ur (accurate plain
language, 1-2 short sentences); why_en and why_ur (why it matters, only supported
by supplied reporting).

Return JSON only:
{{
 "stories":[
  {{"candidate_id":"n01","corroborating_candidate_ids":[],"category":"WORLD",
   "headline_en":"...","headline_ur":"...","summary_en":"...","summary_ur":"...",
   "why_en":"...","why_ur":"..."}}
 ],
 "carousel_caption_en":"...","carousel_caption_ur":"...",
 "single_caption_en":"...","single_caption_ur":"...",
 "hashtags":["#WorldNews","#NewsBrief"]
}}

Captions should be concise, useful, non-sensational, bilingual in their respective
fields, and invite respectful discussion. Do not include source URLs; publishing
code adds verified source links. Use at most 8 relevant hashtags. Never claim
these are literally all the world's news.

Reporting supplied:
{json.dumps(source_pack, ensure_ascii=False)}
"""
    response = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json", temperature=0.25
        ),
    )
    brief = _extract_json(response.text or "")
    by_id = {item["id"]: item for item in candidates}
    stories = []
    for item in brief.get("stories", []):
        candidate_id = item.get("candidate_id")
        if candidate_id not in by_id:
            continue
        primary = by_id[candidate_id]
        corroborating = [
            by_id[source_id]
            for source_id in item.get("corroborating_candidate_ids", [])
            if source_id in by_id and source_id != candidate_id
        ]
        stories.append({
            "category": str(item.get("category", "WORLD")).upper()[:24],
            "headline_en": str(item.get("headline_en", primary["title"]))[:180],
            "headline_ur": str(item.get("headline_ur", ""))[:180],
            "summary_en": str(item.get("summary_en", ""))[:550],
            "summary_ur": str(item.get("summary_ur", ""))[:550],
            "why_en": str(item.get("why_en", ""))[:350],
            "why_ur": str(item.get("why_ur", ""))[:350],
            "sources": [
                {key: source.get(key, "") for key in (
                    "title", "url", "date", "domain", "source_country"
                )}
                for source in [primary] + corroborating
            ],
        })
    if len(stories) < 4:
        raise RuntimeError(f"Gemini returned only {len(stories)} grounded stories. Need 4; no post will be made.")
    stories = stories[:5]
    hashtags = []
    for tag in brief.get("hashtags", []):
        tag = str(tag)
        if re.fullmatch(r"#?[A-Za-z0-9_]{2,30}", tag):
            hashtags.append(tag if tag.startswith("#") else f"#{tag}")
    hashtags = hashtags[:8]

    def make_caption(en: str, ur: str) -> str:
        source_lines = [
            f"• {source['domain']}: {source['url']}"
            for source in _unique_sources(stories)
        ]
        parts = [
            str(en).strip(), str(ur).strip(),
            "Sources:\n" + "\n".join(source_lines),
            " ".join(hashtags),
        ]
        return "\n\n".join(part for part in parts if part)[:2190]

    return {
        "date": local_date, "slot": slot, "stories": stories,
        "carousel_caption": make_caption(
            brief.get("carousel_caption_en", "Your global news briefing."),
            brief.get("carousel_caption_ur", "")),
        "single_caption": make_caption(
            brief.get("single_caption_en", "One story to understand today."),
            brief.get("single_caption_ur", "")),
        "hashtags": hashtags, "model": model,
    }
