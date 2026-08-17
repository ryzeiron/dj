"""DMX512 universe buffer."""

from __future__ import annotations

import threading


class Universe:
    """A 512 slot DMX universe. Addresses are 1-based, as printed on fixtures."""

    SIZE = 512

    def __init__(self) -> None:
        self._data = bytearray(self.SIZE)
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._data = bytearray(self.SIZE)

    def set(self, address: int, value: int) -> None:
        if not 1 <= address <= self.SIZE:
            return
        with self._lock:
            self._data[address - 1] = max(0, min(255, int(value)))

    def set16(self, address: int, value: int) -> None:
        """Write a 16 bit value across `address` (coarse) and `address + 1` (fine)."""
        value = max(0, min(65535, int(value)))
        self.set(address, value >> 8)
        self.set(address + 1, value & 0xFF)

    def get(self, address: int) -> int:
        if not 1 <= address <= self.SIZE:
            return 0
        with self._lock:
            return self._data[address - 1]

    def snapshot(self) -> bytes:
        with self._lock:
            return bytes(self._data)
