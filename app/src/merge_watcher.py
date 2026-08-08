#!/usr/bin/env python3
import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path


STATE_FILE = Path(os.getenv("STATE_FILE", "/config/state.json"))
WATCH_DIRS = tuple(
    Path(item.strip()).resolve()
    for item in (os.getenv("WATCH_DIRS") or os.getenv("WATCH_DIR", "/watch")).split(",")
    if item.strip()
)
MERGED_SUBDIR = os.getenv("MERGED_SUBDIR", "merged")
PART_SUBDIR = os.getenv("PART_SUBDIR", "part")
FAILED_SUBDIR = os.getenv("FAILED_SUBDIR", "failed")
RUN_AT = os.getenv("RUN_AT", "02:00")
RUN_ON_START = os.getenv("RUN_ON_START", "false").lower() in {"1", "true", "yes"}
MIN_FILE_AGE_SECONDS = max(0, int(os.getenv("MIN_FILE_AGE_SECONDS", "300")))
MIN_PARTS = max(2, int(os.getenv("MIN_PARTS", "2")))
RECURSIVE = os.getenv("RECURSIVE", "false").lower() in {"1", "true", "yes"}
EXTENSIONS = {
    item.strip().lower() if item.strip().startswith(".") else f".{item.strip().lower()}"
    for item in os.getenv("EXTENSIONS", ".mp4,.mkv,.mov,.m4v,.ts").split(",")
    if item.strip()
}

# Supported examples: title-cd1, title-CD2, title-part1, title_part2, title.cd3.
PART_RE = re.compile(
    r"^(?P<base>.+?)[-_. ]+(?:cd|part)[-_. ]*(?P<number>[1-9]\d*)(?P<ext>\.[^.]+)$",
    re.I,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("nas-auto-merge")


def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"outputs": {}}
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Cannot read state file %s: %s", STATE_FILE, exc)
        return {"outputs": {}}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, STATE_FILE)


def stat_identity(path):
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino}


def output_is_managed(output, record):
    if not record or not output.is_file() or not record.get("output_identity"):
        return False
    current = stat_identity(output)
    saved = record["output_identity"]
    return (
        current["size"] == saved.get("size")
        and (
            current["inode"] == saved.get("inode")
            or current["mtime_ns"] == saved.get("mtime_ns")
        )
    )


def infer_plain_number(numbers):
    if not numbers:
        return 1
    for number in range(1, max(numbers) + 1):
        if number not in numbers:
            return number
    return max(numbers) + 1


def archive_dir(root, subdir):
    return root / subdir


def output_path_for(path, root, base, ext):
    relative_parent = path.parent.relative_to(root)
    return archive_dir(root, MERGED_SUBDIR) / relative_parent / f"{base}{ext}"


def is_archived(path):
    return any(
        path == archive_root or archive_root in path.parents
        for root in WATCH_DIRS
        for archive_root in (
            archive_dir(root, MERGED_SUBDIR),
            archive_dir(root, PART_SUBDIR),
            archive_dir(root, FAILED_SUBDIR),
        )
    )


def discover_groups():
    groups = {}

    for root in WATCH_DIRS:
        candidates = root.rglob("*") if RECURSIVE else root.iterdir()
        for path in candidates:
            if not path.is_file() or is_archived(path):
                continue
            match = PART_RE.match(path.name)
            if not match or match.group("ext").lower() not in EXTENSIONS:
                continue

            output = output_path_for(path, root, match.group("base"), match.group("ext"))
            number = int(match.group("number"))
            group = groups.setdefault(
                output,
                {
                    "root": root,
                    "numbered": {},
                    "duplicates": set(),
                    "plain_path": path.parent / f"{match.group('base')}{match.group('ext')}",
                },
            )
            if number in group["numbered"]:
                group["duplicates"].add(number)
            group["numbered"].setdefault(number, path)

    ready = {}
    for output, group in groups.items():
        if group["duplicates"]:
            log.warning(
                "Skipping %s: duplicate part numbers %s",
                output.name,
                sorted(group["duplicates"]),
            )
            continue

        parts = {
            number: {
                "number": number,
                "path": path,
                "root": group["root"],
                "plain": False,
            }
            for number, path in group["numbered"].items()
        }
        plain_path = group["plain_path"]
        if plain_path.is_file():
            number = infer_plain_number(set(parts))
            parts[number] = {
                "number": number,
                "path": plain_path,
                "root": group["root"],
                "plain": True,
            }

        if len(parts) >= MIN_PARTS:
            ready[output] = [parts[number] for number in sorted(parts)]
    return ready


def source_signature(parts):
    return [
        {
            "number": part["number"],
            "path": str(part["path"]),
            **stat_identity(part["path"]),
        }
        for part in parts
    ]


def stream_signature(path):
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        (
            "stream=index,codec_type,codec_name,width,height,pix_fmt,r_frame_rate,"
            "time_base,sample_rate,channels,channel_layout"
        ),
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    streams = json.loads(result.stdout).get("streams", [])
    for stream in streams:
        stream.pop("index", None)
    return streams


