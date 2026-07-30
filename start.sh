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

# Local WhisperX transcription does not need an AssemblyAI key.
if [ -z "$ASSEMBLY_AI_API_KEY" ] && [ "${TRANSCRIPTION_PROVIDER:-assemblyai}" != "whisperx" ]; then
    echo -e "${YELLOW}Warning: ASSEMBLY_AI_API_KEY is not set in .env${NC}"
    echo "Video transcription will not work without this key"
    echo "(or set TRANSCRIPTION_PROVIDER=whisperx for local transcription)."
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

# docker-compose.yml needs Compose v2.24+ for the top-level `include:` key the
# optional add-ons rely on; older v2 releases and the legacy v1 binary cannot
# parse it. Non-numeric version output is treated as too old. (Validated on
# v5.x, which is what current Docker Desktop ships.)
COMPOSE_VERSION=$($DOCKER_COMPOSE version --short 2>/dev/null || true)
COMPOSE_VERSION=${COMPOSE_VERSION#v}
COMPOSE_MAJOR=$(echo "$COMPOSE_VERSION" | cut -d. -f1)
COMPOSE_MINOR=$(echo "$COMPOSE_VERSION" | cut -d. -f2)
case "$COMPOSE_MAJOR" in ''|*[!0-9]*) COMPOSE_MAJOR=0 ;; esac
case "$COMPOSE_MINOR" in ''|*[!0-9]*) COMPOSE_MINOR=0 ;; esac
if [ "$COMPOSE_MAJOR" -lt 2 ] || { [ "$COMPOSE_MAJOR" -eq 2 ] && [ "$COMPOSE_MINOR" -lt 24 ]; }; then
    echo -e "${RED}Error: Docker Compose v2.24 or newer is required (found ${COMPOSE_VERSION:-unknown})!${NC}"
    echo "Update Docker Desktop or the Docker Compose plugin and try again."
    echo ""
    exit 1
fi

# Cloudflare Tunnel ingress is opt-in by uncommenting the tunnel.yml include in
# docker-compose.yml, which this script must not edit for you — it is your file.
# So when a token is configured, check whether the service is actually part of
# the stack and say so plainly if it is not.
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
    if $DOCKER_COMPOSE config --services 2>/dev/null | grep -qx "cloudflared"; then
        TUNNEL_ENABLED=1
        echo -e "${GREEN}Cloudflare Tunnel enabled (docker/options/tunnel.yml)${NC}"
    else
        TUNNEL_ENABLED=0
        echo -e "${YELLOW}Warning: CLOUDFLARE_TUNNEL_TOKEN is set but the tunnel add-on is not enabled${NC}"
        echo "Uncomment this line at the top of docker-compose.yml to start cloudflared:"
        echo "  - path: docker/options/tunnel.yml"
        echo "(the 'include:' line above it must be uncommented too)"
    fi
    if [[ "${NEXT_PUBLIC_APP_URL:-}" != https://* ]] || [[ "${NEXT_PUBLIC_API_URL:-}" != https://* ]] \
        || [[ "${BETTER_AUTH_URL:-}" != https://* ]]; then
        echo -e "${YELLOW}Warning: CLOUDFLARE_TUNNEL_TOKEN is set but NEXT_PUBLIC_APP_URL / NEXT_PUBLIC_API_URL / BETTER_AUTH_URL are not https:// URLs${NC}"
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
