"""Every markdown table row must have as many cells as its table's header."""
import re
import sys
from pathlib import Path

SPLIT = re.compile(r"(?<!\\)\|")
SEP = re.compile(r"^\|[\s:|-]+\|$")

bad = 0
for p in sorted(Path(sys.argv[1]).rglob("*.md")):
    header = None
    for n, line in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
        if not line.startswith("|"):
            header = None
            continue
        cells = len(SPLIT.split(line)) - 2
        if header is None:
            header = cells
        elif not SEP.match(line) and cells != header:
            bad += 1
            print(f"{p.name}:{n}: {cells} cells, header has {header}")
print("bad rows:", bad)
