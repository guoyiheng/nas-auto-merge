FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini \
    && rm -rf /var/lib/apt/lists/*

COPY src/merge_watcher.py /app/merge_watcher.py

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-u", "/app/merge_watcher.py"]
