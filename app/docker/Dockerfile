# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

# 使用静态编译的 ffmpeg / ffprobe，避免 apt 安装 ffmpeg 拖入的 160+ 个依赖包
# （在群晖上该步骤曾耗时十几分钟）。
#
# 架构对应：
#   x86_64（DS720+ 等 Intel 机型） -> ffmpeg-master-latest-linux64-gpl.tar.xz
#   ARM64（部分 2020+ 机型）        -> ffmpeg-master-latest-linuxarm64-gpl.tar.xz
#
# GitHub 下载慢时可用 build-arg 覆盖为镜像/代理地址：
#   docker compose build --build-arg FFMPEG_URL=https://<mirror>/...
ARG FFMPEG_URL=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
ADD ${FFMPEG_URL} /tmp/ffmpeg.tar.xz

# slim 镜像不带 xz 命令，用 Python 自带的 lzma 解压。
RUN set -eux; \
    mkdir -p /tmp/ff; \
    python -c "import tarfile; tarfile.open('/tmp/ffmpeg.tar.xz', 'r:xz').extractall('/tmp/ff')"; \
    install -m 755 /tmp/ff/*/bin/ffmpeg /tmp/ff/*/bin/ffprobe /usr/local/bin/; \
    rm -rf /tmp/ffmpeg.tar.xz /tmp/ff; \
    ffmpeg -version; \
    ffprobe -version

COPY src/merge_watcher.py /app/merge_watcher.py

# PID 1 的僵尸回收由 docker-compose 的 init: true 提供（替代原来的 tini）
CMD ["python", "-u", "/app/merge_watcher.py"]
