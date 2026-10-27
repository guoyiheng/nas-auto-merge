# syntax=docker/dockerfile:1

# 两个镜像地址都可用 build-arg 覆盖。registry-mirrors 只对 docker.io 生效，
# 所以当加速源不可用时，直接写完整的主机名前缀即可绕过它，例如：
#   PYTHON_IMAGE=docker.1ms.run/library/python:3.11-slim-bookworm \
#   FFMPEG_IMAGE=docker.1ms.run/mwader/static-ffmpeg:9.0.2-1 \
#   ./update.sh --build
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
ARG FFMPEG_IMAGE=mwader/static-ffmpeg:9.0.2-1

# 静态编译的 ffmpeg / ffprobe，多阶段构建，最终镜像只保留两个二进制文件。
FROM ${FFMPEG_IMAGE} AS ffmpeg

FROM ${PYTHON_IMAGE}

COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/

COPY src/merge_watcher.py /app/merge_watcher.py

# PID 1 的僵尸回收由 docker-compose 的 init: true 提供（替代原来的 tini）
CMD ["python", "-u", "/app/merge_watcher.py"]
