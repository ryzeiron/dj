"""Point d'entree : `python3 -m beamctl`."""

from __future__ import annotations

import argparse
import signal
import sys
import time

from . import __version__
from .engine import Engine
from .server import lan_ip, serve
from .show import DEFAULT_SHOW_PATH, Show


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="beamctl",
        description="Contrôle DMX pour tetes mobiles BEAM 100 (interface web).")
    parser.add_argument("--show", default=DEFAULT_SHOW_PATH,
                        help="fichier de show (defaut : ./show.json)")
    parser.add_argument("--output",
                        choices=["usb", "dummy", "artnet", "sacn", "enttec", "opendmx"],
                        help="interface DMX : `usb` detecte le boitier branche "
                             "(sinon celle du fichier de show)")
    parser.add_argument("--dmx-host", help="IP du node Art-Net / sACN")
    parser.add_argument("--universe", type=int, help="univers DMX")
    parser.add_argument("--serial-port", help="port serie de l'interface USB-DMX")
    parser.add_argument("--bind", default="0.0.0.0", help="interface d'ecoute web")
    parser.add_argument("--port", type=int, default=8080, help="port web (defaut 8080)")
    parser.add_argument("--token", help="code d'acces exige dans l'URL (?t=CODE)")
    parser.add_argument("--fps", type=int, help="frequence de rafraichissement DMX")
    parser.add_argument("--list-serial", action="store_true",
                        help="lister les ports serie detectes puis quitter")
    parser.add_argument("--check", action="store_true",
                        help="verifier l'installation (interface, ports, reseau) puis quitter")
    parser.add_argument("--verbose", action="store_true", help="journal HTTP complet")
    parser.add_argument("--version", action="version", version=f"beamctl {__version__}")
    return parser


def list_serial_ports() -> int:
    try:
        from serial.tools import list_ports  # type: ignore
    except ImportError:
        print("pyserial n'est pas installe : pip install pyserial")
        return 1
    ports = list(list_ports.comports())
    if not ports:
        print("aucun port serie detecte")
        return 0
    for port in ports:
        print(f"{port.device}\t{port.description}")
    return 0


def apply_cli_output(show: Show, args: argparse.Namespace) -> None:
    if not args.output:
        return
    config: dict = {"driver": args.output}
    if args.dmx_host:
        config["host"] = args.dmx_host
    if args.universe is not None:
        config["universe"] = args.universe
    if args.serial_port:
        config["port"] = args.serial_port
    show.config["output"] = config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_serial:
        return list_serial_ports()

    show = Show(path=args.show)
    apply_cli_output(show, args)

    if args.check:
        from . import diagnose
        print(diagnose.format_report(diagnose.run(show)))
        return 0

    if args.fps:
        show.config["fps"] = args.fps

    engine = Engine(show)
    engine.start()

    conflicts = show.patch_conflicts()
    if conflicts:
        print("[patch] attention :")
        for problem in conflicts:
            print(f"  - {problem}")

    httpd = serve(engine, host=args.bind, port=args.port,
                  token=args.token, verbose=args.verbose)

    suffix = f"?t={args.token}" if args.token else ""
    print(f"beamctl {__version__} — show : {show.path}")
    print(f"sortie DMX : {engine.output.describe()}")
    print(f"lampes     : {len(show.fixtures)}")
    print()
    print(f"  ordinateur : http://127.0.0.1:{args.port}/{suffix}")
    if args.bind not in ("127.0.0.1", "localhost"):
        print(f"  telephone  : http://{lan_ip()}:{args.port}/{suffix}")
    print()
    print("Ctrl+C pour arreter (les lampes sont eteintes en sortant).")

    stopping = False

    def shutdown(*_args) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        while not stopping:
            time.sleep(0.2)
    finally:
        print("\narret…")
        httpd.shutdown()
        engine.stop()
        show.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
