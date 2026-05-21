import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent.parent
MOJIBAKE_MARKERS = (
    "\ufffd",
    "鈹",
    "锛",
    "鐢",
    "绯",
    "鏄",
    "涓",
    "乄",
    "丄",
    "孫",
)


def _markdown_files():
    ignored_dirs = {".git", ".pytest_cache", ".claude", ".idea"}
    for path in ROOT.rglob("*.md"):
        if ignored_dirs.intersection(path.parts):
            continue
        yield path


def test_markdown_files_are_utf8_and_not_mojibake():
    bad = []
    for path in _markdown_files():
        text = path.read_text(encoding="utf-8")
        markers = [marker for marker in MOJIBAKE_MARKERS if marker in text]
        if markers:
            bad.append(f"{path.relative_to(ROOT)} contains {markers}")

    assert bad == []


def test_relative_markdown_links_exist():
    missing = []
    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for path in _markdown_files():
        text = path.read_text(encoding="utf-8")
        for raw_target in link_re.findall(text):
            target = raw_target.strip()
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            target = unquote(target.split("#", 1)[0])
            if not target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                missing.append(f"{path.relative_to(ROOT)} -> {target}")

    assert missing == []
