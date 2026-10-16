#!/usr/bin/env python3
"""Build and verify a deterministic, source-only handbook download."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from check_docs import REQUIRED_FILES, check


PREFIX = "tech-stack-handbook"
ROOT = Path(__file__).resolve().parents[1]
FILES = (*REQUIRED_FILES, "scripts/check_docs.py", "scripts/package_release.py", ".github/workflows/docs.yml")


def main() -> int:
    errors, _ = check(ROOT)
    for name in FILES:
        if not (ROOT / name).is_file():
            errors.append(f"{name}: required package file missing")
        elif (ROOT / name).is_symlink() or not (ROOT / name).resolve().is_relative_to(ROOT):
            errors.append(f"{name}: package members must be regular repository files")
    if errors:
        for message in dict.fromkeys(errors):
            print(f"ERROR {message}", file=sys.stderr)
        return 1
    output_dir = ROOT / "dist"
    output_dir.mkdir(exist_ok=True)
    output = output_dir / f"{PREFIX}.zip"
    temporary = output.with_suffix(".zip.tmp")
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for name in sorted(set(FILES)):
                info = ZipInfo(f"{PREFIX}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, (ROOT / name).read_bytes(), compresslevel=9)
        with tempfile.TemporaryDirectory(prefix="handbook-verify-") as folder:
            with ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise ValueError("ZIP integrity check failed")
                archive.extractall(folder)
            extracted = Path(folder) / PREFIX
            errors, stats = check(extracted)
            if errors:
                raise ValueError("Packaged document check failed: " + "; ".join(errors))
            for name in FILES:
                if (extracted / name).read_bytes() != (ROOT / name).read_bytes():
                    raise ValueError(f"Packaged file content differs: {name}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"PASS: dist/{output.name}; {len(set(FILES))} files; {output.stat().st_size} bytes")
    print(f"SHA-256: {digest}")
    print(f"Extracted package verified: {stats['markdown_files']} Markdown files, all local links and images available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
