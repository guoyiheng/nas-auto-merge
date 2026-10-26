#!/usr/bin/env bash
# 一键更新：拉取最新代码并重启容器。
# 个人配置存放在 docker-compose.override.yml 中，git pull 不会改动它。
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"

if [ ! -f docker-compose.override.yml ]; then
    echo "==> 未找到 docker-compose.override.yml，正在从模板创建"
    cp docker-compose.override.example.yml docker-compose.override.yml
    echo "==> 请先编辑 docker-compose.override.yml 填写你的路径，然后重新运行 ./update.sh"
    exit 1
fi

if [ -d "$REPO_ROOT/.git" ]; then
    echo "==> 拉取最新代码"
    git -C "$REPO_ROOT" pull --ff-only
else
    echo "==> 未检测到 git 仓库，跳过代码拉取（请自行同步 app/ 目录）"
fi

echo "==> 重新构建并启动容器"
docker compose up -d --build --force-recreate
docker compose ps
