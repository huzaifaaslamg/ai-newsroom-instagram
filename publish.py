"""Publish posts using the official Instagram API with Instagram Login."""
from __future__ import annotations
import argparse
import json
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOG = logging.getLogger("instagram-publisher")

class InstagramPublisher:
    def __init__(self):
        self.user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
        self.token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        self.base = (os.getenv("INSTAGRAM_GRAPH_BASE") or "https://graph.instagram.com").rstrip("/")
        self.version = (os.getenv("INSTAGRAM_API_VERSION") or "v25.0").strip()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "AI-Newsroom/1.0"})

    def endpoint(self, path: str) -> str:
        return f"{self.base}/{self.version}/{path.lstrip('/')}"

    def post(self, path: str, data: dict) -> dict:
        payload = dict(data)
        payload["access_token"] = self.token
        response = self.session.post(self.endpoint(path), data=payload, timeout=45)
        if not response.ok:
            raise RuntimeError(
                f"Instagram API failed ({response.status_code}): {response.text[:1200]}"
            )
        return response.json()

    def get(self, path: str, params: dict) -> dict:
        payload = dict(params)
        payload["access_token"] = self.token
        response = self.session.get(self.endpoint(path), params=payload, timeout=30)
        if not response.ok:
            raise RuntimeError(
                f"Instagram API failed ({response.status_code}): {response.text[:1200]}"
            )
        return response.json()

    def wait_until_ready(self, container_id: str) -> None:
        for attempt in range(24):
            result = self.get(container_id, {"fields": "status_code"})
            state = result.get("status_code")
            if state == "FINISHED":
                return
            if state in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"Instagram media container status: {state}")
            time.sleep(5)
        raise TimeoutError("Instagram did not finish processing the media container.")

    def public_image_url(self, relative_path: str) -> str:
        repository = os.getenv("GITHUB_REPOSITORY", "").strip()
        branch = os.getenv("GITHUB_REF_NAME", "main").strip()
        if not repository:
            raise RuntimeError("GITHUB_REPOSITORY is not available.")
        relative = quote(relative_path.lstrip("/"), safe="/")
        return f"https://raw.githubusercontent.com/{repository}/{branch}/{relative}"

    def check_public_jpeg(self, url: str) -> None:
        response = self.session.get(url, stream=True, timeout=30)
        try:
            if response.status_code != 200:
                raise RuntimeError(
                    f"Image is not publicly accessible (HTTP {response.status_code}): {url}"
                )
            content_type = response.headers.get("content-type", "").lower()
            if "image/jpeg" not in content_type and "image/jpg" not in content_type:
                raise RuntimeError(
                    f"Expected a public JPEG; received {content_type or 'unknown content type'}."
                )
        finally:
            response.close()

    def publish_single(self, image_path: str, caption: str, alt_text: str) -> str:
        image_url = self.public_image_url(image_path)
        self.check_public_jpeg(image_url)
        container = self.post(
            f"{self.user_id}/media",
            {"image_url": image_url, "caption": caption[:2190], "alt_text": alt_text[:1000]},
        )
        container_id = container.get("id")
        if not container_id:
            raise RuntimeError("Instagram returned no single-image container ID.")
        self.wait_until_ready(container_id)
        published = self.post(
            f"{self.user_id}/media_publish", {"creation_id": container_id}
        )
        media_id = published.get("id", "")
        LOG.info("Published single-image post. Media ID: %s", media_id)
        return media_id

    def publish_carousel(self, image_paths: list[str], caption: str, alt_text: str) -> str:
        if not 2 <= len(image_paths) <= 10:
            raise ValueError("Instagram carousels need between 2 and 10 images.")
        children = []
        for image_path in image_paths:
            image_url = self.public_image_url(image_path)
            self.check_public_jpeg(image_url)
            child = self.post(
                f"{self.user_id}/media",
                {
                    "image_url": image_url,
                    "is_carousel_item": "true",
                    "alt_text": alt_text[:1000],
                },
            )
            child_id = child.get("id")
            if not child_id:
                raise RuntimeError("Instagram returned no carousel-item container ID.")
            self.wait_until_ready(child_id)
            children.append(child_id)

        parent = self.post(
            f"{self.user_id}/media",
            {
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption[:2190],
            },
        )
        parent_id = parent.get("id")
        if not parent_id:
            raise RuntimeError("Instagram returned no carousel container ID.")
        self.wait_until_ready(parent_id)
        published = self.post(
            f"{self.user_id}/media_publish", {"creation_id": parent_id}
        )
        media_id = published.get("id", "")
        LOG.info("Published carousel post. Media ID: %s", media_id)
        return media_id

def main() -> int:
    parser = argparse.ArgumentParser(description="Publish generated newsroom assets.")
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    enabled = os.getenv("AUTO_PUBLISH", "false").lower() == "true"
    if not enabled:
        LOG.warning("AUTO_PUBLISH is not true. Preview files will not be posted.")
        return 0

    user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    if not user_id or not token:
        LOG.warning("Instagram credentials missing. No post was published.")
        return 0

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state_path = Path("state/published.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    run_id = manifest["run_id"]
    run_state = state.setdefault(run_id, {})
    publisher = InstagramPublisher()

    if run_state.get("carousel_media_id"):
        LOG.info("Carousel already published for %s; skipping duplicate.", run_id)
    else:
        carousel = manifest["posts"]["carousel"]
        media_id = publisher.publish_carousel(
            carousel["files"], carousel["caption"], carousel.get("alt_text", "")
        )
        run_state["carousel_media_id"] = media_id
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    if run_state.get("single_media_id"):
        LOG.info("Single-image post already published for %s; skipping duplicate.", run_id)
    else:
        single = manifest["posts"]["single"]
        media_id = publisher.publish_single(
            single["file"], single["caption"], single.get("alt_text", "")
        )
        run_state["single_media_id"] = media_id
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    LOG.info("The %s edition completed both posts.", manifest["slot"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
