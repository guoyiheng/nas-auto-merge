#!/usr/bin/env bash
# 端到端自测：生成两段测试分片 -> 跑一次合并 -> 校验产物/清理/时长。
#
# 用法：
#   ./test.sh
#
# 前提：镜像已构建（先执行 ./update.sh --build）。
# 测试在临时目录里进行，不会碰你挂载的真实视频目录。
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE=(docker compose -f docker-compose.yml)
SERVICE=nas-auto-merge

IMAGE="$("${COMPOSE[@]}" config --images 2>/dev/null | head -n 1 || true)"
if [ -z "$IMAGE" ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "找不到镜像，请先执行：./update.sh --build" >&2
    exit 1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/nas-auto-merge-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/watch" "$WORK/state"

run() {
    # -T 禁用 TTY（脚本/非交互环境），--user 让产物归属当前用户以便清理临时目录
    "${COMPOSE[@]}" run --rm --no-deps -T \
        --user "$(id -u):$(id -g)" -v "$WORK:/work" "$@"
}

echo "==> 1/4 用镜像内的 ffmpeg 生成两段测试分片"
run "$SERVICE" sh -c '
set -e
gen() {
    ffmpeg -hide_banner -loglevel error -y \
        -f lavfi -i "testsrc=size=320x240:rate=15:duration=2" \
        -f lavfi -i "sine=frequency=$2:sample_rate=48000:duration=2" \
        -c:v mpeg4 -q:v 5 -c:a aac -shortest "/work/watch/$1"
}
gen title-cd1.mp4 440
gen title-cd2.mp4 660
'
ls -l "$WORK/watch"

echo "==> 2/4 跑一次合并（--run-once）"
run \
    -e WATCH_DIRS=/work/watch \
    -e STATE_FILE=/work/state/state.json \
    -e MIN_FILE_AGE_SECONDS=0 \
    -e DELETE_SOURCES_ON_SUCCESS=true \
    -e LOG_LEVEL=INFO \
    "$SERVICE" python -u /app/merge_watcher.py --run-once

echo "==> 3/4 校验产物与源分片清理"
fail=0
[ -f "$WORK/watch/merged/title.mp4" ] || { echo "  FAIL: 未生成 merged/title.mp4"; fail=1; }
[ -f "$WORK/watch/title-cd1.mp4" ] && { echo "  FAIL: 源分片 cd1 未被删除"; fail=1; }
[ -f "$WORK/watch/title-cd2.mp4" ] && { echo "  FAIL: 源分片 cd2 未被删除"; fail=1; }
[ "$fail" -eq 0 ] || exit 1
echo "  产物: merged/title.mp4"

echo "==> 4/4 用 ffprobe 校验合并结果可读、时长约为 4s"
dur="$(run "$SERVICE" ffprobe -v error \
    -show_entries format=duration -of default=nk=1:nw=1 \
    /work/watch/merged/title.mp4 | tr -d '\r')"
echo "  duration=${dur}s"
awk -v d="$dur" 'BEGIN { if (d < 3 || d > 5) { print "  FAIL: 时长异常（期望约 4s）"; exit 1 } }'

echo "==> 测试通过 ✅"
