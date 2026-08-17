"""Fixture profiles and the state -> DMX conversion.

A profile describes one lamp in one DMX mode. Channel numbers inside a profile
are relative to the fixture start address (1 = first channel of the fixture),
exactly like the tables printed in the manuals.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict

from .dmx import Universe

PROFILE_DIR = os.path.join(os.path.dirname(__file__), "profiles")

#: Named colours, used by RGB fixtures and by the UI swatches. Colour wheels
#: use their own slot table; this maps the same names to light.
COLOR_RGB: dict[str, tuple[int, int, int]] = {
    "blanc": (255, 255, 255),
    "rouge": (255, 0, 0),
    "vert": (0, 255, 0),
    "bleu": (0, 40, 255),
    "jaune": (255, 190, 0),
    "orange": (255, 80, 0),
    "cyan": (0, 220, 255),
    "rose": (255, 0, 140),
    "violet": (140, 0, 255),
    "arc-en-ciel": (255, 255, 255),
}


@dataclass
class FixtureState:
    """What a lamp should be doing, in human units. The engine works on these."""

    pan: float = 0.5        # 0..1 over the head's full pan range
    tilt: float = 0.5       # 0..1 over the head's full tilt range
    dimmer: float = 1.0     # 0..1
    strobe: float = 0.0     # flashes per second, 0 = shutter simply open
    color: str = "white"
    gobo: str = "open"
    prism: bool = False
    prism_rot: float = 0.0  # 0..1
    focus: float = 0.5      # 0..1
    speed: float = 0.0      # 0 = fastest movement, 1 = slowest

    def copy(self) -> "FixtureState":
        return FixtureState(**asdict(self))


class Profile:
    def __init__(self, data: dict) -> None:
        self.id: str = data["id"]
        self.name: str = data.get("name", self.id)
        self.footprint: int = int(data.get("footprint", 1))
        self.data = data

    # -- lookups -----------------------------------------------------------
    def block(self, key: str) -> dict | None:
        value = self.data.get(key)
        return value if isinstance(value, dict) else None

    @property
    def colors(self) -> list[str]:
        block = self.block("color")
        return list(block.get("slots", {})) if block else []

    @property
    def gobos(self) -> list[str]:
        block = self.block("gobo")
        return list(block.get("slots", {})) if block else []

    def channel_names(self) -> list[str]:
        """Human readable list, one entry per channel of the mode."""
        names = [f"canal {i + 1}" for i in range(self.footprint)]
        for key, block in self.data.items():
            if not isinstance(block, dict):
                continue
            for sub in ("channel", "coarse", "fine"):
                chan = block.get(sub)
                if isinstance(chan, int) and 1 <= chan <= self.footprint:
                    label = key if sub == "channel" else f"{key} ({sub})"
                    names[chan - 1] = label
        return names

    # -- rendering ---------------------------------------------------------
    def render(self, state: FixtureState, address: int, universe: Universe) -> None:
        """Write one fixture's state into the universe at `address`."""
        def put(channel: int | None, value: float) -> None:
            if channel:
                universe.set(address + channel - 1, round(value))

        pan = self.block("pan")
        if pan:
            self._render_axis(pan, state.pan, address, universe)
        tilt = self.block("tilt")
        if tilt:
            self._render_axis(tilt, state.tilt, address, universe)

        speed = self.block("speed")
        if speed:
            value = state.speed * 255
            if speed.get("invert"):
                value = 255 - value
            put(speed.get("channel"), value)

        dimmer = self.block("dimmer")
        if dimmer:
            lo, hi = dimmer.get("min", 0), dimmer.get("max", 255)
            put(dimmer.get("channel"), lo + state.dimmer * (hi - lo))

        shutter = self.block("shutter")
        if shutter:
            if state.dimmer <= 0.0 and shutter.get("closed") is not None:
                value = shutter["closed"]
            elif state.strobe > 0:
                lo = shutter.get("strobe_min", 0)
                hi = shutter.get("strobe_max", 255)
                rate = max(0.0, min(1.0, state.strobe / shutter.get("strobe_hz_max", 20)))
                value = lo + rate * (hi - lo)
            else:
                value = shutter.get("open", 255)
            put(shutter.get("channel"), value)

        self._render_wheel(self.block("color"), state.color, address, universe)
        self._render_wheel(self.block("gobo"), state.gobo, address, universe)

        rgb = self.block("rgb")
        if rgb:
            red, green, blue = COLOR_RGB.get(state.color, (255, 255, 255))
            level = 0.0 if state.dimmer <= 0 else state.dimmer
            if not dimmer:  # no dedicated dimmer channel: scale the colour
                red, green, blue = (c * level for c in (red, green, blue))
            put(rgb.get("r"), red)
            put(rgb.get("g"), green)
            put(rgb.get("b"), blue)
            white = min(red, green, blue) if state.color == "blanc" else 0
            put(rgb.get("w"), white)

        prism = self.block("prism")
        if prism:
            put(prism.get("channel"), prism["on"] if state.prism else prism.get("off", 0))
        prism_rot = self.block("prism_rot")
        if prism_rot:
            put(prism_rot.get("channel"), state.prism_rot * 255)
        focus = self.block("focus")
        if focus:
            put(focus.get("channel"), state.focus * 255)

    def _render_axis(self, block: dict, value: float, address: int,
                     universe: Universe) -> None:
        value = max(0.0, min(1.0, value))
        lo = block.get("min", 0) / 255.0
        hi = block.get("max", 255) / 255.0
        value = lo + value * (hi - lo)
        if block.get("invert"):
            value = 1.0 - value
        coarse = block.get("coarse") or block.get("channel")
        if not coarse:
            return
        fine = block.get("fine")
        if fine:
            universe.set16(address + coarse - 1, round(value * 65535))
            if fine != coarse + 1:  # non contiguous fine channel
                universe.set(address + fine - 1, round(value * 65535) & 0xFF)
        else:
            universe.set(address + coarse - 1, round(value * 255))

    def _render_wheel(self, block: dict | None, slot: str, address: int,
                      universe: Universe) -> None:
        if not block or not block.get("channel"):
            return
        slots: dict = block.get("slots", {})
        if slot in slots:
            value = slots[slot]
        elif slots:
            value = next(iter(slots.values()))
        else:
            value = 0
        universe.set(address + block["channel"] - 1, value)


