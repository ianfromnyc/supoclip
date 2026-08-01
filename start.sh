#!/bin/bash

# SupoClip - Quick Start Script
# This script helps you start SupoClip with a single command

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "============================================"
echo "  SupoClip - AI Video Clipping Tool"
echo "============================================"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    echo ""
    echo "Please create a .env file with your API keys:"
    echo "  1. Copy the template: cp .env.example .env"
    echo "  2. Or use the provided .env file"
    echo "  3. Edit .env and add your API keys:"
    echo "     - ASSEMBLY_AI_API_KEY (required unless TRANSCRIPTION_PROVIDER=whisperx)"
    echo "     - OPENAI_API_KEY or GOOGLE_API_KEY or ANTHROPIC_API_KEY"
    echo "     - OR set LLM=openai:<model> with OPENAI_BASE_URL for a local"
    echo "       OpenAI-compatible endpoint (llama.cpp, vLLM, Ollama, ...)"
    echo ""
    exit 1
fi

# docker-compose.yml is not tracked in git: it is your own copy of the example,
# so the optional add-on includes you uncomment survive every `git pull`. Make
# the copy on first run rather than making people read about it first.
if [ ! -f docker-compose.yml ]; then
    if [ ! -f docker-compose.yml.example ]; then
        echo -e "${RED}Error: neither docker-compose.yml nor docker-compose.yml.example found!${NC}"
        echo "Run this script from the SupoClip checkout."
        echo ""
        exit 1
    fi
    cp docker-compose.yml.example docker-compose.yml
    echo -e "${GREEN}Created docker-compose.yml from docker-compose.yml.example${NC}"
    echo "Enable optional add-ons (GPU encoding, local transcription, local LLM,"
    echo "Cloudflare Tunnel) by uncommenting their include lines at the top of it."
    echo ""
fi

# Check if required API keys are set
source .env

# Replace any auth secret that is still empty or set to one of the placeholders
# published in our own docs (.env.example, README) with a strong random value, so
# a fresh checkout is never deployed with well-known secrets. Secrets you have
# already customised are left alone on purpose: rotating
# APP_SETTINGS_ENCRYPTION_KEY, for example, would make previously encrypted admin
# settings impossible to decrypt.

# The placeholders we publish, one entry per secret: "VAR_NAME placeholder...".
# Single-sourced so the generation pass below and the "cannot generate anything"
# safety check cannot drift apart.
PLACEHOLDER_SECRETS=(
    "BACKEND_AUTH_SECRET change_me_backend_auth_secret replace_this_if_using_hosted_mode replace_me"
    "BETTER_AUTH_SECRET supoclip_dev_secret_change_in_production change_this_in_production replace_this_for_real_use replace_me"
    "APP_SETTINGS_ENCRYPTION_KEY change_me_settings_encryption_secret"
)

# Print 32 random bytes as 64 lowercase hex characters. openssl is preferred, but
# plenty of minimal hosts do not ship it, so fall back to reading /dev/urandom
# through od (both are POSIX tools). Returns non-zero only when neither source
# works, which callers must treat as "no secret can be generated at all".
# SUPOCLIP_URANDOM_SOURCE exists so that fail-safe path can be exercised in tests.
# True when $1 is exactly 64 lowercase hex characters — the only output
# generate_random_hex is allowed to report success with.
is_64_hex() {
    case "$1" in
        *[!0-9a-f]*) return 1 ;;
    esac
    [ "${#1}" -eq 64 ]
}

generate_random_hex() {
    local urandom="${SUPOCLIP_URANDOM_SOURCE:-/dev/urandom}"
    local hex=""

    if command -v openssl > /dev/null 2>&1; then
        hex="$(openssl rand -hex 32)" || hex=""
    fi

    # Fall back to /dev/urandom when openssl is missing or produced unusable
    # output (e.g. a broken provider or entropy configuration).
    if ! is_64_hex "$hex" && [ -r "$urandom" ] && command -v od > /dev/null 2>&1; then
        hex="$(head -c 32 "$urandom" | od -An -tx1 | tr -d ' \n')" || hex=""
    fi

    # Never report success with a short or malformed result: a truncated random
    # source or a masked pipeline failure must not become a weak secret.
    is_64_hex "$hex" || return 1
    printf '%s' "$hex"
}

