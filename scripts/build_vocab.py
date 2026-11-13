#!/usr/bin/env python3
"""Build assemblee/vocab_data.json: the "rich" creative vocabulary, checked against the real engines.

Queries FilmCraft `effects.list` (detail) and EffectCraft `list_effects`, then merges the engine data with the
hand-written notes below: a one-line description of what each transition/effect LOOKS like, the parameters the
model may touch with SAFE ranges (verified on rendered frames, see scripts/smoke_rich.py), a preset that makes the
effect visible when the model gives no values, and an exclusion reason for technical, duplicate or useless items.

Every engine id must be either described or excluded: an engine upgrade that adds something fails loudly here.

usage: python3 scripts/build_vocab.py            (writes assemblee/vocab_data.json)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemblee.config import EFFECTCRAFT_CLI, FILMCRAFT_CLI  # noqa: E402
from assemblee.mcp import MCP  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "assemblee" / "vocab_data.json"
DIRS = ["From North", "From East", "From South", "From West"]


def T(desc, params=None, preset=None, main=None):
    return {"desc": desc, "params": params or {}, "preset": preset or {}, "main": main}


# ---------------------------------------------------------------- transitions
# params: {id: (lo, hi) | "color" | "bool" | [choice names]}; main: the param that `amount` (0..1) drives.
TRANSITIONS = {
    # Animation
    "block_motion": T("picture breaks into sliding blocks that fly in from one side", {"direction": DIRS, "blocks": (3, 16)}, main="blocks"),
    "flip_motion": T("outgoing picture flips away like a card, the next one flips in", {"direction": DIRS}),
    "fold_motion": T("picture folds in half like paper and unfolds into the next", {"direction": DIRS}),
    "pop_motion": T("next picture pops in from small with a springy overshoot", {"overshoot": (0, 60)}, main="overshoot"),
    "pull_motion": T("outgoing picture is pulled away, shrinking toward the edge", {"direction": DIRS}),
    "spin_motion": T("both pictures spin around the centre with motion blur", {"rotation": (90, 720), "spin": ["Clockwise", "Counter-clockwise"]}, main="rotation"),
    "spring_motion": T("next picture bounces in on a spring from one side", {"direction": DIRS, "bounce": (10, 80)}, main="bounce"),
    "travel_motion": T("camera travels sideways from one picture to the next, both shrink a little", {"direction": DIRS, "zoom": (10, 60)}, main="zoom"),
    # Dissolve
    "additive_dissolve": T("bright dissolve: the two pictures add up, highlights flare"),
    "blur_dissolve": T("dissolve through a heavy blur, soft and dreamy", {"blur": (10, 120)}, main="blur"),
    "burn_alpha": T("outgoing picture burns away with glowing fiery edges", {"burn_color": "color", "softness": (10, 60)}, main="softness"),
    "cross_dissolve": T("classic soft cross-fade"),
    "dip_to_black": T("fade to black, then up into the next picture"),
    "dip_to_color": T("fade through a solid colour (default red)", {"color": "color", "hold": (0, 40)}, preset={"color": "#d83333"}),
    "dip_to_white": T("fade through white, like an overexposed flash"),
    "film_dissolve": T("film-like dissolve with a slightly darker, gamma-correct mix"),
    "luma_fade": T("dissolve where the bright areas change first, then the darks", {"softness": (5, 60)}, main="softness"),
    "mosaic_transition": T("pictures dissolve through big pixel blocks", {"block_size": (16, 160)}, main="block_size"),
    "non_additive_dissolve": T("dissolve where the brighter picture wins pixel by pixel, contrasty"),
    # Grunge & Distort
    "chaos": T("broken digital blocks tear the picture apart, harsh glitch", {"amount": (20, 100)}, main="amount"),
    "earthquake": T("violent shake with motion blur across the cut", {"shake": (10, 120)}, main="shake"),
    "flicker": T("rapid flickering between the two pictures like a bad bulb", {"flickers": (3, 20)}, main="flickers"),
    "glass": T("picture shatters into glass cells that refract the next one", {"cell_size": (40, 200), "refraction": (10, 100)}, main="refraction"),
    "glitch": T("digital glitch: coloured blocks and RGB noise over the cut", {"amount": (20, 100)}, main="amount"),
    "grunge": T("dirty burnt-paper holes eat the picture away", {"scale": (60, 300)}, main="scale"),
    "kaleidoscope": T("pictures turn into a spinning kaleidoscope mandala", {"segments": (3, 12), "zoom": (10, 60)}, main="segments"),
    "liquid_distortion": T("picture melts and wobbles like liquid into the next", {"amount": (20, 200)}, main="amount"),
    "tv_power": T("old TV switching off to a white line and back on", {"glow_color": "color", "line": (2, 12)}),
    "vhs_damage": T("VHS tape damage: noise, colour bleed and tracking lines", {"amount": (20, 100)}, main="amount"),
    # Immersive (the flat-frame-friendly ones)
    "vr_light_rays": T("blinding starburst of light rays from the centre", {"amount": (30, 100)}, main="amount"),
    "vr_mobius_zoom": T("psychedelic spiral zoom that twists both pictures", {"zoom": (20, 90)}, main="zoom"),
    "vr_random_blocks": T("random square blocks switch to the next picture", {"block_size": (40, 240)}, main="block_size"),
    # Lights & Blurs
    "burn_chroma": T("hot colour burn: the cut flares through saturated colour", {"amount": (30, 100)}, main="amount"),
    "chroma_leak": T("rainbow chroma leak washes over the cut", {"amount": (30, 100)}, main="amount"),
    "cross_zoom": T("fast zoom-blur punch into the next picture", {"strength": (20, 100)}, main="strength"),
    "directional_blur_transition": T("sideways motion-blur smear between pictures", {"angle": (0, 180), "blur": (40, 400)}, main="blur"),
    "flare": T("warm anamorphic lens flare sweeps across the cut", {"color": "color", "amount": (30, 100)}, main="amount"),
    "flash": T("bright white camera flash at the cut", {"color": "color", "intensity": (40, 100)}, main="intensity"),
    "glow": T("everything blooms into glow, then settles on the next picture", {"radius": (10, 120), "intensity": (30, 100)}, main="intensity"),
    "lens_blur": T("defocus out, refocus in (camera lens blur)", {"radius": (8, 80)}, main="radius"),
    "light_leak": T("warm orange film light leak over the cut", {"color": "color", "amount": (30, 100)}, main="amount"),
    "light_sweep": T("a bright diagonal light bar sweeps across", {"angle": (0, 180), "width": (60, 400), "color": "color"}, main="width"),
    "phosphor": T("old CRT phosphor afterglow: outgoing picture lingers as a glow", {"decay": (20, 90)}, main="decay"),
    "radial_blur": T("spin blur around the centre into the next picture", {"angle": (10, 120)}, main="angle"),
    "ray": T("light rays streak out of the bright parts", {"amount": (30, 100), "length": (20, 90)}, main="amount"),
    "solarize": T("colours invert and posterize for a moment, psychedelic", {"amount": (40, 100)}, main="amount"),
    "stripe": T("diagonal black-and-white stripes wipe across", {"stripes": (3, 20), "angle": (0, 180), "color": "color"}, main="stripes"),
    "zoom_blur": T("radial zoom blur out of one picture into the next", {"strength": (20, 100)}, main="strength"),
    # Slide
    "roll_3d": T("3D cube-like roll from one picture to the next", {"direction": DIRS}),
    "film_roll": T("film strip rolls by with sprocket holes between frames", {"direction": DIRS, "gap": (10, 120)}, main="gap"),
    "push": T("next picture pushes the old one out of frame", {"direction": DIRS}),
    "roll": T("pictures roll past with a slight 3D bend", {"direction": DIRS}),
    "slide": T("next picture slides in over the old one", {"direction": DIRS}),
    "split": T("old picture splits in two halves that slide apart", {"orientation": ["Horizontal", "Vertical"]}),
    "stretch": T("next picture stretches in from one edge", {"direction": DIRS}),
    "whip": T("fast whip-pan with heavy motion blur", {"direction": DIRS, "blur": (40, 100)}, main="blur"),
    # Smart Tools
    "motion_camera": T("virtual camera zooms and rotates between the two pictures", {"zoom": (10, 120), "rotation": (-90, 90)}, main="zoom"),
    "motion_tween": T("gentle scale tween that blends the pictures", {"scale": (5, 50)}, main="scale"),
    "shape_dissolve": T("dissolve through many small shapes (circles, stars, hearts...)",
                        {"shape": ["Circle", "Square", "Diamond", "Star", "Heart", "Triangle"], "size": (40, 300), "order": ["Random", "Left to Right", "Center Out"]}, main="size"),
    "shape_flow": T("one big shape (circle, star, heart...) grows to reveal the next picture",
                    {"shape": ["Circle", "Square", "Diamond", "Star", "Heart", "Triangle"], "direction": DIRS}),
    # Transformers
    "spin_3d": T("picture spins in 3D around its axis, revealing the next on the back", {"direction": DIRS}),
    "spinback_3d": T("picture swings back into depth and the next swings forward", {"direction": DIRS, "depth": (20, 90)}, main="depth"),
    "frame": T("pictures shrink into a white-bordered frame and swap", {"frame_width": (8, 60), "frame_color": "color", "scale": (40, 85)}, main="frame_width"),
    "louver": T("horizontal blinds (louvers) flip open to the next picture", {"slats": (4, 24), "orientation": ["Horizontal", "Vertical"]}, main="slats"),
    "mirror_transition": T("mirrored split that folds into the next picture", {"direction": DIRS}),
    "page_peel": T("the corner peels like paper to reveal the next picture", {"corner": ["Top Left", "Top Right", "Bottom Right", "Bottom Left"], "radius": (30, 200)}, main="radius"),
    "slice": T("diagonal slices slide in different directions", {"slices": (3, 20), "angle": (0, 180)}, main="slices"),
    "wave": T("a wave ripples through and carries the next picture in", {"direction": DIRS, "amplitude": (20, 200)}, main="amplitude"),
    # Wipe
    "clock_wipe": T("clock-hand sweep reveals the next picture", {"feather": (0, 80)}),
    "linear_wipe": T("straight wipe line moves across", {"angle": (0, 360), "feather": (0, 200)}, main="feather"),
    "neon_wipe": T("glowing neon line wipes across", {"angle": (0, 360), "color": "color", "glow": (10, 120)}, main="glow"),
    "panel_wipe": T("staggered panels wipe in like a blocky curtain", {"direction": DIRS, "panels": (2, 16)}, main="panels"),
    "plateau_wipe": T("stepped plateau-shaped wipe", {"angle": (0, 360), "plateaus": (2, 12)}, main="plateaus"),
    "radial_wipe": T("radial wipe sweeping from a corner", {"corner": ["Top Left", "Top Right", "Bottom Right", "Bottom Left"], "feather": (0, 80)}),
    "soft_wipe": T("very soft gradient wipe, almost a directional dissolve", {"angle": (0, 360), "feather": (100, 800)}, main="feather"),
    "star_wipe": T("growing star shape reveals the next picture (cheesy on purpose)", {"points": (4, 10), "border_width": (0, 20), "border_color": "color"}, main="points"),
    "stretch_wipe": T("picture stretches and smears out of frame", {"direction": DIRS, "stretch": (60, 600)}, main="stretch"),
    # Classic folder
    "barn_doors": T("barn doors open from the middle", {"orientation": ["Horizontal", "Vertical"]}),
    "center_split": T("picture splits into four quarters that slide to the corners"),
    "inset": T("next picture grows from a corner as a rectangle", {"corner": ["Top Left", "Top Right", "Bottom Right", "Bottom Left"]}),
    "iris_box": T("rectangle iris opens from the centre"),
    "iris_cross": T("cross-shaped iris opens from the centre"),
    "iris_diamond": T("diamond iris opens from the centre"),
    "iris_round": T("round iris opens from the centre (old cinema)"),
    "wipe": T("plain hard-edged wipe", {"direction": DIRS}),
    "band_slide": T("horizontal bands slide in from alternating sides"),
    "checker_wipe": T("checkerboard of small cells wipes across"),
    "cube_spin": T("3D cube rotation from one face to the next"),
    "flip_over": T("picture flips over in 3D, black behind"),
    "gradient_wipe": T("soft diagonal gradient wipe", {"softness": (0, 60)}, main="softness"),
    "page_turn": T("page turns from the corner like a book"),
    "venetian_blinds": T("venetian blinds close and reopen on the next picture"),
}
TRANSITIONS_EXCLUDED = {
    "morph_cut": "meant for talking-head jump cuts; on unrelated pictures it is just a muddy dissolve",
    "text_animator": "text-clip transition (works on text graphics, not pictures)",
    "typewriter": "text-clip transition (works on text graphics, not pictures)",
    "vr_chroma_leaks": "VR duplicate of chroma_leak", "vr_gradient_wipe": "VR duplicate of gradient_wipe",
    "vr_iris_wipe": "VR duplicate of iris_round", "vr_light_leaks": "VR duplicate of light_leak", "vr_spherical_blur": "VR duplicate of blur_dissolve",
    "additive_dissolve_legacy": "legacy duplicate", "clock_wipe_legacy": "legacy duplicate", "cross_dissolve_legacy": "legacy duplicate",
    "cross_zoom_legacy": "legacy duplicate", "dip_to_black_legacy": "legacy duplicate", "dip_to_white_legacy": "legacy duplicate",
    "film_dissolve_legacy": "legacy duplicate", "push_legacy": "legacy duplicate", "radial_wipe_legacy": "legacy duplicate",
    "slide_legacy": "legacy duplicate", "split_legacy": "legacy duplicate", "whip_legacy": "legacy duplicate",
}

# ---------------------------------------------------------------- video effects
FX = {
    # Blur & Sharpen
    "gaussian_blur": T("soft blur over the whole picture; animate it from high to 0 for a focus pull", {"blurriness": (0, 60)}, {"blurriness": 20}, "blurriness"),
    "directional_blur": T("motion-blur smear in one direction (speed feeling)", {"direction": (0, 180), "length": (20, 160)}, {"direction": 90, "length": 60}, "length"),
    "sharpen": T("crisper edges and texture", {"amount": (0, 80)}, {"amount": 40}, "amount"),
    "camera_blur": T("out-of-focus camera lens blur", {"percent": (10, 70)}, {"percent": 30}, "percent"),
    "bokeh_blur": T("dreamy defocus with round bokeh highlights", {"amount": (4, 40), "shape": ["Circle", "Hexagon", "Octagon"]}, {"amount": 14}, "amount"),
    "focus_blur": T("tilt-shift miniature: sharp band in the middle, blurred top and bottom",
                    {"shape": ["Linear", "Radial"], "size": (150, 900), "amount": (15, 80)}, {"shape": "Linear", "center": [540, 960], "size": 350, "feather": 250, "amount": 55}, "amount"),
    # Color / image control
    "black_white": T("plain black-and-white"),
    "color_pass": T("keeps one colour, everything else goes grey (Sin City look)", {"color": "color", "similarity": (15, 40)}, {"color": "#e03030", "similarity": 25}, "similarity"),
    "invert": T("photo negative", {"blend": (0, 80)}, {}, "blend"),
    "tint": T("duotone: darks and lights mapped to two colours", {"black": "color", "white": "color", "amount": (50, 100)},
              {"black": "#1b1340", "white": "#ffcf6e", "amount": 85}, "amount"),
    "vignette": T("darkened corners that pull the eye to the centre (positive amount = white vignette)",
                  {"amount": (-80, 60), "midpoint": (20, 80), "feather": (30, 90)}, {"amount": -55}, "amount"),
    "posterize": T("flat poster colours, fewer tones", {"levels": (3, 16)}, {"levels": 6}, "levels"),
    # Stylize
    "mosaic": T("pixelate into big square blocks (8-bit / censorship)", {"horizontal": (10, 80)}, {"horizontal": 30, "sharp": True}, "horizontal"),
    "find_edges": T("line-art sketch: only the edges stay", {"blend": (0, 70), "invert": "bool"}, {"blend": 35}, "blend"),
    "strobe": T("stroboscope: the picture flashes a colour at a fixed period", {"color": "color", "duration": (0.03, 0.15), "period": (0.15, 1.0)},
                {"color": "#ffffff", "duration": 0.05, "period": 0.4}, "period"),
    "noise": T("film grain / video noise", {"amount": (5, 45), "grain_size": (1, 4), "color": "bool"}, {"amount": 18}, "amount"),
    "brush_strokes": T("painterly brush strokes, like an oil painting", {"size": (2, 5), "length": (8, 30)}, {"size": 3, "length": 18, "density": 2}, "length"),
    "color_emboss": T("embossed relief with colours kept, like a metal stamp", {"relief": (1, 8), "blend": (0, 70)}, {"relief": 4}, "relief"),
    "posterize_time": T("choppy stop-motion: fewer frames per second", {"rate": (4, 15)}, {"rate": 8}, "rate"),
    "echo": T("motion trails: earlier frames ghost behind moving things", {"time": (-0.2, -0.02), "count": (1, 6)}, {"time": -0.06, "count": 3}, "count"),
    # Lights & Glows
    "lens_flare": T("bright lens flare at a point (sun, lamp, magic)", {"center": "point", "brightness": (60, 180), "size": (50, 200),
                    "lens_type": ["50-300mm Zoom", "35mm Prime", "105mm Prime", "Anamorphic"]}, {"center": [0.3, 0.2], "brightness": 140}, "brightness"),
    "echo_glow": T("layered bloom echoes around bright areas", {"threshold": (40, 85), "echoes": (2, 6), "intensity": (50, 250)}, {"threshold": 60, "intensity": 120}, "intensity"),
    "edge_glow": T("neon outline glowing along edges", {"threshold": (10, 50), "width": (1, 6), "intensity": (80, 400), "color": "color"},
                   {"intensity": 200, "color": "#3fd8ff"}, "intensity"),
    "glint": T("star sparkles on the brightest highlights", {"threshold": (55, 92), "length": (30, 220), "rays": ["4", "6", "8"]}, {"threshold": 75, "length": 90}, "length"),
    "light_leaks": T("drifting warm film light leaks", {"c1": "color", "c2": "color", "intensity": (20, 80), "speed": (0.3, 3)}, {"intensity": 45}, "intensity"),
    "rgb_split": T("chromatic aberration: red/blue channels shifted apart", {"amount": (3, 40), "mode": ["Linear", "Radial"]}, {"amount": 10}, "amount"),
    "volumetric_rays": T("god rays streaming from the bright parts", {"center": "point", "threshold": (40, 85), "length": (20, 80), "intensity": (50, 220)},
                         {"center": [0.5, 0.2], "intensity": 120}, "intensity"),
    "wonder_glow": T("soft bloom glow around highlights", {"threshold": (30, 80), "radius": (10, 80), "intensity": (60, 400)}, {"threshold": 45, "intensity": 220}, "intensity"),
    # Distort
    "mirror": T("mirror the picture along a line through the centre (symmetry)", {"angle": (0, 180)}, {"center": [0.5, 0.5], "angle": 90}, "angle"),
    "lens_distortion": T("fisheye bulge (negative) or pinch (positive) lens, with black rounded edges like an old CRT", {"curvature": (-60, 40)}, {"curvature": -35}, "curvature"),
    "twirl": T("swirl around the centre", {"angle": (-240, 240), "radius": (10, 70)}, {"angle": 120, "radius": 40}, "angle"),
    "wave_warp": T("wavy water-like distortion that moves", {"height": (4, 40), "width": (40, 300), "speed": (0, 3)}, {"height": 14, "width": 140, "speed": 1}, "height"),
    "magnify": T("magnifying glass circle over a spot", {"center": "point", "magnification": (130, 260), "size": (150, 480)},
                 {"center": [0.5, 0.5], "magnification": 180, "size": 300}, "magnification"),
    "spherize": T("spherical bulge of the centre", {"center": "point", "radius": (200, 900)}, {"center": [0.5, 0.5], "radius": 500}, "radius"),
    "turbulent_displace": T("heat-haze wobble / dream distortion", {"displacement": ["Turbulent", "Bulge", "Twist", "Turbulent Smoother"], "amount": (10, 90), "size": (50, 300)},
                            {"amount": 35, "size": 120}, "amount"),
    "rotate_3d": T("picture tilted in 3D space like a card", {"rot_x": (-40, 40), "rot_y": (-40, 40), "rot_z": (-20, 20)}, {"rot_y": 22, "rot_x": 8}, "rot_y"),
    # Transform / framing
    "crop": T("cinematic letterbox: black bars top/bottom (or sides)", {"top": (0, 25), "bottom": (0, 25), "left": (0, 25), "right": (0, 25)},
              {"top": 12, "bottom": 12}, "top"),
    "rounded_crop": T("picture inset as a rounded card with a border", {"left": (2, 15), "top": (2, 15), "right": (2, 15), "bottom": (2, 15), "radius": (20, 140),
                      "border": (0, 20), "border_color": "color"}, {"left": 6, "right": 6, "top": 8, "bottom": 8, "radius": 60, "border": 8, "border_color": "#ffffff"}, "radius"),
    "edge_feather": T("soft dark fade around the frame edges", {"amount": (5, 40)}, {"amount": 15}, "amount"),
    "horizontal_flip": T("mirror the picture left-right"),
    "vertical_flip": T("upside-down picture"),
    "transform": T("skew / rotate the picture (slanted, off-kilter), zoomed so no edges show", {"skew": (-10, 10), "rotation": (-10, 10)},
                   {"skew": 6, "scale_width": 135, "scale_height": 135}, "skew"),
    "clone": T("grid of N x N copies of the picture (pop-art)", {"columns": (2, 4), "gap": (0, 20), "mirror": "bool"}, {"columns": 2, "gap": 6}, "columns"),
    "camera_shake": T("handheld camera shake", {"amount": (5, 70), "rotation": (0, 5), "frequency": (1, 12)}, {"amount": 20}, "amount"),
    "wiggle": T("random jittery wiggle of position", {"frequency": (1, 12), "amount": (5, 80), "rotation": (0, 8)}, {"frequency": 4, "amount": 20}, "amount"),
    # Generate (overlays)
    "lightning": T("electric lightning bolt across the frame", {"start": "point", "end": "point", "width": (4, 30), "amplitude": (5, 30)},
                   {"start": [0.5, 0.0], "end": [0.45, 0.6], "width": 10}, "amplitude"),
    "block_dissolve": T("picture breaks into missing blocks (animate [0, 70] to crumble it away)", {"completion": (0, 70), "block_w": (20, 120), "block_h": (20, 120)},
                        {"completion": 30, "block_w": 60, "block_h": 60}, "completion"),
    "vr_digital_glitch": T("animated digital glitch: block displacement, colour channels, scanlines",
                           {"amplitude": (10, 80), "scanlines": (0, 60), "color": (0, 100)}, {"amplitude": 30}, "amplitude"),
}
FX_EXCLUDED = {
    "motion": "use `camera`", "opacity": "handled by the harness", "time_remap": "use `speed`",
    "lumetri": "use `grade`", "brightness_contrast": "covered by `grade`", "proc_amp": "covered by `grade`", "levels": "covered by `grade`",
    "gamma_correction": "covered by `grade`", "asc_cdl": "covered by `grade`", "channel_mix": "technical colour matrix",
    "color_balance": "obsolete, covered by `grade`", "three_way_color": "obsolete, covered by `grade`", "leave_color": "obsolete duplicate of color_pass",
    "change_to_color": "obsolete, needs exact source colour", "color_replace": "needs exact source colour", "extract": "technical luma key",
    "unsharp_mask": "duplicate of sharpen", "emboss": "obsolete duplicate of color_emboss", "median": "obsolete smoothing",
    "replicate": "duplicate of clone", "offset": "use `camera`", "basic_3d": "duplicate of rotate_3d", "corner_pin": "needs four exact corner points",
    "warp_stabilizer": "for shaky footage, not pictures", "reduce_interlace_flicker": "technical (interlacing)", "video_limiter": "technical broadcast limiter",
    "cineon_converter": "technical log conversion", "auto_reframe": "technical reframing (pictures are already vertical)", "auto_align": "layout utility",
    "spacer": "layout utility", "spin": "rotating a vertical frame shows black corners unless zoomed 2x (use spin transitions)",
    "four_color_gradient": "covers the picture completely (opacity does not blend)", "grow": "use `camera`", "shrink": "use `camera`", "move": "use `camera`",
    "channel_blur": "technical per-channel blur", "compound_blur": "needs a blur-map track", "drop_shadow": "needs transparency (pictures are opaque)",
    "long_shadow": "needs transparency", "bevel_alpha": "needs transparency", "alpha_glow": "needs transparency", "stroke": "needs transparency",
    "roughen_edges": "needs transparency", "ultra_key": "green-screen keying", "track_matte": "matte compositing", "color_key": "keying",
    "luma_key": "keying", "alpha_adjust": "alpha utility", "logo_cutout": "keying", "ramp": "generator that replaces the picture",
    "gradient": "generator that replaces the picture", "circle": "obsolete generator", "grid": "obsolete generator", "checkerboard": "obsolete generator",
    "ellipse": "obsolete generator", "cell_pattern": "obsolete generator", "paint_bucket": "obsolete fill", "write_on": "obsolete paint stroke",
    "lighting_effects": "too many parameters for one line", "timecode": "timecode burn-in", "clip_name": "clip name burn-in",
    "metadata_burnin": "metadata/timecode burn-in", "simple_text": "captions are separate", "graphic_text": "captions are separate",
    "graphic_shape": "graphics layer, not an effect", "directional_blur_legacy": "legacy duplicate", "gaussian_blur_legacy": "legacy duplicate",
    "gradient_wipe_legacy": "legacy, use transitions", "linear_wipe_legacy": "legacy, use transitions", "magnify_legacy": "legacy duplicate",
    "mosaic_legacy": "legacy duplicate", "noise_legacy": "legacy duplicate", "twirl_legacy": "legacy duplicate",
    "vr_blur": "VR projection", "vr_chromatic_aberrations": "VR projection (use rgb_split)", "vr_color_gradients": "VR projection",
    "vr_denoise": "VR projection", "vr_fractal_noise": "VR projection", "vr_glow": "VR projection (use wonder_glow)",
    "vr_plane_to_sphere": "VR projection", "vr_projection": "VR projection", "vr_rotate_sphere": "VR projection", "vr_sharpen": "VR projection",
}


def number(default):
    if isinstance(default, dict):
        default = next(iter(default.values()), None)
    return default


def merge(engine, notes, excluded, kind):
    out, missing = [], []
    for e in engine:
        eid = e["id"]
        info = {p["id"]: p for p in e.get("paramInfo", [])}
        row = {"id": eid, "name": e["name"], "category": e.get("folder") or "Other"}
        if eid in excluded:
            row["excluded"] = excluded[eid]
        elif eid not in notes:
            missing.append(eid)
            continue
        else:
            n = notes[eid]
            row.update(desc=n["desc"], main=n["main"], preset=n["preset"], params={})
            for pid, spec in n["params"].items():
                p = info.get(pid)
                if p is None:
                    raise SystemExit(f"{kind} {eid}: engine has no param '{pid}' ({list(info)})")
                t = p["type"]
                if isinstance(spec, tuple):
                    lo, hi = spec
                    if t in ("float", "int"):
                        lo, hi = max(lo, p.get("min", lo)), min(hi, p.get("max", hi))
                    elif t != "angle":
                        raise SystemExit(f"{kind} {eid}.{pid}: range given for a {t}")
                    row["params"][pid] = {"type": "number", "min": lo, "max": hi, "default": number(p.get("default"))}
                elif isinstance(spec, list):
                    bad = [o for o in spec if o not in p.get("options", [])]
                    if t != "choice" or bad:
                        raise SystemExit(f"{kind} {eid}.{pid}: options {bad} not in {p.get('options')}")
                    row["params"][pid] = {"type": "choice", "options": spec}
                elif spec in ("color", "bool", "point"):
                    if t != spec:
                        raise SystemExit(f"{kind} {eid}.{pid}: engine type is {t}, notes say {spec}")
                    row["params"][pid] = {"type": spec}
                else:
                    raise SystemExit(f"{kind} {eid}.{pid}: bad spec {spec!r}")
                row["params"][pid]["animatable"] = bool(p.get("animatable"))
            for pid in n["preset"]:
                if pid not in info:
                    raise SystemExit(f"{kind} {eid}: preset param '{pid}' unknown")
            if n["main"] and n["main"] not in row["params"]:
                raise SystemExit(f"{kind} {eid}: main '{n['main']}' is not an exposed param")
        out.append(row)
    unknown = (set(notes) | set(excluded)) - {e["id"] for e in engine}
    if missing or unknown:
        raise SystemExit(f"{kind}: engine ids without notes {missing}; notes for ids the engine lacks {sorted(unknown)}")
    return out


def main():
    fc = MCP([FILMCRAFT_CLI, "mcp"])
    try:
        transitions = fc.run("effects.list", {"kind": "VideoTransition", "detail": True})
        effects = fc.run("effects.list", {"kind": "Video", "detail": True})
        lumetri = next(e for e in effects if e["id"] == "lumetri")
    finally:
        fc.close()
    ec = MCP([EFFECTCRAFT_CLI, "mcp"])
    try:
        ec_effects = ec.call("list_effects", {"compact": True})
    finally:
        ec.close()
    looks = next(p for p in lumetri["paramInfo"] if p["id"] == "look")["options"]
    data = {
        "engines": {"filmcraft": FILMCRAFT_CLI.parent.parent.name, "effectcraft": EFFECTCRAFT_CLI.parent.parent.name},
        "transitions": merge(transitions, TRANSITIONS, TRANSITIONS_EXCLUDED, "transition"),
        "effects": merge(effects, FX, FX_EXCLUDED, "effect"),
        "lumetri_looks": looks,
        "effectcraft_effects": [{"id": e["id"], "name": e["name"], "category": e["category"]} for e in ec_effects],
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    n = lambda rows: (sum("excluded" not in r for r in rows), len(rows))  # noqa: E731
    print(f"wrote {OUT}: transitions {n(data['transitions'])}, effects {n(data['effects'])} (exposed, total); "
          f"lumetri looks {len(looks)}; EffectCraft effects {len(ec_effects)}")


if __name__ == "__main__":
    main()