def verify_compatible(parts):
    expected = stream_signature(parts[0]["path"])
    for part in parts[1:]:
        actual = stream_signature(part["path"])
        if actual != expected:
            raise ValueError(
                f"stream parameters differ: {parts[0]['path'].name} and {part['path'].name}"
            )


def ffconcat_quote(path):
    if "\n" in str(path) or "\r" in str(path):
        raise ValueError(f"newline is not supported in filename: {path.name}")
    return str(path).replace("'", "'\\''")


def merge_parts(output, parts):
    verify_compatible(parts)
    output.parent.mkdir(parents=True, exist_ok=True)
    list_path = None
    temp_output = output.with_name(f".{output.stem}.automerge-{uuid.uuid4().hex}{output.suffix}")

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".automerge-",
            suffix=".ffconcat",
            dir=output.parent,
            delete=False,
        ) as handle:
            list_path = Path(handle.name)
            handle.write("ffconcat version 1.0\n")
            for part in parts:
                handle.write(f"file '{ffconcat_quote(part['path'].resolve())}'\n")

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostdin",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-map",
            "0",
            "-c",
            "copy",
            str(temp_output),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "ffmpeg failed")
        if not temp_output.exists() or temp_output.stat().st_size == 0:
            raise RuntimeError("ffmpeg produced an empty output")

        os.replace(temp_output, output)
        return parts
    finally:
        if list_path:
            list_path.unlink(missing_ok=True)
        temp_output.unlink(missing_ok=True)


def move_sources(parts, destination_root):
    moves = []
    for part in parts:
        source = part["path"]
        root = part["root"]
        destination = archive_dir(root, destination_root) / source.relative_to(root)
        if destination.exists():
            for index in range(1, 10000):
                candidate = destination.with_name(
                    f"{destination.stem}.{index}{destination.suffix}"
                )
                if not candidate.exists():
                    destination = candidate
                    break
            else:
                raise FileExistsError(f"too many destination conflicts: {destination}")
        moves.append((source, destination))

    for source, destination in moves:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    return [
        {**part, "path": destination, "plain": False}
        for part, (_, destination) in zip(parts, moves)
    ]


def group_is_old_enough(parts):
    newest_mtime = max(part["path"].stat().st_mtime for part in parts)
    return time.time() - newest_mtime >= MIN_FILE_AGE_SECONDS


def scan_once():
    state = load_state()
    outputs_state = state.setdefault("outputs", {})
    groups = discover_groups()
    log.info("Scan found %d merge group(s)", len(groups))

    for output, parts in groups.items():
        try:
            if not group_is_old_enough(parts):
                log.info("Skipping %s: one or more files are too new", output.name)
                continue

            signature = source_signature(parts)
            record = outputs_state.get(str(output))
            if (
                record
                and record.get("source_signature") == signature
                and output_is_managed(output, record)
            ):
                continue

            log.info(
                "Merging %s -> %s",
                ", ".join(part["path"].name for part in parts),
                output.name,
            )
            merge_parts(output, parts)
            moved_parts = move_sources(parts, PART_SUBDIR)
            outputs_state[str(output)] = {
                "source_signature": source_signature(moved_parts),
                "parts": [str(part["path"]) for part in moved_parts],
                "output_identity": stat_identity(output),
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            save_state(state)
            log.info("Created %s", output)
            log.info("Moved %d source part(s) to %s", len(moved_parts), PART_SUBDIR)
        except Exception as exc:
            log.error("Merge failed for %s: %s", output.name, exc)
            try:
                remaining = [part for part in parts if part["path"].exists()]
                if remaining:
                    move_sources(remaining, FAILED_SUBDIR)
                    log.info("Moved failed source part(s) to %s", FAILED_SUBDIR)
            except Exception as move_exc:
                log.error("Could not move failed source parts: %s", move_exc)


def parse_run_at(value):
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value.strip())
    if not match:
        raise ValueError("RUN_AT must use 24-hour HH:MM format, for example 02:30")
    return int(match.group(1)), int(match.group(2))


def next_run(now, hour, minute):
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_scheduler():
    hour, minute = parse_run_at(RUN_AT)
    log.info("Daily schedule enabled at %02d:%02d", hour, minute)
    if RUN_ON_START:
        scan_once()

    while True:
        now = datetime.now()
        target = next_run(now, hour, minute)
        log.info("Next scan: %s", target.strftime("%Y-%m-%d %H:%M:%S"))
        time.sleep(max(0, (target - now).total_seconds()))
        scan_once()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-once", action="store_true", help="scan immediately and exit")
    args = parser.parse_args()
    if not os.getenv("WATCH_DIRS"):
        log.warning(
            "WATCH_DIRS is not set; using fallback watch dir(s): %s",
            ", ".join(str(root) for root in WATCH_DIRS),
        )
    log.info(
        "Scanning %d watch dir(s): %s",
        len(WATCH_DIRS),
        ", ".join(str(root) for root in WATCH_DIRS),
    )

    missing = [str(root) for root in WATCH_DIRS if not root.is_dir()]
    if missing:
        raise SystemExit("WATCH_DIRS do not exist: " + ", ".join(missing))
    if args.run_once:
        scan_once()
    else:
        run_scheduler()


if __name__ == "__main__":
    main()