# True when $1's current value is empty or still one of its documented
# placeholders, i.e. when it must not be trusted as a real secret.
# Usage: secret_needs_generating VAR_NAME placeholder [placeholder...]
secret_needs_generating() {
    local var="$1" current placeholder
    shift
    current="${!var:-}"

    if [ -z "$current" ]; then
        return 0
    fi

    # Any value that matches none of the documented placeholders is a real secret.
    for placeholder in "$@"; do
        if [ "$current" = "$placeholder" ]; then
            return 0
        fi
    done

    return 1
}

# Usage: generate_secret_if_placeholder VAR_NAME placeholder [placeholder...]
generate_secret_if_placeholder() {
    local var="$1" current new
    current="${!var:-}"

    if ! secret_needs_generating "$@"; then
        return 0
    fi

    new="$(generate_random_hex)"

    # Update the existing assignment in place, or add one if the var is absent.
    # Commented-out lines do not count as an assignment, hence the "^VAR=" anchor.
    # `sed -i` needs a backup suffix to be portable (BSD/macOS sed requires one),
    # so write .env.bak and delete it immediately.
    if grep -q "^${var}=" .env; then
        sed -i.bak "s|^${var}=.*|${var}=${new}|" .env && rm -f .env.bak
    else
        printf '%s=%s\n' "$var" "$new" >> .env
    fi

    # Re-export so the rest of this script sees the new value.
    export "${var}=${new}"
    echo -e "${GREEN}Generated ${var} (stored in .env)${NC}"

    # Replacing the placeholder encryption key (rather than filling in an empty
    # one) orphans any admin settings that were encrypted under it. The backend
    # skips rows it cannot decrypt and falls back to .env, so this is recoverable
    # — but only if the operator knows to re-enter them.
    if [ "$var" = "APP_SETTINGS_ENCRYPTION_KEY" ] && [ -n "$current" ]; then
        echo -e "${YELLOW}Note: admin settings previously saved under the old placeholder encryption key${NC}"
        echo "can no longer be decrypted and will fall back to .env values - re-enter them in the"
        echo "admin settings UI if needed."
    fi
}

# Probe the generator once up front: if this host can produce randomness we fix
# up every placeholder, otherwise we must not quietly start on known secrets.
if generate_random_hex > /dev/null 2>&1; then
    for secret_spec in "${PLACEHOLDER_SECRETS[@]}"; do
        # Split "VAR placeholder..." into arguments without relying on globbing.
        read -ra secret_args <<< "$secret_spec"
        generate_secret_if_placeholder "${secret_args[@]}"
    done
else
    # No randomness source at all (no openssl, no readable /dev/urandom). Any
    # secret still holding a documented placeholder is public knowledge, and we
    # have no way to replace it, so refuse to start rather than warn and proceed.
    unsafe_secrets=()
    for secret_spec in "${PLACEHOLDER_SECRETS[@]}"; do
        read -ra secret_args <<< "$secret_spec"
        if secret_needs_generating "${secret_args[@]}"; then
            unsafe_secrets+=("${secret_args[0]}")
        fi
    done

    if [ "${#unsafe_secrets[@]}" -gt 0 ]; then
        echo -e "${RED}Error: refusing to start with placeholder auth secrets${NC}"
        echo ""
        echo "Unset or still placeholder: ${unsafe_secrets[*]}"
        echo ""
        echo "These values are published in .env.example and the README, so anyone could"
        echo "forge sessions and decrypt your admin settings. Neither openssl nor"
        echo "/dev/urandom is available here, so this script cannot replace them for you."
        echo ""
        echo "Set each of them in .env to its own long random value - for example run"
        echo "'openssl rand -hex 32' once per secret on another machine - then re-run this"
        echo "script."
        echo ""
        exit 1
    fi

    echo -e "${YELLOW}Note: no openssl or /dev/urandom available, so auth secrets cannot be${NC}"
    echo "generated - continuing with the customised values already in .env."
    echo ""
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running!${NC}"
    echo "Please start Docker Desktop and try again."
    echo ""
    exit 1
fi

# Determine which Docker Compose command to use.
if docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
else
    echo -e "${RED}Error: Docker Compose is not installed!${NC}"
    echo "Please install the Docker Compose plugin and try again."
    echo ""
    exit 1
fi

