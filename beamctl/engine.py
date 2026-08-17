"""The render engine: turns the active look into DMX frames, 40 times a second."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict

from .beat import BeatClock
from .dmx import Universe
from .effects import EffectContext, apply_effect
from .fixtures import COLOR_RGB, FixtureState
from .output import Output, create_output, DummyOutput
from .show import Look, Show


class Engine:
    def __init__(self, show: Show, output: Output | None = None) -> None:
        self.show = show
        self.universe = Universe()
        self.clock = BeatClock(show.config.get("bpm", 128.0))
        self.fps = int(show.config.get("fps", 40) or 40)
        self.beats_per_bar = int(show.config.get("beats_per_bar", 4) or 4)

        self.output: Output = output or self._make_output()
        self.output_error: str | None = None

        self.master_dimmer = 1.0
        self.blackout = False
        self.strobe_momentary = False
        self.strobe_rate = 15.0
        self.freeze = False

        self.auto_mode: str | None = None       # None | doux | normal | feu
        self._auto_next_bar: float = 0.0
        self._auto_seed = 1

        self.active_look_id: str | None = show.looks[0].id if show.looks else None
        self.live: dict = {}                    # temporary overrides from the UI
        self.channel_overrides: dict[int, int] = {}   # raw channels, for testing
        self.solo_fixture: str | None = None

        self._frozen: dict[str, FixtureState] = {}
        self.last_states: list[FixtureState] = []
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.frames = 0
        self.started_at = time.monotonic()

    # -- output ------------------------------------------------------------
    def _make_output(self) -> Output:
        try:
            return create_output(self.show.config.get("output", {}))
        except Exception as exc:
            print(f"[sortie] {exc} — passage en mode simulation")
            self.output_error = str(exc)
            return DummyOutput()

    def set_output(self, config: dict) -> str:
        """Swap the DMX interface while the show is running."""
        with self._lock:
            new_output = create_output(config)   # raises on bad config
            old = self.output
            self.output = new_output
            self.output_error = None
            self.show.config["output"] = dict(config)
        try:
            old.close()
        except Exception:
            pass
        return new_output.describe()

    # -- transport ---------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dmx-render", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.blackout_now()
        try:
            self.output.close()
        except Exception:
            pass

    def blackout_now(self) -> None:
        """Send one all-zero frame, so the rig goes dark when we quit."""
        self.universe.clear()
        try:
            self.output.send(self.universe.snapshot())
        except Exception:
            pass

    def _run(self) -> None:
        period = 1.0 / max(1, self.fps)
        next_frame = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                self.render(now)
            except Exception as exc:            # never let the show stop
                self.output_error = f"rendu : {exc}"
            next_frame += period
            delay = next_frame - time.monotonic()
            if delay < -0.25:                   # we fell behind, resynchronise
                next_frame = time.monotonic()
                delay = 0
            if delay > 0:
                self._stop.wait(delay)

    # -- look resolution ---------------------------------------------------
    def current_look(self) -> Look:
        look = self.show.get_look(self.active_look_id) if self.active_look_id else None
        if look is None:
            look = self.show.looks[0] if self.show.looks else Look(id="-", name="-")
        if not self.live:
            return look
        merged = look.to_dict()
        merged.update({k: v for k, v in self.live.items() if k in merged})
        merged["id"] = look.id
        merged["name"] = look.name
        return Look.from_dict(merged)

    def _colors_for(self, look: Look, index: int, count: int, beats: float) -> str:
        palette = [c for c in (look.colors or []) if c] or [look.color]
        if look.color_mode == "static" or len(palette) == 1:
            return look.color if look.color_mode == "static" else palette[0]
        step = int(beats / max(0.25, look.color_beats))
        if look.color_mode == "chase":
            return palette[step % len(palette)]
        if look.color_mode == "spread":
            return palette[index % len(palette)]
        if look.color_mode == "random":
            seed = (step * 2654435761 + index * 40503) & 0xFFFFFF
            return palette[seed % len(palette)]
        return look.color

    def build_states(self, beats: float) -> list[FixtureState]:
        """Compute one frame of fixture states, before master and blackout."""
        look = self.current_look()
        fixtures = self.show.sorted_fixtures()
        count = len(fixtures)

        states = []
        for index, fixture in enumerate(fixtures):
            states.append(FixtureState(
                pan=look.pan,
                tilt=look.tilt,
                dimmer=look.dimmer,
                strobe=look.strobe,
                color=self._colors_for(look, index, count, beats),
                gobo=look.gobo,
                prism=look.prism,
                focus=look.focus,
                speed=look.speed,
            ))

        ctx = EffectContext(beats=beats, bpm=self.clock.bpm, length=look.length,
                            size=look.size, spread=look.spread)
        apply_effect(look.position_effect, states, ctx)
        apply_effect(look.intensity_effect, states, ctx)
        return states

    # -- autopilot ---------------------------------------------------------
    #: how many bars a look is held, per mode
    AUTO_BARS = {"doux": 16, "normal": 8, "feu": 4}
    #: which energies a mode is allowed to pick from
    AUTO_ENERGIES = {"doux": (1,), "normal": (1, 2), "feu": (2, 3)}

    def set_auto(self, mode: str | None, now: float | None = None) -> None:
        """Hands-free mode: the software changes look on its own, in time."""
        with self._lock:
            self.auto_mode = mode if mode in self.AUTO_BARS else None
            if self.auto_mode:
                bar = self.clock.beats(now) / max(1, self.beats_per_bar)
                self._auto_next_bar = bar + self.AUTO_BARS[self.auto_mode]

    def auto_pool(self) -> list[Look]:
        energies = self.AUTO_ENERGIES.get(self.auto_mode or "", ())
        pool = [l for l in self.show.looks if int(getattr(l, "energy", 2)) in energies]
        return pool or list(self.show.looks)

    def _tick_auto(self, beats: float) -> None:
        if not self.auto_mode:
            return
        bar = beats / max(1, self.beats_per_bar)
        if bar < self._auto_next_bar:
            return
        pool = self.auto_pool()
        if not pool:
            return
        candidates = [l for l in pool if l.id != self.active_look_id] or pool
        self._auto_seed = (self._auto_seed * 1103515245 + 12345) & 0x7FFFFFFF
        chosen = candidates[(self._auto_seed >> 8) % len(candidates)]
        self.active_look_id = chosen.id
        self.live = {}
        self._auto_next_bar = bar + self.AUTO_BARS[self.auto_mode]

    # -- rendering ---------------------------------------------------------
    def render(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            beats = self.clock.beats(now)
            self._tick_auto(beats)
            fixtures = self.show.sorted_fixtures()

            if self.freeze and self._frozen:
                states = [self._frozen.get(f.id, FixtureState()) for f in fixtures]
            else:
                states = self.build_states(beats)
                self._frozen = {f.id: s.copy() for f, s in zip(fixtures, states)}

            for fixture, state in zip(fixtures, states):
                if self.blackout:
                    state.dimmer = 0.0
                    state.strobe = 0.0
                else:
                    if self.solo_fixture and fixture.id != self.solo_fixture:
                        state.dimmer = 0.0
                    state.dimmer *= max(0.0, min(1.0, self.master_dimmer))
                    if self.strobe_momentary:
                        state.strobe = self.strobe_rate
                        state.dimmer = max(state.dimmer, self.master_dimmer)
                fixture.render(state, self.universe)

            for address, value in self.channel_overrides.items():
                self.universe.set(address, value)

            frame = self.universe.snapshot()
            self.last_states = states

        try:
            self.output.send(frame)
            self.output_error = None
        except Exception as exc:
            self.output_error = f"sortie : {exc}"
        self.frames += 1

    # -- commands ----------------------------------------------------------
    def activate_look(self, look_id: str) -> bool:
        with self._lock:
            if self.show.get_look(look_id) is None:
                return False
            self.active_look_id = look_id
            self.live = {}
            return True

    def set_live(self, values: dict) -> None:
        with self._lock:
            for key, value in values.items():
                if value is None:
                    self.live.pop(key, None)
                else:
                    self.live[key] = value

    def clear_live(self) -> None:
        with self._lock:
            self.live = {}

    def store_live_into_look(self) -> Look | None:
        """Freeze the current live tweaks back into the active look."""
        with self._lock:
            look = self.current_look()
            if self.active_look_id is None:
                return None
            data = look.to_dict()
            data["id"] = self.active_look_id
            stored = self.show.upsert_look(data)
            self.live = {}
            return stored

    def surprise(self) -> dict:
        """Roll a new look on top of the current one. Pure fun button."""
        import random

        from .effects import EFFECTS

        positions = [k for k, v in EFFECTS.items() if v["kind"] == "position"]
        intensities = [k for k, v in EFFECTS.items() if v["kind"] == "intensity"]
        palette = list(COLOR_RGB)
        profile = next((f.profile for f in self.show.sorted_fixtures() if f.profile), None)
        if profile and profile.colors:
            palette = profile.colors

        values = {
            "position_effect": random.choice(positions),
            "intensity_effect": random.choice(intensities + ["none", "none"]),
            "color_mode": random.choice(["static", "chase", "spread", "random"]),
            "color": random.choice(palette),
            "colors": random.sample(palette, min(len(palette), random.randint(2, 4))),
            "length": random.choice([1, 2, 4, 4, 8, 16]),
            "size": round(random.uniform(0.4, 1.0), 2),
            "spread": round(random.uniform(0.0, 1.0), 2),
            "tilt": round(random.uniform(0.2, 0.6), 2),
            "dimmer": 1.0,
        }
        self.set_live(values)
        return values

    def set_channel_override(self, address: int, value: int | None) -> None:
        with self._lock:
            if value is None:
                self.channel_overrides.pop(int(address), None)
            else:
                self.channel_overrides[int(address)] = max(0, min(255, int(value)))

    def clear_channel_overrides(self) -> None:
        with self._lock:
            self.channel_overrides = {}

    # -- reporting ---------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            look = self.current_look()
            fixtures = self.show.sorted_fixtures()
            states = self.last_states
            return {
                "bpm": round(self.clock.bpm, 1),
                "beats": round(self.clock.beats(), 3),
                "bar_phase": round(self.clock.bar_phase(self.beats_per_bar), 3),
                "look": look.to_dict(),
                "active_look_id": self.active_look_id,
                "live": dict(self.live),
                "master_dimmer": self.master_dimmer,
                "blackout": self.blackout,
                "strobe": self.strobe_momentary,
                "freeze": self.freeze,
                "solo": self.solo_fixture,
                "auto": self.auto_mode,
                "output": self.output.describe(),
                "output_error": self.output_error,
                "frames": self.frames,
                "overrides": dict(self.channel_overrides),
                "fixtures": [
                    {
                        "id": fixture.id,
                        "name": fixture.name,
                        "address": fixture.address,
                        **({"state": asdict(state)} if state else {}),
                    }
                    for fixture, state in zip(fixtures, list(states) + [None] * len(fixtures))
                ],
                "dmx": list(self.universe.snapshot()[:64]),
            }
