#!/usr/bin/env python3
"""End-to-end web picture gathering for a task, ready for the catalog/montage.

    scripts/fetch_demo.py "сделай ролик про семью" --dest /tmp/family [--max 30] [--per-query 6]
        [--orientation vertical] [--providers openverse,wikimedia,searxng] [--no-check] [--sheet sheet.jpg]

Needs a running llama-server (scripts/serve_llm.sh start agent) for query planning and the vision check.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from assemblee import assets, fetch  # noqa: E402
from assemblee.config import FONT_BOOK  # noqa: E402
from assemblee.llm import LLM  # noqa: E402


def contact_sheet(cat, out, cell=300, cols=6):
    items = sorted(cat.items())
    rows = max(1, -(-len(items) // cols))
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 40)), (24, 24, 24))
    font = ImageFont.truetype(FONT_BOOK, 13)
    d = ImageDraw.Draw(sheet)
    for i, (k, v) in enumerate(items):
        im = Image.open(v["path"]).convert("RGB")
        im.thumbnail((cell - 8, cell - 8))
        x, y = (i % cols) * cell, (i // cols) * (cell + 40)
        sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        d.text((x + 4, y + cell), k[:44], fill=(255, 220, 120), font=font)
        d.text((x + 4, y + cell + 18), v["what"][:44], fill=(220, 220, 220), font=font)
    sheet.save(out, quality=85)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--max", type=int, default=30)
    ap.add_argument("--per-query", type=int, default=6)
    ap.add_argument("--orientation", choices=["vertical", "horizontal", "square"])
    ap.add_argument("--providers", default=",".join(fetch.DEFAULT_PROVIDERS))
    ap.add_argument("--no-check", action="store_true")
    ap.add_argument("--sheet", help="contact sheet path (default <dest>/contact_sheet.jpg)")
    a = ap.parse_args()

    llm = LLM()
    if not llm.health():
        sys.exit("llama-server is not running: scripts/serve_llm.sh start agent")
    t0 = time.time()

    def on_event(kind, data):
        if kind == "tool_call" and data["name"] != "download_image":
            print(f"→ {data['name']} {json.dumps(data['args'], ensure_ascii=False)[:160]}")
        elif kind == "tool_result":
            mark = "✓" if data["ok"] else "✗"
            print(f"  {mark} {data['name']} {data['seconds']}s {json.dumps(data['result'], ensure_ascii=False)[:200]}")
        elif kind == "warning":
            print(f"  ! {data['message']}")

    dest = fetch.gather(a.task, llm, a.dest, per_query=a.per_query, max_total=a.max, orientation=a.orientation,
                        providers=tuple(p for p in a.providers.split(",") if p), check=not a.no_check, on_event=on_event)
    described = []
    cat = assets.load_or_build(dest, llm, on_item=lambda k, e: described.append(k))
    credits = fetch.load_credits(dest)
    clear = sum(1 for c in credits.values() if c.get("license_clear"))
    print(f"\n{len(cat)} pictures in {dest} ({time.time() - t0:.0f} s); described again by the catalog: {len(described)}")
    print(f"credits.json: {len(credits)} entries, clear CC/PD licence: {clear}")
    by = {}
    for c in credits.values():
        by[c["license"]] = by.get(c["license"], 0) + 1
    print("licences:", ", ".join(f"{k} ×{v}" for k, v in sorted(by.items(), key=lambda x: -x[1])))
    if cat:
        print("contact sheet:", contact_sheet(cat, a.sheet or str(Path(dest) / ".contact_sheet.jpg")))
    print(assets.compact_list(cat))


if __name__ == "__main__":
    main()
