#!/bin/sh
# Docker entrypoint for clutch — maps environment variables to CLI flags.
set -e

# Apply timezone from TZ env var (creates /etc/localtime symlink)
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
    ln -sf "/usr/share/zoneinfo/$TZ" /etc/localtime
    echo "$TZ" > /etc/timezone 2>/dev/null || true
fi

TARGET_UID="${CLUTCH_UID:-1000}"
TARGET_GID="${CLUTCH_GID:-1000}"

run_as_target_user() {
    if [ "$(id -u)" -ne 0 ]; then
        exec "$@"
    fi

    GROUP_NAME="clutch"
    USER_NAME="clutch"

    EXISTING_GROUP="$(getent group "$TARGET_GID" | cut -d: -f1 || true)"
    if [ -n "$EXISTING_GROUP" ]; then
        GROUP_NAME="$EXISTING_GROUP"
    elif ! getent group "$GROUP_NAME" >/dev/null 2>&1; then
        if command -v addgroup >/dev/null 2>&1; then
            addgroup --gid "$TARGET_GID" "$GROUP_NAME" >/dev/null 2>&1 || true
        else
            groupadd -g "$TARGET_GID" "$GROUP_NAME" >/dev/null 2>&1 || true
        fi
    fi

    EXISTING_USER="$(getent passwd "$TARGET_UID" | cut -d: -f1 || true)"
    if [ -n "$EXISTING_USER" ]; then
        USER_NAME="$EXISTING_USER"
    elif ! getent passwd "$USER_NAME" >/dev/null 2>&1; then
        if command -v adduser >/dev/null 2>&1; then
            adduser --disabled-password --gecos "" --uid "$TARGET_UID" --gid "$TARGET_GID" "$USER_NAME" >/dev/null 2>&1 || true
        else
            useradd -u "$TARGET_UID" -g "$TARGET_GID" -M -s /usr/sbin/nologin "$USER_NAME" >/dev/null 2>&1 || true
        fi
    fi

    mkdir -p /config
    chown -R "$TARGET_UID:$TARGET_GID" /config 2>/dev/null || true

    if command -v gosu >/dev/null 2>&1; then
        exec gosu "$TARGET_UID:$TARGET_GID" "$@"
    fi
    if command -v su-exec >/dev/null 2>&1; then
        exec su-exec "$TARGET_UID:$TARGET_GID" "$@"
    fi
    exec "$@"
}

ARGS="--serve --listen-host 0.0.0.0 --listen-port ${CLUTCH_PORT:-8765}"
SERVICE_DB_PATH="${CLUTCH_SERVICE_DB:-/config/service.db}"
ARGS="$ARGS --service-db $SERVICE_DB_PATH"

# Media roots
if [ -n "$CLUTCH_ALLOW_ROOTS" ]; then
    for root in $(echo "$CLUTCH_ALLOW_ROOTS" | tr ',' ' '); do
        ARGS="$ARGS --allow-root $root"
    done
else
    ARGS="$ARGS --allow-root /media"
fi

# Workers
if [ -n "$CLUTCH_WORKERS" ]; then
    ARGS="$ARGS --workers $CLUTCH_WORKERS"
fi

# GPU devices
if [ -n "$CLUTCH_GPUS" ]; then
    ARGS="$ARGS --gpus $CLUTCH_GPUS"
fi

# Watch directories
if [ -n "$CLUTCH_WATCH_DIRS" ]; then
    for dir in $(echo "$CLUTCH_WATCH_DIRS" | tr ',' ' '); do
        ARGS="$ARGS --watch-dir $dir"
    done
fi

if [ "${CLUTCH_WATCH_RECURSIVE:-false}" = "true" ]; then
    ARGS="$ARGS --watch-recursive"
fi

# Schedule
if [ -n "$CLUTCH_SCHEDULE" ]; then
    ARGS="$ARGS --schedule $CLUTCH_SCHEDULE"
fi

if [ -n "$CLUTCH_SCHEDULE_MODE" ]; then
    ARGS="$ARGS --schedule-mode $CLUTCH_SCHEDULE_MODE"
fi

# Price-based scheduling
if [ -n "$CLUTCH_PRICE_PROVIDER" ]; then
    ARGS="$ARGS --price-provider $CLUTCH_PRICE_PROVIDER"
fi

if [ -n "$CLUTCH_PRICE_COUNTRY" ]; then
    ARGS="$ARGS --price-country $CLUTCH_PRICE_COUNTRY"
fi

if [ -n "$CLUTCH_PRICE_LIMIT" ]; then
    ARGS="$ARGS --price-limit $CLUTCH_PRICE_LIMIT"
fi

# Debug mode
if [ "${CLUTCH_DEBUG:-false}" = "true" ]; then
    ARGS="$ARGS --debug"
fi

# If arguments were passed directly (e.g. docker run ... clutch --serve ...),
# use them as-is instead of the generated ones.
if [ $# -gt 0 ]; then
    run_as_target_user clutch "$@"
fi

# shellcheck disable=SC2086
run_as_target_user clutch $ARGS
