"""Tempo clock: a free running beat counter, driven by BPM or by tapping."""

from __future__ import annotations

import threading
import time

MIN_BPM = 40.0
MAX_BPM = 220.0


class BeatClock:
    """Counts beats continuously so effects can stay in phase with the music."""

    def __init__(self, bpm: float = 128.0) -> None:
        self._lock = threading.Lock()
        self._bpm = self._clamp(bpm)
        self._origin = time.monotonic()   # instant of beat `_origin_beats`
        self._origin_beats = 0.0
        self._taps: list[float] = []

    @staticmethod
    def _clamp(bpm: float) -> float:
        return max(MIN_BPM, min(MAX_BPM, float(bpm)))

    # -- reading -----------------------------------------------------------
    @property
    def bpm(self) -> float:
        with self._lock:
            return self._bpm

    def beats(self, now: float | None = None) -> float:
        """Continuous beat position, e.g. 12.5 = halfway through beat 12."""
        now = time.monotonic() if now is None else now
        with self._lock:
            return self._origin_beats + (now - self._origin) * self._bpm / 60.0

    def bar_phase(self, beats_per_bar: int = 4, now: float | None = None) -> float:
        """0..1 position inside the current bar."""
        return (self.beats(now) % beats_per_bar) / beats_per_bar

    # -- writing -----------------------------------------------------------
    def set_bpm(self, bpm: float) -> float:
        """Change tempo without jumping the phase."""
        now = time.monotonic()
        with self._lock:
            self._origin_beats += (now - self._origin) * self._bpm / 60.0
            self._origin = now
            self._bpm = self._clamp(bpm)
            return self._bpm

    def nudge(self, delta_bpm: float) -> float:
        return self.set_bpm(self.bpm + delta_bpm)

    def resync(self) -> None:
        """Declare 'now' to be a downbeat — the button you hit on the drop."""
        now = time.monotonic()
        with self._lock:
            self._origin = now
            self._origin_beats = 0.0

    def tap(self) -> float:
        """Tap along with the track. Returns the resulting BPM."""
        now = time.monotonic()
        with self._lock:
            if self._taps and now - self._taps[-1] > 2.0:
                self._taps = []          # new tapping session
            self._taps.append(now)
            self._taps = self._taps[-8:]
            if len(self._taps) >= 2:
                intervals = [b - a for a, b in zip(self._taps, self._taps[1:])]
                average = sum(intervals) / len(intervals)
                if average > 0:
                    bpm = 60.0 / average
                    while bpm < MIN_BPM:
                        bpm *= 2
                    while bpm > MAX_BPM:
                        bpm /= 2
                    self._bpm = self._clamp(bpm)
            # every tap is a beat, and it restarts the bar
            self._origin = now
            self._origin_beats = 0.0
            return self._bpm
