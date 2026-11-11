"""Build posts for one morning or evening newsroom run."""
from __future__ import annotations
import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from gemini_writer import create_news_brief
from image_generator import generate_assets
from news_fetcher import get_candidate_articles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOG = logging.getLogger("newsroom")
PKT = ZoneInfo("Asia/Karachi")

def choose_slot(value: str) -> str:
    if value in ("morning", "evening"):
        return value
    return "morning" if datetime.now(PKT).hour < 14 else "evening"

def main() -> int:
    parser = argparse.ArgumentParser(description="Build AI Newsroom Instagram assets.")
    parser.add_argument("--slot", choices=["auto", "morning", "evening"], default="auto")
    args = parser.parse_args()

    now = datetime.now(PKT)
    slot = choose_slot(args.slot)
    date_label = now.strftime("%Y-%m-%d")
    run_id = f"{now.strftime('%Y%m%d')}-{slot}"
    output_dir = Path("published") / run_id

    LOG.info("Starting %s edition for %s (Asia/Karachi)", slot, date_label)
    candidates = get_candidate_articles(max_candidates=18)
    LOG.info("Extracted %s full-text articles.", len(candidates))
    if len(candidates) < 4:
        LOG.warning("Not enough full-text sources. Skipping this run rather than guessing.")
        return 0

    brief = create_news_brief(candidates, slot, date_label)
    assets = generate_assets(brief, str(output_dir))
    manifest = {
        "project": "AI Newsroom",
        "date": date_label,
        "slot": slot,
        "run_id": run_id,
        "timezone": "Asia/Karachi",
        "generated_at": now.isoformat(),
        "model": brief["model"],
        "stories": brief["stories"],
        "posts": assets,
        "publishing_note": "Preview assets only until Instagram publishing is enabled.",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    LOG.info("Generated post assets and manifest: %s", manifest_path)
    print(str(manifest_path))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
