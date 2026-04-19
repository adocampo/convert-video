#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# qbt-hardlink-to-watch.sh — qBittorrent post-download script
#
# Creates hardlinks of downloaded video files into watch directories
# so clutch can pick them up for conversion.
#
# qBittorrent "Run on torrent finished" command:
#   /path/to/qbt-hardlink-to-watch.sh "%N" "%L" "%F"
#
#   %N = Torrent name
#   %L = Category
#   %F = Content path (root path for multi-file torrents)
#
# Classification rules:
#   Series  → category is "sonarr", or torrent name contains PACK, "serie"
#            or S01..SNN pattern
#   Movies  → everything else, or category is "radarr"
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────
MOVIES_WATCH="/data/Downloads/Movies"
SERIES_WATCH="/data/Downloads/Series"
VIDEO_EXTS="mp4|mkv|avi|mov|ts|iso|mpg|mpeg"
LOG_FILE="/config/qbt-hardlink-to-watch.log"   # set to a path to enable logging
# ──────────────────────────────────────────────────────────────────────

TORRENT_NAME="${1:-}"
CATEGORY="${2:-}"
CONTENT_PATH="${3:-}"

log() {
    [[ -n "$LOG_FILE" ]] && echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG_FILE" || true
}

classify() {
    local name_upper="${TORRENT_NAME^^}"
    local cat_lower="${CATEGORY,,}"

    # Explicit category override
    if [[ "$cat_lower" == "radarr" ]]; then
        echo "movie"
        return
    fi
    if [[ "$cat_lower" == "sonarr" ]]; then
        echo "series"
        return
    fi

    # PACK, serie (case-insensitive), S01..S99, or Cap.NNN pattern → series
    if [[ "$name_upper" =~ PACK ]] \
    || [[ "$name_upper" =~ SERIE ]] \
    || [[ "$name_upper" =~ S[0-9]{2,} ]] \
    || [[ "$name_upper" =~ CAP\.[0-9]+ ]]; then
        echo "series"
        return
    fi

    echo "movie"
}

link_file() {
    local src="$1"
    local dest_dir="$2"
    local filename
    filename="$(basename "$src")"

    # Skip non-video files
    local ext="${filename##*.}"
    ext="${ext,,}"
    if ! [[ "$ext" =~ ^($VIDEO_EXTS)$ ]]; then
        return
    fi

    local dest="$dest_dir/$filename"

    if [[ -e "$dest" ]]; then
        log "SKIP  $filename (already exists in $dest_dir)"
        return
    fi

    ln "$src" "$dest"
    log "LINK  $src -> $dest"
}

# ── Main ──────────────────────────────────────────────────────────────
TYPE="$(classify)"

if [[ "$TYPE" == "series" ]]; then
    DEST="$SERIES_WATCH"
else
    DEST="$MOVIES_WATCH"
fi

mkdir -p "$DEST"
log "START torrent='$TORRENT_NAME' category='$CATEGORY' type=$TYPE dest='$DEST' content='$CONTENT_PATH'"

if [[ -f "$CONTENT_PATH" ]]; then
    link_file "$CONTENT_PATH" "$DEST"
elif [[ -d "$CONTENT_PATH" ]]; then
    # Recreate the torrent folder inside the watch directory
    FOLDER_NAME="$(basename "$CONTENT_PATH")"
    DEST="$DEST/$FOLDER_NAME"
    mkdir -p "$DEST"
    find "$CONTENT_PATH" -type f | while IFS= read -r file; do
        link_file "$file" "$DEST"
    done
else
    log "ERROR content path does not exist: $CONTENT_PATH"
    exit 1
fi

log "DONE  torrent='$TORRENT_NAME' type=$TYPE"
