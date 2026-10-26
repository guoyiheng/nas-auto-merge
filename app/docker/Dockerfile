# syntax=docker/dockerfile:1

# 静态编译的 ffmpeg / ffprobe 直接从 Docker Hub 取，避免从 GitHub Release
# 下载（国内经常很慢）。多阶段构建，最终镜像只保留两个二进制文件。
# 需要换版本时用 build-arg 覆盖：
#   FFMPEG_IMAGE=mwader/static-ffmpeg:<tag> ./update.sh --build
ARG FFMPEG_IMAGE=mwader/static-ffmpeg:9.0.2-1
FROM ${FFMPEG_IMAGE} AS ffmpeg

FROM python:3.11-slim-bookworm

COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/

COPY src/merge_watcher.py /app/merge_watcher.py

# PID 1 的僵尸回收由 docker-compose 的 init: true 提供（替代原来的 tini）
CMD ["python", "-u", "/app/merge_watcher.py"]