# The add-ons need Compose v5.0.0+. `include:` itself landed in v2.24, but every
# overlay in docker/options/ merges into a service the root file also defines —
# vaapi.yml adds devices: to backend and worker, the rest add a worker
# depends_on entry — and partial-service includes only work from v5.0.0. On
# v2.x, up to and including the final v2.40.3, the same file fails with
# "services.backend conflicts with imported resource" rather than merging.
#
# Only the major version matters because the floor is x.0.0. Non-numeric output
# is treated as too old, which also catches the legacy v1 `docker-compose`.
COMPOSE_VERSION=$($DOCKER_COMPOSE version --short 2>/dev/null || true)
COMPOSE_VERSION=${COMPOSE_VERSION#v}
COMPOSE_MAJOR=$(echo "$COMPOSE_VERSION" | cut -d. -f1)
case "$COMPOSE_MAJOR" in ''|*[!0-9]*) COMPOSE_MAJOR=0 ;; esac
if [ "$COMPOSE_MAJOR" -lt 5 ]; then
    echo -e "${RED}Error: Docker Compose v5.0.0 or newer is required (found ${COMPOSE_VERSION:-unknown})!${NC}"
    echo "Older releases cannot merge the optional add-ons in docker/options/ into the"
    echo "base stack: they report 'conflicts with imported resource' and refuse to start."
    echo "Update Docker Desktop or the Docker Compose plugin and try again."
    echo ""
    exit 1
fi

# Every add-on has two halves that must agree: an uncommented include in
# docker-compose.yml, and a .env.<option> copied from its .example. Enabling one
# without the other fails quietly — a service with no configuration, or
# configuration nothing reads — so check both directions here. This script never
# edits docker-compose.yml or creates the scoped files: they are yours, and
# guessing at them is how you end up with a stack nobody can reason about.

COMPOSE_SERVICES="$($DOCKER_COMPOSE config --services 2>/dev/null || true)"

# True when $1's add-on is part of the stack. Tested two ways because they fail
# differently: the include line is what the docs tell you to edit (and is the
# only signal for vaapi, which adds no service), while the service list is what
# Compose actually resolved.
option_is_enabled() {
    local option="$1"

    # An uncommented `- path: docker/options/<option>*.yml` line. The llama
    # variants share one prefix, hence the trailing glob.
    if grep -qE "^[[:space:]]*-[[:space:]]*path:[[:space:]]*docker/options/${option}[a-z-]*\.yml" \
        docker-compose.yml 2>/dev/null; then
        return 0
    fi

    case "$option" in
        whisperx) printf '%s\n' "$COMPOSE_SERVICES" | grep -qx "whisperx" ;;
        tunnel)   printf '%s\n' "$COMPOSE_SERVICES" | grep -qx "cloudflared" ;;
        llama)    printf '%s\n' "$COMPOSE_SERVICES" | grep -qx "llama" ;;
        *)        return 1 ;;
    esac
}

# The five llama variants all define the same `llama` service, so uncommenting
# two does not run two models: Compose merges them into one service with a
# mixture of images and device mappings, and the last include quietly wins. That
# is unfixable from inside the compose files, so refuse to start instead of
# reporting a cheerful "Add-on enabled" for a stack nobody can reason about.
ACTIVE_LLAMA_INCLUDES=$(grep -cE \
    "^[[:space:]]*-[[:space:]]*path:[[:space:]]*docker/options/llama-[a-z]+\.yml" \
    docker-compose.yml 2>/dev/null || true)
if [ "${ACTIVE_LLAMA_INCLUDES:-0}" -gt 1 ]; then
    echo -e "${RED}Error: ${ACTIVE_LLAMA_INCLUDES} llama add-ons are enabled at once${NC}"
    echo "All five define the same 'llama' service, so enabling more than one merges"
    echo "incompatible images and device mappings into a single container."
    echo ""
    echo "Currently uncommented in docker-compose.yml:"
    grep -E "^[[:space:]]*-[[:space:]]*path:[[:space:]]*docker/options/llama-[a-z]+\.yml" \
        docker-compose.yml | grep -oE "llama-[a-z]+\.yml" | sed 's/^/  - /'
    echo ""
    echo "Comment out all but the one matching your hardware, then run this again."
    echo ""
    exit 1
fi