@dataclass
class Fixture:
    """A patched lamp: a profile at a DMX address, with a place in the rig."""

    id: str
    name: str
    profile_id: str
    address: int
    order: int = 0
    invert_pan: bool = False
    invert_tilt: bool = False
    pan_offset: float = 0.0     # -0.5..0.5, trims a badly hung head
    tilt_offset: float = 0.0
    enabled: bool = True
    profile: Profile | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("profile", None)
        return data

    def render(self, state: FixtureState, universe: Universe) -> None:
        if not self.enabled or self.profile is None:
            return
        state = state.copy()
        if self.invert_pan:
            state.pan = 1.0 - state.pan
        if self.invert_tilt:
            state.tilt = 1.0 - state.tilt
        state.pan = max(0.0, min(1.0, state.pan + self.pan_offset))
        state.tilt = max(0.0, min(1.0, state.tilt + self.tilt_offset))
        self.profile.render(state, self.address, universe)

    @property
    def footprint(self) -> int:
        return self.profile.footprint if self.profile else 1

    @property
    def last_address(self) -> int:
        return self.address + self.footprint - 1


class ProfileLibrary:
    def __init__(self, directory: str = PROFILE_DIR) -> None:
        self.directory = directory
        self.profiles: dict[str, Profile] = {}
        self.reload()

    def reload(self) -> None:
        self.profiles = {}
        if not os.path.isdir(self.directory):
            return
        for filename in sorted(os.listdir(self.directory)):
            if not filename.endswith(".json"):
                continue
            path = os.path.join(self.directory, filename)
            try:
                with open(path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError) as exc:
                print(f"[profils] {filename} ignoré : {exc}")
                continue
            profile = Profile(data)
            self.profiles[profile.id] = profile

    def get(self, profile_id: str) -> Profile | None:
        return self.profiles.get(profile_id)

    def list(self) -> list[dict]:
        return [
            {
                "id": p.id,
                "name": p.name,
                "footprint": p.footprint,
                "colors": p.colors,
                "gobos": p.gobos,
                "channels": p.channel_names(),
            }
            for p in sorted(self.profiles.values(), key=lambda p: p.name)
        ]
