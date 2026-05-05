#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
#  docker-release.sh — Build and push Clutch Docker images to ghcr.io
#
#  Usage:
#    ./docker-release.sh              # uses version from pyproject.toml
#    ./docker-release.sh 2.1.3        # override version tag
#
#  Requires:
#    • .ghcr-token file in the repo root (gitignored) with your PAT
#    • Docker with buildx support
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKEN_FILE="$SCRIPT_DIR/.ghcr-token"
REGISTRY="ghcr.io"
NAMESPACE="adocampo"

# ── Read token ───────────────────────────────────────────────────────
if [[ ! -f "$TOKEN_FILE" ]]; then
    echo "ERROR: Token file not found: $TOKEN_FILE" >&2
    echo "       Create it with your GitHub PAT (scope: write:packages)" >&2
    exit 1
fi
TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"

# ── Determine version ────────────────────────────────────────────────
if [[ -n "${1:-}" ]]; then
    VERSION="$1"
else
    VERSION="$(grep -Po '(?<=^version = ")[^"]+' "$SCRIPT_DIR/pyproject.toml")"
    if [[ -z "$VERSION" ]]; then
        echo "ERROR: Could not read version from pyproject.toml" >&2
        exit 1
    fi
fi

echo "╭──────────────────────────────────────────────╮"
echo "│  Clutch Docker Release — v${VERSION}"
echo "╰──────────────────────────────────────────────╯"
echo ""

# ── Login ────────────────────────────────────────────────────────────
echo "→ Logging in to $REGISTRY..."
echo "$TOKEN" | docker login "$REGISTRY" -u "$NAMESPACE" --password-stdin

# ── Build & push: clutch (full image) ────────────────────────────────
FULL_IMAGE="$REGISTRY/$NAMESPACE/clutch"
echo ""
echo "→ Building $FULL_IMAGE..."
docker build -f "$SCRIPT_DIR/Dockerfile" \
    -t "$FULL_IMAGE:latest" \
    -t "$FULL_IMAGE:$VERSION" \
    "$SCRIPT_DIR"

echo "→ Pushing $FULL_IMAGE:$VERSION..."
docker push "$FULL_IMAGE:$VERSION"
echo "→ Pushing $FULL_IMAGE:latest..."
docker push "$FULL_IMAGE:latest"

# ── Build & push: clutch-minimal ─────────────────────────────────────
MINIMAL_IMAGE="$REGISTRY/$NAMESPACE/clutch-minimal"
echo ""
echo "→ Building $MINIMAL_IMAGE..."
docker build -f "$SCRIPT_DIR/Dockerfile.minimal" \
    -t "$MINIMAL_IMAGE:latest" \
    -t "$MINIMAL_IMAGE:$VERSION" \
    "$SCRIPT_DIR"

echo "→ Pushing $MINIMAL_IMAGE:$VERSION..."
docker push "$MINIMAL_IMAGE:$VERSION"
echo "→ Pushing $MINIMAL_IMAGE:latest..."
docker push "$MINIMAL_IMAGE:latest"

# ── Done ─────────────────────────────────────────────────────────────
echo ""
echo "✔ Released:"
echo "    $FULL_IMAGE:$VERSION"
echo "    $FULL_IMAGE:latest"
echo "    $MINIMAL_IMAGE:$VERSION"
echo "    $MINIMAL_IMAGE:latest"
