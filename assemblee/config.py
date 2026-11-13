"""Paths and constants. Every path can be overridden with an environment variable."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _p(env, default):
    return Path(os.environ.get(env, default)).expanduser()


FILMCRAFT_CLI = _p("ASSEMBLEE_FILMCRAFT", "~/craft/filmcraft/filmcraft-0.20.1-linux-x86_64/bin/filmcraft-cli")
EFFECTCRAFT_CLI = _p("ASSEMBLEE_EFFECTCRAFT", "~/craft/effectcraft/effectcraft-0.24.1-linux-x86_64/bin/effectcraft-cli")
LLM_URL = os.environ.get("ASSEMBLEE_LLM_URL", "http://127.0.0.1:8011")
CACHE = _p("ASSEMBLEE_CACHE", REPO / ".cache")
AUDIO_DIR = _p("ASSEMBLEE_AUDIO", CACHE / "audio")
RUNS = _p("ASSEMBLEE_RUNS", REPO / "runs")

W, H, FPS = 1080, 1920, 30
TICKS = 254016000000  # FilmCraft ticks per second

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_BOOK = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_SANS = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
RENDER_VERSION = 3  # bump when rendering of captions/cards/pictures changes
