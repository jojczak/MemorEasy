from .media_processing import (
    merge_mp4_with_overlay,
    merge_jpg_with_overlay
)
from .metadata import (
    write_exif,
)
from .exceptions import (
    DownloadError,
    DependencyError
)
from .dependencies import find_dependency
from pathlib import Path
import shutil
import os
import datetime

# =========================================================================== #

FAILED_LOG_PATH = "failed_files.log"


def log_failed_file(file_path, error) -> None:
    with open(FAILED_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{file_path}\t{error}\n")


def parse_filename_datetime(filename: str) -> datetime.datetime:

    path = "memories/" + filename
    timestamp = os.path.getmtime(path)
    datestamp = datetime.datetime.fromtimestamp(timestamp,
                                                tz=datetime.timezone.utc)

    return datestamp.replace(tzinfo=datetime.timezone.utc)


def parse_metadata_datetime(date_str: str) -> datetime.datetime:

    clean_date = date_str.replace("UTC", "").strip()
    dt = datetime.datetime.strptime(clean_date, "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=datetime.timezone.utc)


def scan_memories(
    memories: list[dict[str, str]],
) -> None:

    MEMORIES_DIR = Path("./memories")
    FINAL_DIR = Path("./final")
    FINAL_DIR.mkdir(exist_ok=True)

    overlay_map = {}
    main_files = []

    # Find overlay images for corresponding main files and store in map
    for file in MEMORIES_DIR.iterdir():

        if not file.is_file():
            continue

        name = file.name

        if "-overlay" in name:
            # Key example:
            # 2025-11-15_UUID
            key = name.replace("-overlay.png", "")
            overlay_map[key] = file

        elif "-main" in name:
            main_files.append(file)

    # Sort on modification date instead of file name
    main_files.sort(
        key=lambda p: p.stat().st_mtime,
        reverse=True  # newest first
    )

    file_idx = 0
    mem_idx = 0
    total_files = len(main_files)
    total_memories = len(memories)

    # Find ffmpeg dependency
    try:
        ffmpeg_path = find_dependency("ffmpeg")
    except DependencyError:
        raise  # Re-raise to be handled by caller

    # Find exiftool dependency
    try:
        exiftool_path = find_dependency("exiftool")
    except DependencyError:
        raise

    while file_idx < total_files and mem_idx < total_memories:
        file_path = main_files[file_idx]
        current_memory = memories[mem_idx]

        print(
            f"\rProcessing {file_idx + 1}/{total_files}: {file_path}...",
            end="",
            flush=True
        )

        date_str = current_memory["date"]
        lat = current_memory["lat"]
        lon = current_memory["lon"]

        file_dt = parse_filename_datetime(file_path.name)
        memory_dt = parse_metadata_datetime(date_str)

        diff_mins = abs(file_dt.minute - memory_dt.minute)
        diff_secs = abs(file_dt.second - memory_dt.second)

        BUFFER_SECONDS = 10
        BUFFER_MINUTES = 2

        if diff_mins < BUFFER_MINUTES and diff_secs <= BUFFER_SECONDS:
            try:
                # Format: "2025-12-09 11:10:51 UTC" -> "2025-12-09-111051"
                name = date_str.replace(" ", "-")[:-4]
                name = name.replace(":", "")
            except DownloadError as e:
                print(
                    f"\nMemory {mem_idx}: Invalid date format '{date_str}',\
                        skipping: {e}"
                     )
                continue

            final_main = FINAL_DIR / file_path.name
            shutil.copy2(file_path, final_main)
            write_exif(final_main, date_str, lat, lon, exiftool_path)

            key = file_path.stem.replace("-main", "")
            overlay_file = overlay_map.get(key)
            ext = file_path.suffix.lower()

            if overlay_file is not None and ext in (".mp4", ".jpg"):
                final_overlay = FINAL_DIR / overlay_file.name
                shutil.copy2(overlay_file, final_overlay)
                expected_combined = FINAL_DIR / final_main.name.replace(
                    "-main", "-combined"
                )

                try:
                    if ext == ".mp4":
                        combined_path = merge_mp4_with_overlay(
                            final_main, final_overlay, ffmpeg_path)
                    else:
                        combined_path = merge_jpg_with_overlay(
                            final_main, final_overlay)

                    if combined_path is None:
                        combined_path = expected_combined

                    write_exif(combined_path, date_str, lat, lon,
                               exiftool_path)


                    final_main.unlink(missing_ok=True)
                    final_overlay.unlink(missing_ok=True)

                except Exception as e:
                    print(f"\nInvalid overlay for {file_path}, "
                          f"keeping only the main file: {e}")
                    log_failed_file(file_path, e)
                    
                    final_overlay.unlink(missing_ok=True)
                    expected_combined.unlink(missing_ok=True)

            file_idx += 1
            mem_idx += 1

        elif file_dt < memory_dt:
            mem_idx += 1
            print("Non-matching memory for: ", file_path)
            print("Moving to next memory: ", memories[mem_idx])

        elif file_dt > memory_dt:
            file_idx += 1
            print("Non-matching file: ", file_path)
            print("Moving to next file: ", main_files[file_idx])
