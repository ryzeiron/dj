"""Beat synced movement and intensity effects.

An effect receives the list of fixture states for the current frame and edits
them in place. Everything is derived from the beat counter, so a whole rig
stays in phase and follows the tempo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .fixtures import FixtureState

TAU = math.pi * 2


@dataclass
class EffectContext:
    beats: float                     # continuous beat position
    bpm: float = 128.0
    length: float = 4.0              # beats for one full cycle
    size: float = 1.0                # 0..1 amplitude
    spread: float = 1.0              # 0..1 phase spread across the rig
    params: dict = field(default_factory=dict)

    def phase(self, index: int, count: int) -> float:
        """Cycle position for one fixture, in turns (0..1)."""
        offset = 0.0
        if count > 1:
            offset = self.spread * index / count
        return (self.beats / max(0.25, self.length)) + offset


def _amp(ctx: EffectContext) -> float:
    return max(0.0, min(1.0, ctx.size)) * 0.5


def _hash01(*values: int) -> float:
    """Deterministic pseudo random in 0..1 — same frame gives the same look."""
    seed = 0
    for value in values:
        seed = (seed * 1103515245 + int(value) + 12345) & 0x7FFFFFFF
    return ((seed >> 8) % 10000) / 10000.0


# --------------------------------------------------------------------------
# effect implementations
# --------------------------------------------------------------------------
def _static(states, ctx):
    return


def _sweep(states, ctx):
    amp = _amp(ctx)
    for i, state in enumerate(states):
        state.pan = state.pan + amp * math.sin(TAU * ctx.phase(i, len(states)))


def _nod(states, ctx):
    amp = _amp(ctx)
    for i, state in enumerate(states):
        state.tilt = state.tilt + amp * math.sin(TAU * ctx.phase(i, len(states)))


def _circle(states, ctx):
    amp = _amp(ctx)
    for i, state in enumerate(states):
        theta = TAU * ctx.phase(i, len(states))
        state.pan = state.pan + amp * math.sin(theta)
        state.tilt = state.tilt + amp * 0.6 * math.cos(theta)


def _figure8(states, ctx):
    amp = _amp(ctx)
    for i, state in enumerate(states):
        theta = TAU * ctx.phase(i, len(states))
        state.pan = state.pan + amp * math.sin(theta)
        state.tilt = state.tilt + amp * 0.5 * math.sin(2 * theta)


def _fan(states, ctx):
    """Static spread: heads open like a fan around the look's centre."""
    count = len(states)
    amp = _amp(ctx)
    for i, state in enumerate(states):
        position = 0.0 if count == 1 else (i / (count - 1)) - 0.5
        state.pan = state.pan + 2 * amp * position


def _cross(states, ctx):
    """Neighbouring heads sweep in opposite directions."""
    amp = _amp(ctx)
    for i, state in enumerate(states):
        direction = 1 if i % 2 == 0 else -1
        state.pan = state.pan + direction * amp * math.sin(TAU * ctx.beats / max(0.25, ctx.length))


def _chase(states, ctx):
    """One head lit at a time, stepping every `length` beats."""
    count = len(states)
    step = int(ctx.beats / max(0.25, ctx.length))
    for i, state in enumerate(states):
        state.dimmer = state.dimmer if i == step % count else 0.0


def _pulse(states, ctx):
    """Intensity decay on every cycle — the classic on-beat punch."""
    for i, state in enumerate(states):
        frac = ctx.phase(i, len(states)) % 1.0
        envelope = (1.0 - frac) ** 2
        state.dimmer = state.dimmer * (1.0 - ctx.size + ctx.size * envelope)


def _wave(states, ctx):
    """Sine wave of intensity travelling along the rig."""
    for i, state in enumerate(states):
        value = 0.5 + 0.5 * math.sin(TAU * ctx.phase(i, len(states)))
        state.dimmer = state.dimmer * (1.0 - ctx.size + ctx.size * value)


def _strobe_beat(states, ctx):
    """Short burst of strobe at the start of every cycle."""
    duty = float(ctx.params.get("duty", 0.25))
    rate = float(ctx.params.get("rate", 15.0))
    for i, state in enumerate(states):
        if (ctx.phase(i, len(states)) % 1.0) < duty:
            state.strobe = rate
        else:
            state.strobe = 0.0


