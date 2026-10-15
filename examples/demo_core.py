"""Run with: python examples/demo_core.py"""

import json

import numpy as np

from manim_lace import LaceEngine
from manim_lace.animation import build_animation_plan, trace_to_jsonable

paths = [
    np.array([[-3.0, -1.0], [3.0, 1.0]]),
    np.array([[-3.0, 1.0], [3.0, -1.0]]),
    np.array([[-3.0, -0.5], [3.0, -0.5]]),
]
result = LaceEngine(paths, offset=0.12, weave_mode="free").solve()
plan = build_animation_plan(result, mode="algorithm")

print(f"paths={len(result.paths)} crossings={len(result.crossings)} pieces={len(result.pieces)}")
print("animation stages:", plan.stage_names())
print("diagnostics:", [d.code for d in result.diagnostics])
with open("trace.json", "w", encoding="utf-8") as file:
    json.dump(trace_to_jsonable(result.trace), file, ensure_ascii=False, indent=2)
print("wrote trace.json")
