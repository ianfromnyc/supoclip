# Setup

This guide covers the recommended Docker setup, local development mode, and the checks to perform after first boot.

## Requirements

### Required software

- Docker Desktop or a Docker Engine installation with Compose v2.20 or newer (the legacy v1 `docker-compose` binary cannot read this project's compose file)
- Git

### Required credentials

- `ASSEMBLY_AI_API_KEY`
- One LLM provider configuration:
  - `OPENAI_API_KEY` with `LLM=openai:...`
  - `GOOGLE_API_KEY` with `LLM=google-gla:...`
  - `ANTHROPIC_API_KEY` with `LLM=anthropic:...`
  - `LLM=ollama:...` with an available Ollama server, optionally `OLLAMA_BASE_URL`

### Optional credentials

- `PEXELS_API_KEY` for AI B-roll sourcing
- `NEXT_PUBLIC_DATAFAST_WEBSITE_ID` and `NEXT_PUBLIC_DATAFAST_DOMAIN` for DataFast analytics
- `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `SES_FROM_EMAIL` for hosted billing emails
- Stripe keys if you are running with monetization enabled
- Discord webhook URLs for feedback forwarding

## Recommended Setup: Docker

Docker is the intended path for running SupoClip because it starts the frontend, backend, worker, PostgreSQL, and Redis together with the expected wiring.

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd supoclip
```

### 2. Create a local environment file

```bash
cp .env.example .env
```

Then edit `.env` and set at least:

```env
ASSEMBLY_AI_API_KEY=your_assemblyai_key
LLM=google-gla:gemini-3-flash-preview
GOOGLE_API_KEY=your_google_key

# Optional: DataFast analytics
NEXT_PUBLIC_DATAFAST_WEBSITE_ID=dfid_xxxxx
NEXT_PUBLIC_DATAFAST_DOMAIN=your-domain.com
NEXT_PUBLIC_DATAFAST_ALLOW_LOCALHOST=false
```

You do not need to invent the auth secrets. On every run, `./start.sh` replaces
`BACKEND_AUTH_SECRET`, `BETTER_AUTH_SECRET`, and `APP_SETTINGS_ENCRYPTION_KEY`
with `openssl rand -hex 32` values if they are empty or still set to the
placeholders shipped in `.env.example`, and writes them back to `.env`. Secrets
you have already customized are never rotated. If you invoke `docker compose`
directly instead of using `./start.sh`, set all three to random values yourself:
the backend treats the known placeholder strings as no secret at all and answers
signed requests with `500 Server authentication secret is not configured`.

### 3. Start the stack

Fastest option:

```bash
./start.sh
```

Manual equivalent:

```bash
docker-compose up -d --build
```

### 4. Wait for services to become healthy

```bash
docker-compose logs -f
docker-compose ps
```

You should see these services:

- `supoclip-frontend`
- `supoclip-backend`
- `supoclip-mcp`
- `supoclip-worker`
- `supoclip-postgres`
- `supoclip-redis`

### 5. Open the application

- Frontend: `http://localhost:3001`
- Backend API: `http://localhost:8000`
- FastAPI docs: `http://localhost:8000/docs`

## What Docker Starts

The default Compose stack contains six services. Every published port is bound
to `127.0.0.1`, and `postgres` publishes no port at all:

- `frontend`
  - Next.js application listening on `3107` in the container, published as `3001` on the host
  - Proxies authenticated requests to the backend
- `backend`
  - FastAPI API on port `8000`
  - Provides task, media, billing, admin, and feedback endpoints
- `mcp`
  - `supoclip-mcp` server on port `SUPOCLIP_MCP_PORT` (default `9100`)
  - Thin MCP client over the REST API, see `mcp/README.md`
- `worker`
  - ARQ background worker
  - Processes long-running video jobs from Redis
- `postgres`
  - Stores users, sessions, tasks, sources, clips, billing metadata, and auth rotation state
- `redis`
  - Backs the job queue and progress event flow

## First-Run Checklist

After the stack is up:

1. Load the homepage at `http://localhost:3001`.
2. Create an account or sign in. Sign-ups are disabled by default, including when
   `DISABLE_SIGN_UP` is unset; set it to `false` in `.env` and restart the
   frontend to register the first account, then close it again if you like.
3. Submit a YouTube URL or upload a video file.
4. Open the task page and confirm progress updates appear.
5. Wait for clip generation to finish.
6. Open the clips list and verify playback and download work.
7. If DataFast is enabled, open browser devtools and confirm `/js/script.js` and `/api/events` load from your own domain.
8. Trigger one successful action such as sign-up, sign-in, task creation, feedback submission, or waitlist submission and verify the goal arrives in DataFast.

## Local Development Without Docker

Use this mode if you need to iterate on a single app directly. You still need PostgreSQL and Redis running somewhere.

### Backend

```bash
cd backend
uv venv .venv
source .venv/bin/activate
uv sync
uvicorn src.main_refactored:app --reload --host 0.0.0.0 --port 8000
```

In a second terminal:

```bash
cd backend
source .venv/bin/activate
arq src.workers.tasks.WorkerSettings
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Required local dependencies

- Python 3.11+
- Node.js compatible with Next.js 15
- PostgreSQL
- Redis
- FFmpeg available to the backend environment

## Data and Volumes

With Docker, SupoClip stores persistent data in named volumes:

- `postgres_data`
- `redis_data`
- `uploads`
- `clips`

The backend also mounts these local directories:

- `backend/fonts`
- `backend/transitions`

## Hosted Mode Versus Self-Hosted Mode

SupoClip defaults to self-host mode:

```env
SELF_HOST=true
```

When `SELF_HOST=false`, monetization and hosted billing flows become active. That mode requires additional Stripe and backend auth configuration. See [Configuration](./configuration.md).

## Production Setup Notes

For anything beyond local experimentation:

- Confirm `BETTER_AUTH_SECRET`, `BACKEND_AUTH_SECRET`, and
  `APP_SETTINGS_ENCRYPTION_KEY` hold real random values, not the `.env.example`
  placeholders. `./start.sh` generates them for you; direct `docker compose`
  users must set them by hand
- Decide whether sign-ups stay closed (the default on every deployment method,
  even with `DISABLE_SIGN_UP` unset) or are opened to the public with an explicit
  `DISABLE_SIGN_UP=false`
- Put the app behind HTTPS
- Set `NEXT_PUBLIC_APP_URL` to your deployed frontend origin
- Use persistent storage and backups for PostgreSQL
- Keep API keys outside version control
- Decide whether you want self-host mode or monetized hosted mode before launch
- Verify all callback URLs and origins match your deployed domain
- If using DataFast, set `NEXT_PUBLIC_DATAFAST_DOMAIN` to the deployed root domain you want tracked
- For hosted billing, create and verify both Stripe monthly prices before deploy: Pro at `$10/month` and Scale at `$50/month`

## Public access with Cloudflare Tunnel (optional)

If you want SupoClip reachable from the internet without opening ports or
running your own reverse proxy, the Compose stack ships an optional
`cloudflared` service behind the `tunnel` profile. It makes an outbound-only
connection to Cloudflare, so no port forwarding and no firewall holes are
needed. TLS terminates at Cloudflare's edge and the hop from the edge to your
containers travels inside the tunnel over plain HTTP.

### 1. Create the tunnel in Cloudflare

Ingress rules live in the Cloudflare dashboard, not in this repository:

1. Open Cloudflare Zero Trust and go to **Networks → Tunnels → Create a tunnel**.
2. Choose the **Cloudflared** connector and give the tunnel a name.
3. Copy the tunnel token that the dashboard shows you.
4. In the tunnel's **Public Hostname** tab, add two hostnames on your zone:
   - `app.<your-domain>` → service **HTTP** `frontend:3107`
   - `api.<your-domain>` → service **HTTP** `backend:8000`

Those are container names and container ports on the Compose network, not the
host's `127.0.0.1:3001` / `127.0.0.1:8000` published ports. The API hostname is
required because the browser talks to the backend directly for video uploads
and caption templates.

Note that Cloudflare caps proxied request bodies well below SupoClip's own
1 GB upload limit — 100 MB on Free and Pro plans (more on Business/Enterprise).
Uploads larger than your plan's cap fail at Cloudflare's edge with HTTP 413
before ever reaching the backend, so through the tunnel the practical upload
limit is your Cloudflare plan's, not SupoClip's. Larger files still work from
the host itself via `http://localhost:3001`, or use YouTube URLs, which the
backend downloads server-side without passing through the tunnel.

### 2. Add the tunnel settings to `.env`

```env
CLOUDFLARE_TUNNEL_TOKEN=your_tunnel_token

NEXT_PUBLIC_APP_URL=https://app.example.com
NEXT_PUBLIC_API_URL=https://api.example.com
BETTER_AUTH_URL=https://app.example.com
CORS_ORIGINS=https://app.example.com,http://localhost:3107,http://sp.localhost:3107,http://supoclip.localhost:3107

FRONTEND_BUILD_TARGET=runner
NODE_ENV=production
```

Both of those last two matter for a public deployment. Compose builds the
frontend from the `development` Dockerfile target and runs it with
`NODE_ENV=development` unless you say otherwise, which means publishing a
Next.js dev server: unminified sources and full stack traces on error pages.
`FRONTEND_BUILD_TARGET=runner` selects the standalone production stage instead.

Sign-ups stay closed unless you open them: the frontend closes registration
unless `DISABLE_SIGN_UP` is explicitly `false`, so a hostname that resolves does
not by itself accept registrations. Set `DISABLE_SIGN_UP=false` to let the public
register, and consider putting the app hostname behind Cloudflare Access rather
than opening sign-ups at all.

The three auth secrets need no manual attention here — `./start.sh` replaces
`BACKEND_AUTH_SECRET`, `BETTER_AUTH_SECRET`, and `APP_SETTINGS_ENCRYPTION_KEY`
with random values while they are still at their placeholders. If you bring the
stack up with `docker compose` directly, set them yourself before exposing it.

### 3. Start the stack with the tunnel

`./start.sh` detects `CLOUDFLARE_TUNNEL_TOKEN` and enables the profile for you
by exporting `COMPOSE_PROFILES=tunnel`. It also warns if `NEXT_PUBLIC_APP_URL`,
`NEXT_PUBLIC_API_URL`, or `BETTER_AUTH_URL` are not `https://` URLs, or if
`CORS_ORIGINS` does not include `NEXT_PUBLIC_APP_URL`.

```bash
./start.sh
```

Manual equivalent:

```bash
docker compose --profile tunnel up -d --build
```

### 4. Verify

```bash
docker compose --profile tunnel ps
docker compose logs cloudflared
```

`cloudflared` should report healthy, and its logs should contain
`Registered tunnel connection`. Then browse to `https://app.<your-domain>`.

### Caveats

- `NEXT_PUBLIC_*` values are baked into the production frontend image at build
  time. After changing them, re-run `./start.sh` so the image is rebuilt.
- Setting `BETTER_AUTH_URL` to an `https://` origin means signing in through
  `http://localhost:3001` no longer issues working cookies. That is the expected
  trade-off; use the tunnel hostname instead.
- A plain `docker compose down` never stops `cloudflared`: `./start.sh` exports
  `COMPOSE_PROFILES` only for its own process, so your shell always needs the
  flag. Use `docker compose --profile tunnel down`.
- Bringing the profile up manually with an empty or invalid
  `CLOUDFLARE_TUNNEL_TOKEN` leaves `cloudflared` crash-looping, because the
  service restarts `unless-stopped`. Check `docker compose logs cloudflared`.
  `./start.sh` sidesteps this by enabling the profile only when the token is
  non-empty.

## Useful Commands

### Start or rebuild

```bash
docker-compose up -d --build
```

### Stream logs

```bash
docker-compose logs -f
docker-compose logs -f backend
docker-compose logs -f worker
```

With `VAAPI_ENABLED=true` in `.env` the backend and worker run as the
`backend-vaapi` and `worker-vaapi` services, so target those names instead
(e.g. `docker-compose logs -f worker-vaapi`). The container names
(`supoclip-backend`, `supoclip-worker`) are the same in both modes, so plain
`docker logs supoclip-worker` always works.

### Stop services

```bash
docker-compose down
```

### Reset containers and volumes

```bash
docker-compose down -v
docker-compose up -d --build
```

Warning: `docker-compose down -v` deletes database and Redis data.

## Next Steps

- Review [Configuration](./configuration.md) before changing defaults
- Review [App Guide](./app-guide.md) to understand the UI and workflows
- Review [Troubleshooting](./troubleshooting.md) if tasks do not process correctly
