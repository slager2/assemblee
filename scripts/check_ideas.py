#!/usr/bin/env python3
"""Validate assemblee/ideas.py against the rich vocabulary (vocab.py + EDL validator). Exit 1 on any problem.

usage: python3 scripts/check_ideas.py [-v]   (-v also prints ideas_prompt() and hook_ideas())
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assemblee import ideas  # noqa: E402

probs = ideas.validate()
n_steps = sum(len(r["structure"]) for r in ideas.RECIPES)
used = {"transitions": set(), "effects": set(), "text_anims": set()}
for r in ideas.RECIPES:
    for st in r["structure"]:
        if st.get("transition_out", "cut") != "cut":
            used["transitions"].add(st["transition_out"])
        used["effects"].update(fx["id"] if isinstance(fx, dict) else fx for fx in st.get("effects", []))
        if st.get("text_anim"):
            used["text_anims"].add(st["text_anim"])
print(f"{len(ideas.RECIPES)} recipes, {n_steps} steps, {len(ideas.HOOKS)} hooks, {len(set(ideas.S.values()))} sources; "
      + ", ".join(f"{k} used: {len(v)}" for k, v in used.items()))
for mood, ids in ideas.moods().items():
    print(f"  {mood}: {len(ids)}")
for text, name in [(ideas.ideas_prompt(12, seed=1), "ideas_prompt"), (ideas.hook_ideas(), "hook_ideas")]:
    print(f"{name}: {len(text)} chars")
    if "-v" in sys.argv:
        print(text)
if ideas.ideas_prompt(12, seed=7, mood="dark") != ideas.ideas_prompt(12, seed=7, mood="dark"):
    probs.append("ideas_prompt is not deterministic for a fixed seed")
shots, sfx = ideas.to_shots("loop_ending", ["a", "b"])
if shots[0]["asset"] != shots[2]["asset"]:
    probs.append("to_shots: same_as not honoured")
if probs:
    print("PROBLEMS:\n  " + "\n  ".join(probs))
    sys.exit(1)
print("OK")
