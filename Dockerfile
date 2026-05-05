FROM archlinux:base

LABEL org.opencontainers.image.title="clutch" \
    org.opencontainers.image.description="Video transcoding service with NVENC/NVDEC hardware acceleration" \
    org.opencontainers.image.source="https://github.com/adocampo/clutch" \
    org.opencontainers.image.url="https://github.com/adocampo/clutch" \
    org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_STATE_HOME=/config \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=video,compute,utility \
    CLUTCH_DOCKER_VARIANT=full

# Install runtime dependencies and clutch.
RUN pacman -Sy --noconfirm \
    && pacman -S --noconfirm --needed \
    python \
    python-pip \
    handbrake-cli \
    mediainfo \
    mkvtoolnix-cli \
    shadow \
    ca-certificates \
    && pacman -Scc --noconfirm

WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip3 install --no-cache-dir --break-system-packages .

# Copy entrypoint
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create default directories
RUN mkdir -p /config /media

EXPOSE 8765

VOLUME ["/config", "/media"]

ENTRYPOINT ["docker-entrypoint.sh"]
