FROM python:3.11-slim-bookworm

# Debian mirror used for the build. Defaults to a mirror reachable from
# mainland China / Synology NAS where deb.debian.org:80 often times out.
# Override with: APT_MIRROR=mirrors.tuna.tsinghua.edu.cn docker compose build
ARG APT_MIRROR=mirrors.aliyun.com

RUN set -eux; \
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
        if [ -f "$f" ]; then \
            sed -i \
                -e "s|deb.debian.org|${APT_MIRROR}|g" \
                -e "s|security.debian.org|${APT_MIRROR}|g" \
                "$f"; \
        fi; \
    done; \
    apt-get update; \
    apt-get install -y --no-install-recommends ffmpeg tini; \
    rm -rf /var/lib/apt/lists/*

COPY src/merge_watcher.py /app/merge_watcher.py

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-u", "/app/merge_watcher.py"]
