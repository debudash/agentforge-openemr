"""Escape `|` inside backtick code spans on markdown table rows, so cells do not split."""
import re
import sys
from pathlib import Path

CODE = re.compile(r"`[^`]*`")


def fix_line(line: str) -> str:
    if not line.startswith("|"):
        return line
    return CODE.sub(lambda m: re.sub(r"(?<!\\)\|", r"\\|", m.group(0)), line)


def fix_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    new = "\n".join(fix_line(l) for l in text.split("\n"))
    if new != text:
        path.write_text(new, encoding="utf-8", newline="\n")
        return True
    return False


if __name__ == "__main__":
    root = Path(sys.argv[1])
    changed = [p.name for p in sorted(root.rglob("*.md")) if fix_file(p)]
    print(len(changed), "files changed:", ", ".join(changed))
