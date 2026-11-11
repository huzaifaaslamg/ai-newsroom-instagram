# AI Newsroom — Instagram Automation

A bilingual (English + Urdu) global-news publisher for an Instagram Professional account. The workflow runs at **08:07 and 20:07 Asia/Karachi**. Each run builds:

1. An editorial news carousel of up to 7 slides (cover, four or five story slides, sources page).
2. A single-image explainer for the leading story.
3. Bilingual captions, source links, and relevant hashtags.

That produces **four feed posts per day** when Instagram publishing is enabled.

## How it works

- **GDELT DOC API** discovers recent news articles.
- **Trafilatura** extracts article text from publisher pages.
- **Gemini API** selects and summarises stories in English and Urdu.
- **Pillow** creates 1080 × 1350 JPEG cards. Graphics are rendered from text and shapes rather than generating synthetic photographs of real news events.
- **GitHub Actions** schedules the twice-daily runs.
- **Instagram Graph API with Instagram Login** publishes the image and carousel containers.

The public repository is used as a simple static origin for generated JPEGs. Instagram must be able to fetch each image URL without authentication.

## Important cost note

The project uses no Make.com, Zapier, paid image-generation service, or paid hosting. However, **Gemini Pro in the Gemini app is not the same thing as Gemini API access**. You need a Gemini API key from Google AI Studio. The text model configured by default has a published free API tier, subject to model availability, account eligibility, rate limits, and Google policy changes. Do not enable billing merely to make this project run.

The project generates its own visual layouts locally with Pillow, so it does not call a paid image-generation API. GitHub Actions and raw GitHub hosting are used within their applicable free-plan limits. The workflow can be delayed or skipped by GitHub service availability and free-plan quotas; it is not a guaranteed commercial scheduler.

Meta does not charge a separate fee for ordinary API content publishing, but Meta app setup, permission, account eligibility, access-token expiry, and platform limits apply.

## First-time setup

### 1. Create a Gemini API key

1. Open https://aistudio.google.com/app/apikey
2. Create an API key in a Google project.
3. Copy it once and keep it private.
4. Remember: this API key is separate from your Gemini Pro subscription.

### 2. Add the Gemini key to GitHub

Open this repository → **Settings → Secrets and variables → Actions → New repository secret**.

Create this secret:

| Name | Value |
|---|---|
| GEMINI_API_KEY | Your Google AI Studio API key |

Optional repository variable:

| Name | Value |
|---|---|
| GEMINI_MODEL | gemini-3.8-flash |

If the model is unavailable to your AI Studio account, select a text model shown in your AI Studio account that has a free API tier and update the variable.

### 3. Run a preview before connecting Instagram

1. Open the repository's **Actions** tab.
2. Select **AI Newsroom - Morning and Evening**.
3. Select **Run workflow**.
4. Choose morning or evening.
5. Open the run and inspect its logs.

The generated JPEGs and JSON manifest are committed under published/YYYYMMDD-morning/ or published/YYYYMMDD-evening/.

At this point publishing is off. The workflow only creates preview files.

### 4. Configure Instagram publishing

Use Meta's **Instagram API with Instagram Login** for your Creator or Business account. In your Meta developer app, set up Instagram Login, obtain an Instagram professional-account ID and an access token with these permissions:

- instagram_business_basic
- instagram_business_content_publish

For an app still in Development mode, the Instagram account may need to be added as an app tester and accept the invitation. Follow the current Meta developer setup flow; Meta can change app-review requirements.

Add these repository secrets:

| Name | Value |
|---|---|
| INSTAGRAM_USER_ID | Your Instagram professional account ID |
| INSTAGRAM_ACCESS_TOKEN | Access token with the two permissions above |

Optional repository variables:

| Name | Value |
|---|---|
| AUTO_PUBLISH | true only after preview/testing |
| INSTAGRAM_GRAPH_BASE | https://graph.instagram.com |
| INSTAGRAM_API_VERSION | v27.0 |

**Publishing is disabled unless AUTO_PUBLISH is exactly true.** Keep it unset while testing. Never paste access tokens or API keys into files, chat, issues, or commits.

### 5. Enable automated publishing

After both preview runs look correct and your Meta app/token are working:

1. Open **Settings → Secrets and variables → Actions → Variables**.
2. Add AUTO_PUBLISH with value true.
3. The next scheduled run creates and publishes one carousel and one single-image post.
4. The publishing state is saved in state/published.json to reduce duplicate posts on workflow reruns.

Each run publishes the carousel first and then the single-image post. If one post succeeds and the second fails, the saved state allows a rerun to skip the successful post.

## Schedule

The workflow uses GitHub's timezone-aware scheduled workflow syntax:

- 08:07 Asia/Karachi — [[\nmorning edition
- 20:07 Asia/Karachi — [[\evening edition

Each run publishes two posts when auto-publishing is enabled. GitHub may delay scheduled workflows during periods of high load.

## Safety and editorial safeguards

- At least four full-text articles are required before generating a post.
- The model is instructed to use supplied article text only and not invent sources, quotes, or statistics.
- Sensitive or disputed claims should be included only when separate supplied publishers corroborate them.
- Source domains appear on the source slide; source URLs are included in captions.
- Generated cards are summaries, not replacements for original reporting. Read the linked sources before relying on a claim.
- Public repository files and generated post assets are public. Never store credentials, private material, or personal data in this repository.
- News selection is imperfect. Review the previews and editorial output before turning on fully automatic publication.

## Project files

- main.py — run orchestration and manifest generation.
- news_fetcher.py — GDELN discovery and publisher article extraction.
- gemini_writer.py — bilingual summarisation, story validation and captions.
- image_generator.py — local 4:5 editorial image rendering.
- publish.py — Instagram image/carousel publishing and duplicate protection.
- .github/workflows/newsroom.yml — 08:07 and 20:07 Pakistan-time automation.

## Local preview

Python 3.12 is recommended.

~~~bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export GEMINI_API_KEY="your-key"  # Windows PowerShell: $env:GEMINI_API_KEY="your-key"
python main.py --slot morning
~~~

The generated assets are saved under published/. Do not set AUTO_PUBLISH=true until Meta credentials and a preview have been verified.
