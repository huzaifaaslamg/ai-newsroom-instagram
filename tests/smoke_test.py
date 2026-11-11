"""Fast offline smoke test for the editorial image renderer."""
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from image_generator import generate_assets

def main():
    sample_sources = [{
        "title": "A sample article title used only for renderer testing.",
        "url": "https://example.com/sample-story",
        "date": "2026-11-10T08:00:00+00:00",
        "domain": "example.com",
        "source_country": "US",
    }]
    stories = []
    for idx in range(4):
        stories.append({
            "category": ["WORLD", "TECH", "BUSINESS", "CLIMATE"][idx],
            "headline_en": f"Sample English headline for test story {idx + 1}",
            "headline_ur": "یہ صرف ڈیزائن کی جانچ کے لیے ایک نمونہ سرخی ہے",
            "summary_en": "This is sample English summary text used to check layout and wrapping.",
            "summary_ur": "یہ اردو خلاصہ صرف ڈیزائن، فونٹ اور متن کی ترتیب جانچنے کے لیے ہے۔",
            "why_en": "The smoke test checks that generated cards remain readable.",
            "why_ur": "یہ ٹیسٹ بنائی گئی تصاویر کی بنیادی جانچ کرتا ہے۔",
            "sources": sample_sources,
        })
    brief = {
        "date": "2026-11-10",
        "slot": "morning",
        "stories": stories,
        "carousel_caption": "Sample carousel caption.\nنمونہ کیپشن۔",
        "single_caption": "Sample single caption.\nنمونہ کیپشن۔",
    }
    with TemporaryDirectory() as directory:
        assets = generate_assets(brief, directory)
        files = assets["carousel"]["files"] + [assets["single"]["file"]]
        assert len(assets["carousel"]["files"]) == 6, "Expected cover + four stories + source slide."
        for file_name in files:
            path = Path(file_name)
            assert path.exists() and path.stat().st_size > 5_000, f"Missing or empty image: {path}"
            with Image.open(path) as image:
                assert image.format == "JPEG", f"Unexpected format: {image.format}"
                assert image.size == (1080, 1350), f"Unexpected size: {image.size}"
        print(f"Renderer smoke test passed: {len(files)} JPEGs at 1080x1350.")

if __name__ == "__main__":
    main()
