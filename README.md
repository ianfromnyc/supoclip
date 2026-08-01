# Fuck OpusClip.

... because good video clips shouldn't come with ugly watermarks or platform lock-in.

<p align="center">
  <a href="https://www.supoclip.com">
    <img src="assets/banner.png" alt="SupoClip Banner" width="100%" />
  </a>
</p>

SupoClip gives you AI-powered video clipping capabilities in an open-source package you can run yourself, customize, and inspect. Use the hosted version when you want the convenience of managed infrastructure, or self-host when you want full control.

> For the hosted version, sign up for the waitlist here: [SupoClip Hosted](https://www.supoclip.com)

## Why SupoClip Exists

### The OpusClip Problem

OpusClip is undeniably powerful. It's an AI video clipping tool that can turn long-form content into viral short clips with features like:

- AI-powered clip generation from long videos
- Automated captions with 97%+ accuracy
- Virality scoring to predict viral potential
- Multi-language support (20+ languages)
- Brand templates and customization

**But here's the catch:**

- **Usage limits**: Processing minutes are capped by plan
- **Watermarks**: Some exports can include platform branding
- **Processing limits**: Even paid plans have strict minute limits
- **Vendor lock-in**: Your content and workflows are tied to their platform

### The SupoClip Solution

SupoClip provides the same core functionality with more control:

→ ✅ **Self-Hostable** - Run it on your own infrastructure

→ ✅ **No Watermarks** - Your content stays yours

→ ✅ **Open Source** - Full transparency, community-driven development

→ ✅ **Hosted Option** - Use SupoClip without managing servers

→ ✅ **Unlimited Usage** - Process as many videos as your hardware can handle

→ ✅ **Customizable** - Modify and extend the codebase to fit your needs

## Quick Start

### Prerequisites

- Docker and Docker Compose
- An AssemblyAI API key (for transcription) - [Get one here](https://www.assemblyai.com/) — or set `TRANSCRIPTION_PROVIDER=whisperx` and enable the `whisperx` add-on for fully local transcription, no key needed
- An LLM provider for AI analysis - OpenAI, Google, Anthropic, or Ollama

### 1. Clone and Configure

```bash
git clone https://github.com/FujiwaraChoki/supoclip.git
cd supoclip
cp docker-compose.yml.example docker-compose.yml
```

Both `docker-compose.yml` and `.env` are yours to edit and stay untracked, so
your setup survives every `git pull`. (`./start.sh` creates either one for you
if it is missing.)

Create a `.env` file in the root directory:

```env
# Required: Video transcription (not needed with TRANSCRIPTION_PROVIDER=whisperx)
ASSEMBLY_AI_API_KEY=your_assemblyai_api_key

# Required: Choose ONE LLM provider and set its API key
# Option A: Google Gemini (recommended - fast & cost-effective)
LLM=google-gla:gemini-3-flash-preview
GOOGLE_API_KEY=your_google_api_key

# Option B: OpenAI GPT-5.2 (best reasoning)
# LLM=openai:gpt-5.2
# OPENAI_BASE_URL=https://api.openai.com/v1
# OPENAI_API_KEY=your_openai_api_key

# Option C: Anthropic Claude
# LLM=anthropic:claude-4-sonnet
# ANTHROPIC_API_KEY=your_anthropic_api_key

# Option D: any OpenAI-compatible endpoint (llama.cpp, vLLM, Ollama, OpenRouter, …)
# Same variable as Option B — only the URL changes
# LLM=openai:gpt-oss:20b
# OPENAI_BASE_URL=http://localhost:11434/v1  # Your endpoint; use host.docker.internal in Docker
# OPENAI_API_KEY=  # Only if the endpoint requires one
# (LLM=ollama:* with OLLAMA_BASE_URL still works, but is deprecated)

# Optional: Auth secret — `./start.sh` generates one for you if this is left empty
BETTER_AUTH_SECRET=  # or set it yourself: openssl rand -hex 32

# Optional: DataFast analytics
# Track your deployed domain in DataFast
# NEXT_PUBLIC_DATAFAST_WEBSITE_ID=dfid_xxxxx
# NEXT_PUBLIC_DATAFAST_DOMAIN=your-domain.com
# NEXT_PUBLIC_DATAFAST_ALLOW_LOCALHOST=false

# Optional: Amazon SES for waitlist confirmation emails
# AWS_REGION=us-east-1
# AWS_ACCESS_KEY_ID=your_aws_access_key_id
# AWS_SECRET_ACCESS_KEY=your_aws_secret_access_key
# SES_FROM_EMAIL="SupoClip <onboarding@example.com>"

# Optional: YouTube metadata provider
# `yt_dlp` preserves the existing metadata behavior
# `youtube_data_api` uses the official API first, then falls back to yt-dlp
# YOUTUBE_METADATA_PROVIDER=yt_dlp
# YOUTUBE_DATA_API_KEY=your_youtube_data_api_key
```

### 2. Start the Services

```bash
./start.sh
```

`start.sh` validates your `.env`, generates secure random values for any auth
secrets still at their defaults, and brings the stack up. If you prefer running
`docker-compose up -d` directly, set `BACKEND_AUTH_SECRET`,
`BETTER_AUTH_SECRET`, and `APP_SETTINGS_ENCRYPTION_KEY` to distinct random
values (`openssl rand -hex 32`) first — Compose alone substitutes publicly
known defaults for anything left unset.

This starts (all published ports are bound to `127.0.0.1`):
- **Frontend**: http://localhost:3001
- **Backend API**: http://localhost:8000 (docs at /docs)
- **Worker**: ARQ video-processing worker, no published port
- **MCP server**: localhost:9100 (`SUPOCLIP_MCP_PORT`)
- **Redis**: localhost:6379
- **PostgreSQL**: not published; reachable only from the other containers

### Optional add-ons

Extra services live in `docker/options/` and are off by default. Each one is two
steps — uncomment its line (and the `include:` line above it) at the top of your
`docker-compose.yml`, then copy its settings file — followed by
`docker compose up -d`:

| Add-on | What it does | Its settings |
|--------|--------------|--------------|
| `vaapi.yml` | Intel/AMD GPU video encoding | `cp .env.vaapi.example .env.vaapi` |
| `whisperx.yml` | Local transcription, no AssemblyAI account | `cp .env.whisperx.example .env.whisperx` |
| `tunnel.yml` | Public ingress via Cloudflare Tunnel | `cp .env.tunnel.example .env.tunnel` |
| `llama-*.yml` | Local LLM via llama.cpp — uncomment exactly ONE variant matching your hardware | `cp .env.llama.example .env.llama`, plus `LLM=openai:local` and `OPENAI_BASE_URL=http://llama:8080/v1` in `.env` |

Every `.env.<option>` is git-ignored and holds only that add-on's configuration,
so it is short enough to read in full. To turn an add-on off, comment its
include line back out and run `docker compose up -d --remove-orphans` — deleting
the settings file alone never stops the service, because Docker reads it only
when it creates a container. For `tunnel.yml` that matters: a running
`cloudflared` keeps its token and keeps publishing the app. Delete the
`.env.<option>` afterwards; `./start.sh` warns if an add-on is enabled without
its file, or vice versa.

Details in [docs/setup.md](docs/setup.md).

### 3. Wait for Initialization

First-time startup takes a few minutes. Check progress with:

```bash
docker-compose logs -f
```

Wait until you see health checks passing for all services.

### 4. Access the App

Open http://localhost:3001 in your browser, create an account, and start clipping!

If you enable DataFast, also verify that:
- `/js/script.js` loads from your own app domain
- `/api/events` requests are proxied through your app domain
- custom goals appear after successful sign-up, sign-in, task creation, billing, feedback, or waitlist actions

### Troubleshooting

**Backend fails to start with API key error:**
- Make sure you've set the correct LLM provider AND its corresponding API key in `.env`
- Default is `google-gla:gemini-3-flash-preview` which requires `GOOGLE_API_KEY`
- If using `openai:gpt-5.2` against hosted OpenAI, you MUST set `OPENAI_API_KEY`
- For a self-hosted OpenAI-compatible endpoint, change `OPENAI_BASE_URL` — no key needed
  unless the endpoint requires one (Ollama: `http://localhost:11434/v1` locally,
  `http://host.docker.internal:11434/v1` for Docker)
- Never blank out `OPENAI_BASE_URL`. An empty value is read as an empty endpoint, not as
  "use the default", and every request fails to connect
- Rebuild after changing `.env`: `docker-compose up -d --build`

**Videos stay queued / never process:**
- Check worker logs: `docker-compose logs -f worker`
- Ensure Redis is healthy: `docker-compose logs redis`
- Verify API keys are correct

**`docker compose` says no configuration file was found:**
- Make your own copy first: `cp docker-compose.yml.example docker-compose.yml`
  (or just run `./start.sh`, which does it for you)

**An add-on you enabled is not running, or is running unconfigured:**
- Both the `include:` line and the add-on's own line must be uncommented in
  `docker-compose.yml`; check with `docker compose config --services`
- Its `.env.<option>` must exist too — `cp .env.<option>.example .env.<option>`.
  Missing scoped files are skipped silently by design, so the service comes up
  with no configuration at all
- A typo in an include path fails the parse outright — Compose has no way to
  skip a missing file

**A setting in `.env` seems to be ignored:**
- Add-on settings moved into `.env.<option>` files, and the compose file no
  longer passes the old names through. That covers `VIDEO_ENCODER`,
  `VAAPI_DEVICE`, `TRANSCRIPTION_PROVIDER`, every `WHISPERX_*`, `HF_TOKEN`, and
  `CLOUDFLARE_TUNNEL_TOKEN`
- The reverse also holds: `LLM` and `OPENAI_BASE_URL` must be in `.env`, not
  `.env.llama`, because `environment:` entries outrank any env file

**Upgrading from the old profile-based setup:**
- Delete `COMPOSE_PROFILES` and `VAAPI_ENABLED` from `.env` — both are gone
- Run `docker compose down --remove-orphans` once, to clear the old
  `backend-vaapi`/`worker-vaapi`/`config-guard` containers
- `cp docker-compose.yml.example docker-compose.yml` and re-enable what you
  used by uncommenting its include
- Move each add-on's settings out of `.env` and into its `.env.<option>` (see
  the list above), copying the matching `.example` as a starting point

**YouTube titles or duration lookup is failing:**
- `YOUTUBE_METADATA_PROVIDER=yt_dlp` keeps the old metadata path
- `YOUTUBE_METADATA_PROVIDER=youtube_data_api` requires YouTube Data API v3 enabled in Google Cloud
- Prefer `YOUTUBE_DATA_API_KEY`; if it is unset, the backend will try `GOOGLE_API_KEY`
- The backend will automatically fall back to the other metadata provider if the primary one fails
- `videos.list` costs 1 quota unit per request

**Performance tuning (default is fast mode):**
- `DEFAULT_PROCESSING_MODE=fast|balanced|quality`
- `FAST_MODE_MAX_CLIPS=4` to cap clip count in fast mode
- `FAST_MODE_TRANSCRIPT_MODEL=nano` for fastest transcript model
- View aggregate metrics: `GET /tasks/metrics/performance`

**Prisma errors on Windows:**
- Run `docker-compose down -v` to clear volumes
- Run `docker-compose up -d --build` to rebuild

**Frontend shows database errors:**
- Wait for PostgreSQL to fully initialize (check logs)
- The database is automatically created on first run

**Font picker is empty / cannot select or upload fonts:**
- Add fonts to `backend/fonts/` – see [backend/fonts/README.md](backend/fonts/README.md) for TikTok Sans and custom fonts
- Ensure `BACKEND_AUTH_SECRET` is set in `.env` when using the hosted/monetized setup
- Font upload is Pro-only when monetization is enabled; self-hosted users can upload freely

**Subscription emails are not sending:**
- Set `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `SES_FROM_EMAIL` in `.env`
- `SES_FROM_EMAIL` must be a verified identity/domain in Amazon SES
- The backend sends the “thank you for subscribing” email on `checkout.session.completed`
- The backend sends the “sorry to see you go” email on `customer.subscription.deleted`

## Testing

SupoClip now has a layered automated test setup:

- `pytest` for backend unit and integration tests
- `Vitest` and Testing Library for frontend route and component coverage
- `Playwright` for a small seeded browser smoke suite

Repo-level entrypoints:

```bash
make test
make test-backend
make test-frontend
make test-e2e
make test-ci
```

App-level entrypoints:

```bash
cd backend && uv sync --all-groups && .venv/bin/pytest
cd frontend && npm install && npm run test:coverage
cd frontend && npm run test:e2e
```

Local test runs expect PostgreSQL and Redis to be available. The easiest path is to start the stack with `docker-compose up -d`, then run the commands above. CI runs the same layers in GitHub Actions with Postgres and Redis service containers.

## Documentation

Detailed documentation now lives in [`docs/`](docs/README.md).

Start with:

- [`docs/setup.md`](docs/setup.md)
- [`docs/configuration.md`](docs/configuration.md)
- [`docs/app-guide.md`](docs/app-guide.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/api-reference.md`](docs/api-reference.md)
- [`docs/development.md`](docs/development.md)
- [`docs/troubleshooting.md`](docs/troubleshooting.md)

## Hosted Billing Emails

When you run SupoClip with monetization enabled (`SELF_HOST=false`), subscription lifecycle emails are sent through Amazon SES by the backend:

- `checkout.session.completed` sends the thank-you-for-subscribing email
- `customer.subscription.deleted` sends the sorry-to-see-you-go email

Required env vars for this flow:

- `AWS_REGION`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `SES_FROM_EMAIL`
- `BACKEND_AUTH_SECRET`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_PRICE_ID`

### Local Development (Without Docker)

See [AGENTS.md](AGENTS.md) for detailed development instructions.

## License

SupoClip is released under the AGPL-3.0 License. See [LICENSE](LICENSE) for details.

Contributions are accepted under the terms in [CONTRIBUTING.md](CONTRIBUTING.md),
including a license grant that allows the project owner to sublicense and
relicense contributed code.