def _blinder(states, ctx):
    """Everything full on, on the beat, off in between."""
    duty = float(ctx.params.get("duty", 0.3))
    on = (ctx.beats / max(0.25, ctx.length)) % 1.0 < duty
    for state in states:
        state.dimmer = 1.0 if on else 0.0


def sample_path(points: list, t: float) -> tuple[float, float]:
    """Position at 0..1 along a closed curve passing through `points`.

    Catmull-Rom, so a handful of dropped points give a smooth loop instead of a
    polygon with corners. Mirrored in the browser to draw the same curve.
    """
    count = len(points)
    if count == 0:
        return 0.5, 0.5
    if count == 1:
        return points[0][0], points[0][1]
    position = (t % 1.0) * count
    index = int(position)
    frac = position - index

    def point(i):
        return points[i % count]

    p0, p1, p2, p3 = point(index - 1), point(index), point(index + 1), point(index + 2)

    def axis(a, b, c, d):
        return 0.5 * ((2 * b) + (-a + c) * frac
                      + (2 * a - 5 * b + 4 * c - d) * frac ** 2
                      + (-a + 3 * b - 3 * c + d) * frac ** 3)

    return axis(p0[0], p1[0], p2[0], p3[0]), axis(p0[1], p1[1], p2[1], p3[1])


def _path(states, ctx):
    """Follow the curve the user drew on the preview, in time with the beat."""
    points = [p for p in (ctx.params.get("path") or []) if len(p) >= 2]
    if len(points) < 2:
        return
    centre_x = sum(p[0] for p in points) / len(points)
    centre_y = sum(p[1] for p in points) / len(points)
    scale = max(0.0, min(1.0, ctx.size)) * 2      # size 0.5 = trace exact
    for i, state in enumerate(states):
        x, y = sample_path(points, ctx.phase(i, len(states)))
        state.pan = centre_x + (x - centre_x) * scale
        state.tilt = centre_y + (y - centre_y) * scale


def _random_pos(states, ctx):
    """New random position for each head at every step."""
    amp = _amp(ctx)
    step = int(ctx.beats / max(0.25, ctx.length))
    for i, state in enumerate(states):
        state.pan = state.pan + 2 * amp * (_hash01(step, i, 7) - 0.5)
        state.tilt = state.tilt + amp * (_hash01(step, i, 91) - 0.5)


EFFECTS: dict[str, dict] = {
    "none": {"label": "Statique", "fn": _static, "kind": "position"},
    "sweep": {"label": "Balayage", "fn": _sweep, "kind": "position"},
    "nod": {"label": "Haut / bas", "fn": _nod, "kind": "position"},
    "circle": {"label": "Cercle", "fn": _circle, "kind": "position"},
    "figure8": {"label": "Huit", "fn": _figure8, "kind": "position"},
    "fan": {"label": "Eventail", "fn": _fan, "kind": "position"},
    "cross": {"label": "Croisement", "fn": _cross, "kind": "position"},
    "random_pos": {"label": "Positions aleatoires", "fn": _random_pos, "kind": "position"},
    "path": {"label": "Trace perso", "fn": _path, "kind": "position"},
    "chase": {"label": "Chenillard", "fn": _chase, "kind": "intensity"},
    "pulse": {"label": "Pulsation", "fn": _pulse, "kind": "intensity"},
    "wave": {"label": "Vague", "fn": _wave, "kind": "intensity"},
    "blinder": {"label": "Blinder", "fn": _blinder, "kind": "intensity"},
    "strobe_beat": {"label": "Strobe rythme", "fn": _strobe_beat, "kind": "intensity"},
}


def apply_effect(name: str, states: list[FixtureState], ctx: EffectContext) -> None:
    effect = EFFECTS.get(name or "none")
    if effect is None:
        return
    effect["fn"](states, ctx)
    for state in states:
        state.pan = max(0.0, min(1.0, state.pan))
        state.tilt = max(0.0, min(1.0, state.tilt))
        state.dimmer = max(0.0, min(1.0, state.dimmer))


def list_effects() -> list[dict]:
    return [
        {"id": key, "label": value["label"], "kind": value["kind"]}
        for key, value in EFFECTS.items()
    ]
