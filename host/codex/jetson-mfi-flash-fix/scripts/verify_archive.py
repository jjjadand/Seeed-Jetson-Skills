#!/usr/bin/env python3
"""Check a complete gzip stream and MFI members without extracting an archive."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile


REPAIR_FILES = (
    "recomputer-orin-super-j401.conf",
    "tools/kernel_flash/l4t_initrd_flash.sh",
    "tools/kernel_flash/l4t_flash_from_kernel.sh",
    "tools/kernel_flash/images/l4t_flash_from_kernel.sh",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--mfi-dir", type=Path, required=True)
    parser.add_argument("--archive-root", help="Top-level MFI directory in archive; defaults to local MFI directory name")
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    root = args.mfi_dir.resolve(strict=True)
    if not root.is_dir():
        parser.error("--mfi-dir must be a directory")
    archive_root = args.archive_root or root.name
    if len(PurePosixPath(archive_root).parts) != 1 or archive_root in (".", "..", "/"):
        parser.error("--archive-root must be one directory name")

    expected = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in REPAIR_FILES}
    before = archive.stat()
    members = {}
    found_hashes = {}
    top_levels = set()
    duplicates = set()
    paths_seen = set()
    unsafe_paths = []
    entries = 0
    print("Reading complete gzip stream and checking MFI members...", file=sys.stderr, flush=True)
    with gzip.open(archive, "rb") as compressed:
        with tarfile.open(fileobj=compressed, mode="r|") as package:
            for member in package:
                entries += 1
                parts = PurePosixPath(member.name).parts
                if not parts:
                    continue
                if member.name.startswith("/") or ".." in parts:
                    unsafe_paths.append(member.name)
                    continue
                normalized = "/".join(parts)
                if normalized in paths_seen:
                    duplicates.add(normalized)
                paths_seen.add(normalized)
                top_levels.add(parts[0])
                if parts[0] != archive_root:
                    continue
                relative = "/".join(parts[1:])
                members[relative] = (member.size, member.type, member.linkname)
                if relative in expected:
                    if not member.isfile():
                        raise ValueError(f"Repair file is not a regular file: {member.name}")
                    source = package.extractfile(member)
                    found_hashes[relative] = hashlib.sha256(source.read()).hexdigest()
        # tar ends before gzip EOF; consume the rest so CRC/truncation checks run.
        while compressed.read(8 * 1024 * 1024):
            pass

    after = archive.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Archive changed during validation")
    mismatches = []
    unreadable = []
    file_count = 0

    def walk_error(error):
        unreadable.append(str(error.filename))

    for directory, dirs, files in os.walk(root, onerror=walk_error):
        for name in dirs + files:
            path = Path(directory) / name
            relative = str(path.relative_to(root))
            record = members.get(relative)
            if path.is_symlink():
                file_count += 1
                if record is None or record[1] != tarfile.SYMTYPE or record[2] != os.readlink(path):
                    mismatches.append(relative + ": missing or different symlink")
            elif path.is_file():
                file_count += 1
                if record is None or record[1] not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.GNUTYPE_SPARSE, tarfile.LNKTYPE):
                    mismatches.append(relative + ": missing or non-file member")
                elif record[1] != tarfile.LNKTYPE and record[0] != path.stat().st_size:
                    mismatches.append(relative + ": different size")

    for name, digest in expected.items():
        if found_hashes.get(name) != digest:
            mismatches.append(name + ": content differs from local file")
    valid = not mismatches and not duplicates and not unsafe_paths
    result = {
        "status": "PASS" if valid else "FAIL",
        "gzip_integrity": "PASS",
        "archive": str(archive),
        "tar_entries": entries,
        "top_level_entries": sorted(top_levels),
        "extra_top_level_entries": sorted(top_levels - {archive_root}),
        "repair_files_match_local": sum(found_hashes.get(name) == digest for name, digest in expected.items()),
        "local_files_checked_for_presence_and_size": file_count,
        "mismatches": mismatches,
        "duplicate_member_paths": sorted(duplicates),
        "unsafe_member_paths": unsafe_paths,
        "unreadable_local_directories": unreadable,
        "limits": "Large image contents are checked for presence and size, not cryptographic equality. Unreadable local directories are not compared.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if valid else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, EOFError, ValueError, tarfile.TarError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
