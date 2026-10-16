#!/usr/bin/env python3
"""Check the handbook's files and local links without network access."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


REQUIRED_FILES = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "开始看这里.md",
    "docs/PRD/PRD模板.md",
    "docs/手册/AI产品Vibe Coding通用技术栈手册.md",
    "docs/手册/AI产品Vibe Coding通用前端技术栈手册.md",
    "docs/手册/AI产品 Vibe Coding 通用上线部署手册.md",
    "LICENSE",
    "NOTICE",
    ".gitignore",
    "assets/project-covers/tech-stack-handbook.png",
    "assets/project-covers/tech-stack-handbook-window.png",
    "assets/project-covers/generation.json",
)
IGNORED_PARTS = {".git", "dist", ".venv", "node_modules", "__pycache__"}
STAGES = ("PRD 体检", "技术适配", "后端 MVP", "正式前端", "上线", "收尾")


def without_code(text: str, path: str, errors: list[str]) -> str:
    """Mask fenced and inline code while preserving line numbers."""
    lines = []
    fence = None
    for number, line in enumerate(text.splitlines(keepends=True), 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            lines.append("\n" if line.endswith("\n") else "")
        elif marker:
            fence = (marker[1][0], len(marker[1]), number)
            lines.append("\n" if line.endswith("\n") else "")
        else:
            lines.append(line)
    if fence:
        errors.append(f"{path}:{fence[2]}: unclosed code fence")
    text = "".join(lines)
    text = re.sub(r"<!--.*?-->", lambda m: "\n" * m[0].count("\n"), text, flags=re.S)
    # Backtick runs must have equal lengths; unmatched runs are ordinary text.
    cursor = 0
    pieces = []
    for start in re.finditer(r"`+", text):
        if start.start() < cursor:
            continue
        end = re.search(r"(?<!`)" + re.escape(start[0]) + r"(?!`)", text[start.end():])
        if end:
            stop = start.end() + end.end()
            pieces.extend((text[cursor:start.start()], "\n" * text[start.start():stop].count("\n")))
            cursor = stop
    pieces.append(text[cursor:])
    return "".join(pieces)


def markdown_targets(text: str):
    """Yield inline/reference destinations, including <paths with spaces>."""
    stack = []
    references = {}
    definition = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*(?:<([^>]+)>|(\S+))", re.M)
    for match in definition.finditer(text):
        references[match[1].strip().casefold()] = match[2] or match[3]
    for match in definition.finditer(text):
        yield match.start(), match[2] or match[3], False
    for index, char in enumerate(text):
        if index and text[index - 1] == "\\":
            continue
        if char == "[":
            stack.append(index)
        elif char == "]" and stack:
            start = stack.pop()
            image = start > 0 and text[start - 1] == "!"
            tail = index + 1
            if tail < len(text) and text[tail] == "(":
                tail += 1
                while tail < len(text) and text[tail].isspace():
                    tail += 1
                if tail < len(text) and text[tail] == "<":
                    stop = text.find(">", tail + 1)
                    if stop >= 0:
                        yield start, text[tail + 1:stop], image
                else:
                    stop, depth = tail, 0
                    while stop < len(text):
                        current = text[stop]
                        if current == "\\" and stop + 1 < len(text):
                            stop += 2
                            continue
                        if current == "(":
                            depth += 1
                        elif current == ")":
                            if not depth:
                                break
                            depth -= 1
                        elif current.isspace() and not depth:
                            break
                        stop += 1
                    yield start, text[tail:stop], image
            elif tail < len(text) and text[tail] == "[":
                stop = text.find("]", tail + 1)
                if stop >= 0:
                    key = (text[tail + 1:stop] or text[start + 1:index]).strip().casefold()
                    if key in references:
                        yield start, references[key], image
            elif text[start + 1:index].strip().casefold() in references:
                yield start, references[text[start + 1:index].strip().casefold()], image


class HTMLTargets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        key = "src" if tag == "img" else "href" if tag == "a" else None
        if key and attributes.get(key):
            self.targets.append((self.getpos()[0], attributes[key], tag == "img"))


def check(root: Path) -> tuple[list[str], dict[str, int]]:
    root = root.resolve()
    errors = []
    stats = {"markdown_files": 0, "local_links": 0, "local_images": 0, "skipped_anchors": 0}
    for name in REQUIRED_FILES:
        if not (root / name).is_file():
            errors.append(f"{name}: required file missing")
    documents = sorted(path for path in root.rglob("*.md") if not IGNORED_PARTS.intersection(path.relative_to(root).parts))
    content = {}
    for path in documents:
        relative = path.relative_to(root).as_posix()
        stats["markdown_files"] += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError) as exc:
            errors.append(f"{relative}: cannot read UTF-8 text ({exc.__class__.__name__})")
            continue
        visible = without_code(text, relative, errors)
        content[relative] = visible
        targets = [(visible.count("\n", 0, offset) + 1, target, image) for offset, target, image in markdown_targets(visible)]
        parser = HTMLTargets()
        parser.feed(visible)
        targets.extend(parser.targets)
        for number, target, image in targets:
            target = re.sub(r"\\([() ])", r"\1", target)
            try:
                url = urlsplit(target)
            except ValueError:
                errors.append(f"{relative}:{number}: invalid link destination")
                continue
            if url.scheme or url.netloc:
                continue
            if not url.path:
                if url.fragment:
                    stats["skipped_anchors"] += 1
                continue
            stats["local_images" if image else "local_links"] += 1
            destination = (path.parent / unquote(url.path)).resolve()
            if not destination.is_relative_to(root):
                errors.append(f"{relative}:{number}: local link escapes repository: {target}")
            elif not destination.exists() or (image and not destination.is_file()):
                errors.append(f"{relative}:{number}: missing local {'image' if image else 'link'}: {target}")
    agents = content.get("AGENTS.md", "")
    for number, label in enumerate(STAGES):
        if not re.search(rf"^\|\s*{number}\s+{re.escape(label)}\s*\|", agents, re.M):
            errors.append(f"AGENTS.md: missing stage {number} {label} in the workflow table")
    fields = re.findall(r"^##\s+([1-8])\.\s+\S", content.get("docs/PRD/PRD模板.md", ""), re.M)
    if fields != [str(number) for number in range(1, 9)]:
        errors.append("docs/PRD/PRD模板.md: expected eight ordered PRD fields (1–8)")
    claude = (root / "CLAUDE.md")
    if claude.is_file() and not re.search(r"^\s*@AGENTS\.md\s*$", claude.read_text(encoding="utf-8"), re.M):
        errors.append("CLAUDE.md: expected @AGENTS.md rule-card import")
    license_file = root / "LICENSE"
    if license_file.is_file() and not re.search(r"Copyright\s+\(c\)\s+\d{4}\s+\S", license_file.read_text(encoding="utf-8"), re.I):
        errors.append("LICENSE: copyright notice missing")
    return errors, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="handbook root (default: script's repository)")
    args = parser.parse_args()
    errors, stats = check(args.root)
    for message in errors:
        print(f"ERROR {message}", file=sys.stderr)
    print("Document check: " + ", ".join(f"{key}={value}" for key, value in stats.items()))
    print(f"{'FAIL' if errors else 'PASS'}: {len(errors)} error(s); remote URLs and anchor targets are not checked.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
