"""Asset catalog: every picture/animation in a folder tree, described once by the vision model and cached.

Asset ids are "<subfolder>/<file stem>" so the model can refer to them by meaning ("spider/04-lava-2").
"""
import io
import json
from pathlib import Path

from PIL import Image

from .config import CACHE
from .media import h

EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def scan(root: Path):
    root = Path(root)
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() in EXTS and p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts):
            rel = p.relative_to(root)
            yield "/".join(rel.parts[:-1] + (p.stem,)), p


def catalog_path(root: Path) -> Path:
    d = CACHE / "catalogs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{Path(root).name}-{h(Path(root).resolve())}.json"


def load_or_build(root: Path, llm=None, on_item=None) -> dict:
    """Returns {asset_id: {path, what, mood, orientation, kind}}. Describes new files with the vision model if given."""
    out = catalog_path(root)
    cat = json.loads(out.read_text()) if out.exists() else {}
    schema = {"type": "object", "properties": {"what": {"type": "string"}, "mood": {"type": "string"}}, "required": ["what", "mood"]}
    for key, p in scan(root):
        mtime = p.stat().st_mtime
        if key in cat and cat[key].get("mtime") == mtime:
            continue
        im = Image.open(p)
        im.seek(0)
        w, hgt = im.size
        entry = {"path": str(p), "mtime": mtime, "orientation": "vertical" if hgt > w else "horizontal",
                 "kind": "animated" if p.suffix.lower() == ".gif" else "still", "what": p.stem.replace("-", " "), "mood": ""}
        if llm is not None:
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "PNG")
            try:
                v = llm.vision(buf.getvalue(), "Опиши картинку для монтажёра по-русски: what — что изображено (до 12 слов), mood — настроение (1-3 слова).", schema)
                entry["what"], entry["mood"] = v["what"][:120], v["mood"][:40]
            except Exception as e:  # keep the file usable even if vision fails
                entry["mood"] = f"(не описано: {str(e)[:40]})"
        cat[key] = entry
        on_item and on_item(key, entry)
        out.write_text(json.dumps(cat, ensure_ascii=False, indent=1))
    present = {k for k, _ in scan(root)}
    return {k: v for k, v in cat.items() if k in present}


def compact_list(cat: dict, prefix="") -> str:
    """One line per asset for the prompt: id | what | mood."""
    return "\n".join(f"{k} | {v['what']} | {v['mood']}{' | анимация' if v['kind'] == 'animated' else ''}"
                     for k, v in cat.items() if k.startswith(prefix))