TUNNEL_ENABLED=0
# Whether transcription actually runs on WhisperX, which takes both halves of
# the add-on: the include supplies the service and the env_file wiring, and
# .env.whisperx supplies TRANSCRIPTION_PROVIDER. Neither a stray .env.whisperx
# nor a legacy TRANSCRIPTION_PROVIDER in the root .env reaches the containers,
# so neither may excuse a missing AssemblyAI key below.
WHISPERX_ACTIVE=0
for option in vaapi whisperx tunnel llama; do
    scoped_env=".env.${option}"
    if option_is_enabled "$option"; then
        [ "$option" = "tunnel" ] && TUNNEL_ENABLED=1
        if [ -f "$scoped_env" ]; then
            [ "$option" = "whisperx" ] && WHISPERX_ACTIVE=1
            echo -e "${GREEN}Add-on enabled: ${option} (${scoped_env})${NC}"
        else
            echo -e "${YELLOW}Warning: the ${option} add-on is enabled but ${scoped_env} is missing${NC}"
            echo "It holds that add-on's entire configuration, so without it the service starts"
            echo "unconfigured. Create it with:"
            echo "  cp ${scoped_env}.example ${scoped_env}"
            echo ""
        fi
    elif [ -f "$scoped_env" ]; then
        echo -e "${YELLOW}Warning: ${scoped_env} exists but the ${option} add-on is not enabled${NC}"
        echo "Uncomment its include line at the top of docker-compose.yml (along with the"
        echo "'include:' line above it), or delete ${scoped_env} if you no longer want it:"
        if [ "$option" = "llama" ]; then
            # There is no llama.yml: five hardware variants share one .env.llama.
            echo "  - path: docker/options/llama-<variant>.yml"
            echo "Uncomment exactly ONE variant for your hardware: llama-cpu.yml, llama-cuda.yml,"
            echo "llama-rocm.yml, llama-sycl.yml or llama-vulkan.yml (all five define the same"
            echo "llama service; see docs/setup.md)."
        else
            echo "  - path: docker/options/${option}.yml"
        fi
        echo ""
    fi
done

# ── Configuration warnings ────────────────────────────────────────
# These run after add-on detection because some of them depend on it: whether a
# key is required is a question about the stack that is actually configured, not
# about what happens to be sitting in a file.

if [ -n "${LLM:-}" ]; then
    case "$LLM" in
        google:*|google-gla:*|openai:*|anthropic:*|ollama:*)
            ;;
        *)
            echo -e "${YELLOW}Warning: Unsupported LLM value '$LLM'${NC}"
            echo "Use google-gla:*, openai:*, or anthropic:* (ollama:* is deprecated)"
            echo ""
            ;;
    esac
fi

# Only a running WhisperX add-on removes the need for an AssemblyAI key, and
# that takes the include and .env.whisperx together (WHISPERX_ACTIVE above).
# Deciding this from a sourced TRANSCRIPTION_PROVIDER instead would clear the
# warning for two configurations that transcribe on AssemblyAI regardless: a
# leftover .env.whisperx with the include commented out, and a legacy
# TRANSCRIPTION_PROVIDER=whisperx in the root .env, which the compose template
# stopped passing through when the add-on settings were scoped.
if [ -z "$ASSEMBLY_AI_API_KEY" ] && [ "$WHISPERX_ACTIVE" -eq 0 ]; then
    echo -e "${YELLOW}Warning: ASSEMBLY_AI_API_KEY is not set in .env${NC}"
    echo "Video transcription will not work without this key. To transcribe locally"
    echo "instead, enable the whisperx add-on: uncomment docker/options/whisperx.yml"
    echo "in docker-compose.yml and run 'cp .env.whisperx.example .env.whisperx'."
    echo ""
fi

if [ "${LLM:-}" = "ollama:" ] || [ "${LLM:-}" = "openai:" ]; then
    echo -e "${YELLOW}Warning: LLM=${LLM} is missing a model name${NC}"
    echo "Use a value like LLM=openai:gpt-oss:20b"
    echo ""
elif [[ "${LLM:-}" == ollama:* ]]; then
    echo -e "${YELLOW}Note: LLM=ollama:* is deprecated${NC}"
    echo "It runs through the same OpenAI-compatible client, reading"
    echo "OLLAMA_BASE_URL and OLLAMA_API_KEY. Prefer LLM=openai:<model> with"
    echo "OPENAI_BASE_URL for new installs."
    echo ""
fi

