"""DMX outputs: Art-Net, sACN (E1.31), Enttec DMX USB Pro, Open DMX USB, dummy.

Art-Net and sACN only need the standard library. The two USB drivers need
pyserial (`pip install pyserial`); they are imported lazily so the rest of the
app runs on a machine without it.
"""

from __future__ import annotations

import socket
import struct
import uuid

MAX_SLOTS = 512


class Output:
    """Base class. `send` is called by the engine at every render tick."""

    name = "output"

    def send(self, data: bytes) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass

    def describe(self) -> str:
        return self.name


class DummyOutput(Output):
    """Runs the whole show with no hardware attached. Handy to rehearse."""

    name = "dummy"

    def __init__(self, **_kwargs) -> None:
        self.last: bytes = bytes(MAX_SLOTS)
        self.frames = 0

    def send(self, data: bytes) -> None:
        self.last = data
        self.frames += 1

    def describe(self) -> str:
        return "aucune sortie (mode simulation)"


class ArtNetOutput(Output):
    """ArtDMX over UDP, port 6454. Works with every Art-Net node / WiFi box."""

    name = "artnet"

    def __init__(self, host: str = "255.255.255.255", port: int = 6454,
                 universe: int = 0, **_kwargs) -> None:
        self.host = host
        self.port = int(port)
        self.universe = int(universe)
        self._seq = 1
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def _packet(self, data: bytes) -> bytes:
        header = b"Art-Net\x00"
        header += struct.pack("<H", 0x5000)          # OpOutput / ArtDMX
        header += struct.pack(">H", 14)              # protocol version
        header += bytes([self._seq, 0])              # sequence, physical
        header += struct.pack("<H", self.universe)   # sub-uni + net
        header += struct.pack(">H", len(data))       # slot count, big endian
        return header + data

    def send(self, data: bytes) -> None:
        self._sock.sendto(self._packet(data), (self.host, self.port))
        self._seq = 1 if self._seq >= 255 else self._seq + 1

    def close(self) -> None:
        self._sock.close()

    def describe(self) -> str:
        return f"Art-Net -> {self.host}:{self.port} (univers {self.universe})"


class SacnOutput(Output):
    """Streaming ACN / E1.31, multicast by default (port 5568)."""

    name = "sacn"

    def __init__(self, universe: int = 1, host: str | None = None,
                 port: int = 5568, priority: int = 100,
                 source_name: str = "beamctl", **_kwargs) -> None:
        self.universe = max(1, int(universe))
        self.port = int(port)
        self.priority = int(priority)
        self.source_name = source_name
        self.host = host or f"239.255.{(self.universe >> 8) & 0xFF}.{self.universe & 0xFF}"
        self._seq = 0
        self._cid = uuid.uuid4().bytes
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 8)

    def _packet(self, data: bytes) -> bytes:
        data = data[:MAX_SLOTS].ljust(MAX_SLOTS, b"\x00")
        slots = len(data) + 1  # + start code

        root = struct.pack(">HH", 0x0010, 0x0000)
        root += b"ASC-E1.17\x00\x00\x00"
        root += struct.pack(">H", 0x7000 | (109 + slots))
        root += struct.pack(">I", 0x00000004)
        root += self._cid

        framing = struct.pack(">H", 0x7000 | (87 + slots))
        framing += struct.pack(">I", 0x00000002)
        framing += self.source_name.encode("utf-8")[:63].ljust(64, b"\x00")
        framing += bytes([self.priority])
        framing += struct.pack(">H", 0)          # synchronization address
        framing += bytes([self._seq, 0])         # sequence, options
        framing += struct.pack(">H", self.universe)

        dmp = struct.pack(">H", 0x7000 | (10 + slots))
        dmp += bytes([0x02, 0xA1])
        dmp += struct.pack(">HHH", 0x0000, 0x0001, slots)
        dmp += b"\x00" + data                    # start code + slots

        return root + framing + dmp

    def send(self, data: bytes) -> None:
        self._sock.sendto(self._packet(data), (self.host, self.port))
        self._seq = (self._seq + 1) % 256

    def close(self) -> None:
        self._sock.close()

    def describe(self) -> str:
        return f"sACN/E1.31 -> {self.host}:{self.port} (univers {self.universe})"


def _open_serial(port: str, baudrate: int, stopbits: int):
    try:
        import serial  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError(
            "pyserial est requis pour les interfaces USB-DMX : pip install pyserial"
        ) from exc
    sb = serial.STOPBITS_TWO if stopbits == 2 else serial.STOPBITS_ONE
    try:
        return serial.Serial(port=port, baudrate=baudrate, bytesize=8,
                             parity="N", stopbits=sb, timeout=1)
    except serial.SerialException as exc:
        raise RuntimeError(
            f"impossible d'ouvrir {port} ({exc}). Verifie le nom du port avec "
            "`python -m beamctl --list-serial`, que l'interface est branchee, "
            "et qu'aucun autre logiciel ne l'utilise."
        ) from exc


class EnttecProOutput(Output):
    """Enttec DMX USB Pro and the many clones that speak the same protocol."""

    name = "enttec"

    def __init__(self, port: str = "/dev/ttyUSB0", **_kwargs) -> None:
        self.port = port
        self._ser = _open_serial(port, 57600, stopbits=1)

    def send(self, data: bytes) -> None:
        payload = b"\x00" + data[:MAX_SLOTS].ljust(MAX_SLOTS, b"\x00")
        frame = b"\x7e\x06" + struct.pack("<H", len(payload)) + payload + b"\xe7"
        self._ser.write(frame)

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass

    def describe(self) -> str:
        return f"Enttec DMX USB Pro sur {self.port}"


class OpenDmxOutput(Output):
    """Open DMX USB / generic FTDI dongle: the break is generated by hand."""

    name = "opendmx"

    def __init__(self, port: str = "/dev/ttyUSB0", **_kwargs) -> None:
        self.port = port
        self._ser = _open_serial(port, 250000, stopbits=2)

    def send(self, data: bytes) -> None:
        import time

        self._ser.break_condition = True
        time.sleep(0.00012)          # break >= 92 us
        self._ser.break_condition = False
        time.sleep(0.00002)          # mark after break >= 12 us
        self._ser.write(b"\x00" + data[:MAX_SLOTS].ljust(MAX_SLOTS, b"\x00"))
        self._ser.flush()

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass

    def describe(self) -> str:
        return f"Open DMX USB (FTDI) sur {self.port}"


DRIVERS = {
    "dummy": DummyOutput,
    "artnet": ArtNetOutput,
    "sacn": SacnOutput,
    "enttec": EnttecProOutput,
    "opendmx": OpenDmxOutput,
}


def create_output(config: dict) -> Output:
    """Build an output from a config dict, falling back to dummy on error."""
    cfg = dict(config or {})
    driver = str(cfg.pop("driver", "dummy")).lower()
    cls = DRIVERS.get(driver)
    if cls is None:
        raise ValueError(f"sortie DMX inconnue : {driver}")
    return cls(**cfg)
