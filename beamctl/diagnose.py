"""Diagnostics: what is actually plugged in, and can we talk to it.

DMX512 is one way. A BEAM 100 never answers, so no software can "detect" a
lamp — the only honest check is: is the interface reachable, are the addresses
coherent, and does the lamp you point at actually light up. This module covers
the first two, and `Engine.lamp_test` covers the third.

Art-Net and sACN boxes are a different story: they are network nodes and they
do answer an ArtPoll, so those we can really discover.
"""

from __future__ import annotations

import socket
import struct
import time

ARTNET_PORT = 6454
ARTNET_ID = b"Art-Net\x00"
OP_POLL = 0x2000
OP_POLL_REPLY = 0x2100

def pyserial_status() -> dict:
    try:
        import serial
    except ImportError:
        return {"ok": False,
                "detail": "pyserial n'est pas installe — `pip install pyserial` "
                          "(necessaire pour les interfaces USB)"}
    return {"ok": True, "detail": f"pyserial {serial.__version__}"}


def serial_ports() -> list[dict]:
    """Every serial port, with a guess about which one is a DMX interface."""
    from .output import serial_candidates

    ports = []
    for port in serial_candidates():
        ports.append(dict(port, serial_number=""))
    return ports


def identified_interface() -> dict | None:
    """Which box the `usb` driver would pick, and what protocol it speaks."""
    from .output import find_usb_interface

    try:
        return find_usb_interface()
    except Exception:
        return None


# ----------------------------------------------------------------- network
def _parse_poll_reply(data: bytes, sender: str) -> dict | None:
    if len(data) < 108 or not data.startswith(ARTNET_ID):
        return None
    if struct.unpack("<H", data[8:10])[0] != OP_POLL_REPLY:
        return None
    ip = ".".join(str(b) for b in data[10:14])
    short = data[26:44].split(b"\x00")[0].decode("latin-1", "replace").strip()
    long_name = data[44:108].split(b"\x00")[0].decode("latin-1", "replace").strip()
    return {
        "ip": ip if ip != "0.0.0.0" else sender,
        "name": short or long_name or "node Art-Net",
        "description": long_name,
        "universe": data[19] & 0x0F if len(data) > 19 else 0,
    }


def poll_packet() -> bytes:
    """The ArtPoll every Art-Net node is required to answer."""
    return (ARTNET_ID + struct.pack("<H", OP_POLL) + struct.pack(">H", 14)
            + bytes([0x02, 0]))


def discover_artnet(timeout: float = 1.5, listen_port: int = ARTNET_PORT,
                    target_port: int = ARTNET_PORT,
                    broadcast: str = "255.255.255.255") -> list[dict]:
    """Broadcast an ArtPoll and collect the nodes that answer.

    The ports are parameters so the discovery can be exercised end to end
    against a fake node in the tests.
    """
    poll = poll_packet()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    nodes: dict[str, dict] = {}
    try:
        sock.bind(("", listen_port))
        sock.settimeout(0.25)
        sock.sendto(poll, (broadcast, target_port))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, address = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            node = _parse_poll_reply(data, address[0])
            if node:
                nodes[node["ip"]] = node
    except OSError as exc:
        return [{"error": f"ecoute Art-Net impossible : {exc}"}]
    finally:
        sock.close()
    return list(nodes.values())


# ------------------------------------------------------------------ output
def probe_output(config: dict) -> dict:
    """Open the configured interface and push one frame through it."""
    from .output import create_output

    try:
        output = create_output(config)
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}
    try:
        output.send(bytes(512))
        return {"ok": True, "detail": output.describe()}
    except Exception as exc:
        return {"ok": False, "detail": f"{output.describe()} : {exc}"}
    finally:
        try:
            output.close()
        except Exception:
            pass


# ------------------------------------------------------------------ report
def run(show, discover: bool = True, engine=None) -> dict:
    """Full report, shared by the `--check` command and the web page.

    When the engine is running it already holds the interface open — a USB port
    cannot be opened twice, so probing it again would report a false failure.
    In that case the engine's own state is the truth: it pushes 40 frames a
    second and records the last error.
    """
    config = show.config.get("output", {}) or {"driver": "dummy"}
    driver = str(config.get("driver", "dummy"))
    ports = serial_ports()

    lamps = []
    for fixture in show.sorted_fixtures():
        profile = fixture.profile
        lamps.append({
            "name": fixture.name,
            "address": fixture.address,
            "last_address": fixture.last_address,
            "profile": profile.name if profile else fixture.profile_id,
            "known_profile": profile is not None,
            "enabled": fixture.enabled,
        })

    return {
        "driver": driver,
        "pyserial": pyserial_status(),
        "serial_ports": ports,
        "usb_candidates": [p for p in ports if p["likely_dmx"]],
        "usb_interface": identified_interface(),
        "artnet_nodes": discover_artnet() if discover else [],
        "output": ({"ok": engine.output_error is None,
                    "detail": engine.output_error or engine.output.describe()}
                   if engine is not None else probe_output(config)),
        "lamps": lamps,
        "conflicts": show.patch_conflicts(),
    }


def format_report(report: dict) -> str:
    """The same report as plain text, for the terminal."""
    lines = ["", "=== Diagnostic beamctl ===", ""]

    lines.append(f"Interface configuree : {report['driver']}")
    output = report["output"]
    lines.append(f"  {'OK  ' if output['ok'] else 'ECHEC'} {output['detail']}")
    if not output["ok"] and report["driver"] in ("enttec", "opendmx"):
        lines.append("  (si beamctl tourne deja dans une autre fenetre, il garde le")
        lines.append("   port USB ouvert : ferme-le avant de relancer --check)")
    lines.append("")

    serial_status = report["pyserial"]
    lines.append(f"pyserial : {serial_status['detail']}")
    detected = report.get("usb_interface")
    if detected:
        protocol = ("protocole Enttec DMX USB Pro" if detected["driver"] == "enttec"
                    else "protocole Open DMX (FTDI direct)")
        lines.append(f"  -> boitier utilisable sur {detected['port']} : {protocol}")
    ports = report["serial_ports"]
    if not ports:
        lines.append("  aucun port serie detecte")
    for port in ports:
        mark = "->" if port["likely_dmx"] else "  "
        extra = f"  [{port['why']}]" if port["why"] else ""
        lines.append(f"  {mark} {port['device']}  {port['description']}{extra}")
    lines.append("")

    nodes = report["artnet_nodes"]
    lines.append("Boitiers Art-Net sur le reseau :")
    if not nodes:
        lines.append("  aucun (normal si tu utilises une interface USB)")
    for node in nodes:
        if node.get("error"):
            lines.append(f"  {node['error']}")
        else:
            lines.append(f"  -> {node['ip']}  {node['name']}")
    lines.append("")

    lines.append("Lampes declarees :")
    for lamp in report["lamps"]:
        state = "" if lamp["enabled"] else "  (desactivee)"
        lines.append(f"  {lamp['name']} : canaux {lamp['address']}-{lamp['last_address']}"
                     f"  [{lamp['profile']}]{state}")
    for problem in report["conflicts"]:
        lines.append(f"  ATTENTION : {problem}")
    lines.append("")

    lines.append("Rappel : le DMX ne parle que dans un sens. Aucun logiciel ne peut")
    lines.append("detecter un BEAM 100 — pour verifier qu'une lampe repond bien a son")
    lines.append("adresse, utilise le test lampe par lampe dans l'onglet Reglages.")
    lines.append("")
    return "\n".join(lines)