# A self-hosted endpoint usually needs no API key at all, so a missing key is
# only worth warning about when the selected LLM actually talks to a hosted
# provider. Every .env ships an OPENAI_BASE_URL, so its presence proves nothing —
# what matters is whether it still points at OpenAI's own API.
if [ -z "$OPENAI_API_KEY" ] && [ -z "$GOOGLE_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    if [[ "${LLM:-}" == openai:* && -n "${OPENAI_BASE_URL:-}" && "${OPENAI_BASE_URL:-}" != *api.openai.com* ]] || [[ "${LLM:-}" == ollama:* ]]; then
        :
    else
    echo -e "${YELLOW}Warning: No AI provider API key is set in .env${NC}"
    echo "You need at least one of: OPENAI_API_KEY, GOOGLE_API_KEY, ANTHROPIC_API_KEY,"
    echo "or LLM=openai:<model> with OPENAI_BASE_URL pointing at your own endpoint"
    echo ""
    fi
fi

if [ "$TUNNEL_ENABLED" -eq 1 ]; then
    if [[ "${NEXT_PUBLIC_APP_URL:-}" != https://* ]] || [[ "${NEXT_PUBLIC_API_URL:-}" != https://* ]] \
        || [[ "${BETTER_AUTH_URL:-}" != https://* ]]; then
        echo -e "${YELLOW}Warning: the tunnel add-on is enabled but NEXT_PUBLIC_APP_URL / NEXT_PUBLIC_API_URL / BETTER_AUTH_URL are not https:// URLs${NC}"
        echo "Public sign-in and uploads will fail until NEXT_PUBLIC_APP_URL, NEXT_PUBLIC_API_URL,"
        echo "BETTER_AUTH_URL and CORS_ORIGINS point at your tunnel hostnames (see .env.example)."
    fi
    # A CORS_ORIGINS list that omits the public app origin blocks every browser
    # request the tunnel forwards, which looks like a broken backend. Compare each
    # comma-separated entry exactly: a substring test would happily accept a
    # look-alike origin such as https://app.example.com.evil.
    if [ -n "${NEXT_PUBLIC_APP_URL:-}" ]; then
        if [ -z "${CORS_ORIGINS:-}" ]; then
            echo -e "${YELLOW}Warning: CORS_ORIGINS is not set${NC}"
            echo "The compose defaults only allow localhost origins, so set CORS_ORIGINS to include"
            echo "$NEXT_PUBLIC_APP_URL or browser requests through the tunnel will be rejected."
        else
            cors_match=0
            # Split on commas, then strip surrounding whitespace from each entry.
            IFS=',' read -ra cors_entries <<< "$CORS_ORIGINS"
            for cors_entry in "${cors_entries[@]}"; do
                cors_entry="${cors_entry#"${cors_entry%%[![:space:]]*}"}"
                cors_entry="${cors_entry%"${cors_entry##*[![:space:]]}"}"
                if [ "$cors_entry" = "$NEXT_PUBLIC_APP_URL" ]; then
                    cors_match=1
                    break
                fi
            done
            if [ "$cors_match" -eq 0 ]; then
                echo -e "${YELLOW}Warning: CORS_ORIGINS does not include NEXT_PUBLIC_APP_URL${NC}"
                echo "Add your public app origin to CORS_ORIGINS or browser requests will be rejected."
            fi
        fi
    fi
    echo ""
fi

echo -e "${GREEN}Starting SupoClip...${NC}"
echo ""

# Build and start containers
echo "Building and starting Docker containers..."
echo "(This may take a few minutes on the first run)"
echo ""

$DOCKER_COMPOSE up -d --build

echo ""
echo -e "${GREEN}SupoClip is starting up!${NC}"
echo ""
echo "Services will be available at:"
echo "  - Frontend:  http://localhost:3001"
echo "  - Backend:   http://localhost:8000"
echo "  - API Docs:  http://localhost:8000/docs"
if [ "${TUNNEL_ENABLED:-0}" -eq 1 ]; then
    echo "  - Public:    ${NEXT_PUBLIC_APP_URL:-<set NEXT_PUBLIC_APP_URL>} (via Cloudflare Tunnel)"
fi
echo ""
echo "To view logs, run:"
echo "  $DOCKER_COMPOSE logs -f"
echo ""
echo "To stop all services, run:"
echo "  $DOCKER_COMPOSE down"
echo ""
echo "Waiting for services to be healthy..."

# Wait for services to be healthy
sleep 5

# Check if services are running
if $DOCKER_COMPOSE ps | grep -q "Up"; then
    echo -e "${GREEN}Services are starting successfully!${NC}"
    echo ""
    echo "You can now:"
    echo "  1. Open http://localhost:3001 in your browser"
    echo "  2. View logs: $DOCKER_COMPOSE logs -f"
    echo "  3. Stop services: $DOCKER_COMPOSE down"
else
    echo -e "${YELLOW}Services are starting... Check logs if you encounter issues:${NC}"
    echo "  $DOCKER_COMPOSE logs -f"
fi

echo ""
echo "============================================"
