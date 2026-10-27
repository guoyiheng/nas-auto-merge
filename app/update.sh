#!/usr/bin/env bash
# 一键更新：拉取最新代码并重启容器。
# 个人配置存放在 docker-compose.override.yml 中，git pull 不会改动它。
#
# 用法：
#   ./update.sh           镜像已存在时跳过构建，直接重启容器（日常更新）
#   ./update.sh --build   强制重新构建镜像（改动 Dockerfile 后用）
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"

FORCE_BUILD=0
case "${1:-}" in
    --build|-b) FORCE_BUILD=1 ;;
    "") ;;
    *) echo "用法: $0 [--build]" >&2; exit 2 ;;
esac

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

# bind mount 的宿主目录不会自动创建。默认的持久化状态目录是 <repo>/config，
# 容器以 override 里的 user（如 1026:100）运行，所以目录必须对该用户可写。
# 若你在 override 中把 /config 挂到了别的路径，请自行创建并设置权限。
CONFIG_DIR="$REPO_ROOT/config"
mkdir -p "$CONFIG_DIR"
CONTAINER_USER="$(sed -nE 's/^[[:space:]]*user:[[:space:]]*"?([0-9]+:[0-9]+)"?.*/\1/p' docker-compose.override.yml | head -n 1)"
if [ -n "$CONTAINER_USER" ] && chown "$CONTAINER_USER" "$CONFIG_DIR" 2>/dev/null; then
    :
else
    # 拿不到 UID:GID（或 chown 失败）时退而求其次，保证容器用户可写
    chmod 777 "$CONFIG_DIR" 2>/dev/null || true
fi

# 解析镜像名：优先问 compose（--images），老版本不支持时回退到默认命名
# <项目名>-nas-auto-merge（本项目即 app-nas-auto-merge）。
IMAGE="$(docker compose config --images 2>/dev/null | head -n 1 || true)"
if [ -z "$IMAGE" ]; then
    IMAGE="${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}-nas-auto-merge"
fi

if [ "$FORCE_BUILD" -eq 1 ]; then
    echo "==> 强制构建镜像 $IMAGE"
    docker compose up -d --build --force-recreate
elif docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "==> 镜像 $IMAGE 已存在，跳过构建（代码经 ./src:/app 挂载即时生效）"
    echo "    如需重建镜像，请执行：./update.sh --build"
    # 不带 --build：即使镜像名解析有误、镜像其实不存在，compose 也会自动补建
    docker compose up -d --force-recreate
else
    echo "==> 未找到镜像 $IMAGE，开始构建"
    docker compose up -d --build --force-recreate
fi

docker compose ps
