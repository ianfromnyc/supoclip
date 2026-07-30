# Setup

This guide covers the recommended Docker setup, local development mode, and the checks to perform after first boot.

## Requirements

### Required software

- Docker Desktop or a Docker Engine installation with Compose v2.24 or newer — the version that introduced the top-level `include:` key the optional add-ons use. (The legacy v1 `docker-compose` binary cannot read this project's compose file at all. Validated against Compose v5.x.)
- Git

### Required credentials

- `ASSEMBLY_AI_API_KEY`
- One LLM provider configuration:
  - `OPENAI_API_KEY` with `LLM=openai:...` and the shipped
    `OPENAI_BASE_URL=https://api.openai.com/v1`
  - `GOOGLE_API_KEY` with `LLM=google-gla:...`
  - `ANTHROPIC_API_KEY` with `LLM=anthropic:...`
  - `LLM=openai:...` with `OPENAI_BASE_URL` changed to a self-hosted
    OpenAI-compatible endpoint (llama.cpp, vLLM, Ollama, …); `OPENAI_API_KEY`
    only if it needs one. `LLM=ollama:...` with `OLLAMA_BASE_URL` still works
    but is deprecated

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

### 2. Create your local configuration files

```bash
cp .env.example .env
cp docker-compose.yml.example docker-compose.yml
```

Neither copy is tracked in git. That is deliberate: `docker-compose.yml` is
where you turn optional add-ons on (see [Optional add-ons](#optional-add-ons)),
and keeping it out of version control means your choices are never disturbed by
a `git pull`. `./start.sh` makes the compose copy for you if it is missing.

Optional add-ons each add a third copy of the same shape,
`cp .env.<option>.example .env.<option>` — but only for the ones you enable, so
skip them for now.

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

## Optional add-ons

Anything that only some deployments need lives in its own compose file under
`docker/options/`, and the base stack does not know about them. Your
`docker-compose.yml` starts with the whole list commented out:

```yaml
# include:
#   - path: docker/options/vaapi.yml        # Intel/AMD GPU video encoding …
#   - path: docker/options/whisperx.yml     # local transcription …
#   - path: docker/options/tunnel.yml       # Cloudflare Tunnel ingress …
#   - path: docker/options/llama-cpu.yml    # local LLM, llama.cpp server, CPU only
#   …
```

Enabling one takes two steps. First uncomment its line **and** the `include:`
line above it. Then copy its settings file:

```bash
cp .env.vaapi.example .env.vaapi          # or .env.whisperx / .env.tunnel / .env.llama
```

Then `docker compose up -d`. To disable it, comment the line back out and run
`docker compose up -d --remove-orphans` so the service is torn down; delete the
`.env.<option>` too, or `./start.sh` will point out the mismatch.

Rules worth internalising:

- **Both halves or neither.** An include with no settings file starts an
  unconfigured service; a settings file with no include configures something
  that is not running. `./start.sh` warns about either.
- **Uncomment exactly one `llama-*.yml`.** They all define the same `llama`
  service, one per hardware backend, and share one `.env.llama`.
- **A wrong include path is fatal.** Compose has no optional includes: a `path`
  that does not exist stops the whole stack from parsing. A missing
  `.env.<option>` is the opposite — silently skipped, which is what lets the
  base stack ignore add-ons you have not enabled.

Check what you actually enabled with:

```bash
docker compose config --services
```

### Which file does a setting go in?

| | |
|---|---|
| `.env` | Stack-level values Compose interpolates into `docker-compose.yml` (host ports, build targets, `LLAMA_MODELS_DIR`), plus anything shared across add-ons: API keys, auth secrets, public URLs |
| `.env.<option>` | That add-on's runtime configuration, passed straight into its containers |

This is not a style preference, it is forced by how Compose resolves variables:

- Compose expands `${...}` only from the root `.env`, never from a scoped file.
  So a scoped file cannot feed an interpolation — which is why each one uses the
  target image's own variable names (`ASR_MODEL`, `TUNNEL_TOKEN`, `LLAMA_ARG_*`)
  rather than ours.
- An `environment:` entry in `docker-compose.yml` always beats an `env_file`
  value — even when it interpolates to an empty string. So a variable is owned
  by `.env` or by a scoped file, never both, and the compose file deliberately
  no longer mentions the ones that moved.

The one place this bites: `LLM` and `OPENAI_BASE_URL` stay in `.env` even for
the llama add-on. They are core settings every provider uses, they reach the
backend through `environment:`, and that outranks `.env.llama`.

### `vaapi.yml` — GPU video encoding

Maps the host's `/dev/dri` render nodes into `backend` and `worker` so ffmpeg
can encode on an Intel or AMD GPU.

`.env.vaapi` holds both settings: `VIDEO_ENCODER=vaapi` (the include only hands
over the GPU, it does not switch the encoder) and `VAAPI_DEVICE`, which matters
when the host has more than one GPU — `ls -l /dev/dri/by-path` shows which node
is which. A failed hardware encode falls back to libx264 with a warning.

The device mapping is a separate switch from the encoder because a `devices:`
entry fails container creation outright on hosts without `/dev/dri`.

### `whisperx.yml` — local transcription

Runs [whisper-asr-webservice](https://ahmetoner.com/whisper-asr-webservice/)
with `ASR_ENGINE=whisperx`, and the backend posts media to it instead of using
AssemblyAI.

`.env.whisperx` carries the whole switch, which is why forgetting it leaves you
quietly on AssemblyAI rather than half-enabled: `TRANSCRIPTION_PROVIDER` and
`WHISPERX_API_URL` for the backend and worker, `ASR_MODEL` and `HF_TOKEN` for
the service itself. The file is read by all three containers.

- Speaker labels need `HF_TOKEN` — a Hugging Face token that has accepted the
  pyannote model licences. Without one, transcription still works, just without
  "Speaker A/B" attribution.
- The model is downloaded on first use into a named volume and can be several
  GB. Expect the first request to take a long time, and `ASR_MODEL=small` to be
  dramatically faster than the `large-v3` default on a CPU-only host.
- On an NVIDIA host, switch the image to `:latest-gpu` and add `gpus: all`.

Running SupoClip directly on the host rather than in Docker? Install the
backend's optional extra (`cd backend && uv sync --extra whisperx`) and set the
`WHISPERX_*` variables in `.env` with `WHISPERX_API_URL` left empty; WhisperX
then runs in-process. (`config.py` reads plain environment variables — the
scoped files are a Compose mechanism.)

### `llama-*.yml` — local LLM

Starts a [llama.cpp](https://github.com/ggml-org/llama.cpp) server, giving you
an OpenAI-compatible endpoint on the compose network. Uncomment the variant
matching your hardware:

| File | Image | Hardware |
|------|-------|----------|
| `llama-cpu.yml` | `ghcr.io/ggml-org/llama.cpp:server` | CPU only |
| `llama-cuda.yml` | `…:server-cuda` | NVIDIA (needs the NVIDIA Container Toolkit) |
| `llama-rocm.yml` | `…:server-rocm` | AMD (ROCm) |
| `llama-sycl.yml` | `…:server-intel` | Intel Arc / Xe (oneAPI SYCL) |
| `llama-vulkan.yml` | `…:server-vulkan` | Any Vulkan driver |

All five share one `.env.llama`. Supply the model yourself — put a `.gguf` file
in `./models` (or point `LLAMA_MODELS_DIR` elsewhere) — and configure the
server with llama.cpp's own variables in `.env.llama`:

```env
LLAMA_ARG_MODEL=/models/your-model.gguf
LLAMA_ARG_N_GPU_LAYERS=99       # offload onto the GPU; drop this line for CPU
LLAMA_ARG_CTX_SIZE=8192         # transcripts are long, the 4096 default is tight
```

The services pass no command-line arguments at all, deliberately: llama-server
lets a flag override the matching environment variable, so any argument in the
compose file would silently ignore what you put here.

The other half of the pairing goes in `.env`, because Compose feeds it to the
backend through `environment:`, which outranks any env file:

```env
LLM=openai:local
OPENAI_BASE_URL=http://llama:8080/v1
```

The model name after `openai:` is arbitrary — llama.cpp serves whichever model
you loaded. Its own web UI is published on `127.0.0.1:9292` (`LLAMA_PORT`, a
host-level setting and therefore in `.env`) for poking at directly. This is a
convenience scaffold rather than a tuned deployment; expect to adjust the flags
for your model and card.

### `tunnel.yml` — public ingress

Covered in detail under
[Public access with Cloudflare Tunnel](#public-access-with-cloudflare-tunnel-optional).

## Upgrading from the profile-based scheme

Earlier versions shipped a tracked `docker-compose.yml` and toggled options
with Compose profiles. If you are coming from one of those:

1. Delete `COMPOSE_PROFILES` and `VAAPI_ENABLED` from `.env`. Both are gone;
   there is no replacement variable, because toggling now happens in the
   compose file itself.
2. Run `docker compose down --remove-orphans` **once**. This clears the old
   `backend-vaapi` / `worker-vaapi` / `config-guard` containers, which would
   otherwise collide on container names and ports.
3. `cp docker-compose.yml.example docker-compose.yml`.
4. Re-enable what you were using by uncommenting the matching include:
   `VAAPI_ENABLED=true` becomes `docker/options/vaapi.yml`, and the `tunnel`
   profile becomes `docker/options/tunnel.yml`.
5. Move each add-on's settings out of `.env` and into its own file. Copy the
   example first, then carry your values across:

   | Was in `.env` | Now lives in |
   |---|---|
   | `VIDEO_ENCODER`, `VAAPI_DEVICE` | `.env.vaapi` |
   | `TRANSCRIPTION_PROVIDER`, `WHISPERX_*`, `HF_TOKEN` | `.env.whisperx` |
   | `CLOUDFLARE_TUNNEL_TOKEN` | `.env.tunnel`, renamed to `TUNNEL_TOKEN` |

   Left in `.env` these are now ignored — the compose file no longer passes
   them through, so this step is not optional.
6. `docker compose up -d --build`.

The rest of your `.env` is unchanged, and the container names
(`supoclip-backend`, `supoclip-worker`) are the same as before. `./start.sh`
will tell you if an add-on is enabled without its settings file.

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
running your own reverse proxy, `docker/options/tunnel.yml` adds a
`cloudflared` service to the stack. It makes an outbound-only
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

### 2. Add the tunnel settings

The connector token goes in its own file, under cloudflared's own variable name:

```bash
cp .env.tunnel.example .env.tunnel
```

```env
# .env.tunnel
TUNNEL_TOKEN=your_tunnel_token
```

Keeping it there rather than in `.env` means the one file holding your ingress
credential is also the file you delete to stop publishing the app.

The rest stays in `.env`, because the frontend bakes these into its image at
build time and the backend needs the origin allow-listed:

```env
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

### 3. Enable the add-on and start the stack

Uncomment these two lines at the top of your `docker-compose.yml`:

```yaml
include:
  - path: docker/options/tunnel.yml
```

Then:

```bash
./start.sh
```

`./start.sh` cannot do the uncommenting for you — `docker-compose.yml` is your
file, not the repo's — but it does check both halves: an enabled add-on with no
`.env.tunnel`, or a `.env.tunnel` with the include still commented out, each
gets a warning naming the exact fix. It also warns if `NEXT_PUBLIC_APP_URL`,
`NEXT_PUBLIC_API_URL`, or `BETTER_AUTH_URL` are not `https://` URLs, or if
`CORS_ORIGINS` does not include `NEXT_PUBLIC_APP_URL`.

Manual equivalent:

```bash
docker compose up -d --build
```

### 4. Verify

```bash
docker compose ps
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
- Enabling the include with a missing `.env.tunnel`, or an empty or invalid
  `TUNNEL_TOKEN` inside it, leaves `cloudflared` crash-looping, because the
  service restarts `unless-stopped`. Check `docker compose logs cloudflared`.
- To stop exposing the app, comment the include back out and run
  `docker compose up -d --remove-orphans`. A plain `docker compose down` stops
  `cloudflared` along with everything else, but leaves the include in place, so
  the next `up` starts the tunnel again.

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

Service names never change with add-ons enabled — `backend` and `worker` are
the same services with a few extra keys merged in — so these commands always
work.

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
