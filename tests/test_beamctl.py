"""Tests unitaires : `python3 -m unittest discover tests`."""

import builtins
import json
import unittest.mock
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beamctl import diagnose
from beamctl.beat import BeatClock
from beamctl.dmx import Universe
from beamctl.effects import EFFECTS, EffectContext, apply_effect, sample_path
from beamctl.engine import Engine
from beamctl.fixtures import Fixture, FixtureState, ProfileLibrary
from beamctl import output
from beamctl.output import ArtNetOutput, DummyOutput, SacnOutput
from beamctl.show import Look, Show


def _pyserial_available() -> bool:
    try:
        import serial  # noqa: F401
    except ImportError:
        return False
    return hasattr(os, "openpty")


class TestUniverse(unittest.TestCase):
    def test_bounds_and_clamping(self):
        universe = Universe()
        universe.set(1, 300)
        universe.set(512, -5)
        universe.set(513, 255)          # ignore, hors univers
        self.assertEqual(universe.get(1), 255)
        self.assertEqual(universe.get(512), 0)
        self.assertEqual(len(universe.snapshot()), 512)

    def test_set16(self):
        universe = Universe()
        universe.set16(10, 0x1234)
        self.assertEqual(universe.get(10), 0x12)
        self.assertEqual(universe.get(11), 0x34)


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.library = ProfileLibrary()
        self.profile = self.library.get("beam100_14ch")

    def test_profiles_load(self):
        self.assertIsNotNone(self.profile)
        self.assertEqual(self.profile.footprint, 14)
        self.assertIn("rouge", self.profile.colors)

    def test_render_positions_and_colour(self):
        universe = Universe()
        state = FixtureState(pan=1.0, tilt=0.0, dimmer=0.5, color="rouge", gobo="gobo 2")
        self.profile.render(state, address=1, universe=universe)
        self.assertEqual(universe.get(1), 255)      # pan coarse
        self.assertEqual(universe.get(2), 255)      # pan fine
        self.assertEqual(universe.get(3), 0)        # tilt coarse
        self.assertEqual(universe.get(6), 128)      # dimmer 50 %
        self.assertEqual(universe.get(7), 255)      # shutter ouvert
        self.assertEqual(universe.get(8), 14)       # rouge
        self.assertEqual(universe.get(9), 16)       # gobo 2

    def test_render_at_offset_address(self):
        universe = Universe()
        self.profile.render(FixtureState(pan=1.0), address=15, universe=universe)
        self.assertEqual(universe.get(15), 255)
        self.assertEqual(universe.get(1), 0)

    def test_shutter_closes_on_blackout(self):
        universe = Universe()
        self.profile.render(FixtureState(dimmer=0.0), 1, universe)
        self.assertEqual(universe.get(7), 0)

    def test_strobe_maps_into_range(self):
        universe = Universe()
        self.profile.render(FixtureState(strobe=20.0), 1, universe)
        self.assertEqual(universe.get(7), 215)

    def test_speed_channel_is_inverted(self):
        universe = Universe()
        self.profile.render(FixtureState(speed=0.0), 1, universe)
        self.assertEqual(universe.get(5), 255)      # 0 = le plus rapide

    def test_rgb_profile(self):
        universe = Universe()
        par = self.library.get("par_rgbw_4ch")
        par.render(FixtureState(color="rouge", dimmer=0.5), 1, universe)
        self.assertEqual(universe.get(1), 128)
        self.assertEqual(universe.get(2), 0)


class TestFixture(unittest.TestCase):
    def setUp(self):
        self.library = ProfileLibrary()

    def test_invert_and_offset(self):
        universe = Universe()
        fixture = Fixture(id="f", name="B", profile_id="beam100_14ch", address=1,
                          invert_pan=True)
        fixture.profile = self.library.get("beam100_14ch")
        fixture.render(FixtureState(pan=1.0), universe)
        self.assertEqual(universe.get(1), 0)

    def test_disabled_fixture_writes_nothing(self):
        universe = Universe()
        fixture = Fixture(id="f", name="B", profile_id="beam100_14ch", address=1,
                          enabled=False)
        fixture.profile = self.library.get("beam100_14ch")
        fixture.render(FixtureState(dimmer=1.0), universe)
        self.assertEqual(universe.snapshot(), bytes(512))


class TestBeatClock(unittest.TestCase):
    def test_beats_advance(self):
        clock = BeatClock(120)
        start = clock.beats(now=0.0)
        # 120 bpm : une seconde vaut deux temps
        self.assertAlmostEqual(clock.beats(now=1.0) - start, 2.0, places=3)

    def test_set_bpm_keeps_phase_continuous(self):
        clock = BeatClock(120)
        before = clock.beats()
        clock.set_bpm(174)
        after = clock.beats()
        self.assertAlmostEqual(before, after, places=2)
        self.assertEqual(clock.bpm, 174)

    def test_tap_gives_bpm(self):
        clock = BeatClock(128)
        now = 100.0
        with unittest.mock.patch("time.monotonic", side_effect=[now, now + 0.5,
                                                                now + 1.0, now + 1.5]):
            clock.tap()
            clock.tap()
            clock.tap()
            bpm = clock.tap()
        self.assertAlmostEqual(bpm, 120.0, places=1)

    def test_tap_folds_extreme_tempo_into_range(self):
        clock = BeatClock(128)
        now = 10.0
        with unittest.mock.patch("time.monotonic", side_effect=[now, now + 2.0]):
            clock.tap()
            bpm = clock.tap()
        self.assertGreaterEqual(bpm, 40.0)          # 30 bpm double en 60
        self.assertAlmostEqual(bpm, 60.0, places=1)


class TestEffects(unittest.TestCase):
    def states(self, count=4):
        return [FixtureState() for _ in range(count)]

    def test_positions_stay_in_range(self):
        for name in ("sweep", "circle", "figure8", "fan", "cross", "random_pos", "nod"):
            for beats in (0.0, 0.7, 3.3, 12.9):
                states = self.states()
                apply_effect(name, states, EffectContext(beats=beats, size=1.0))
                for state in states:
                    self.assertGreaterEqual(state.pan, 0.0, name)
                    self.assertLessEqual(state.pan, 1.0, name)
                    self.assertGreaterEqual(state.tilt, 0.0, name)
                    self.assertLessEqual(state.tilt, 1.0, name)

    def test_chase_lights_one_fixture(self):
        states = self.states(4)
        apply_effect("chase", states, EffectContext(beats=0.0, length=1))
        self.assertEqual([s.dimmer for s in states], [1.0, 0.0, 0.0, 0.0])
        states = self.states(4)
        apply_effect("chase", states, EffectContext(beats=2.5, length=1))
        self.assertEqual([s.dimmer for s in states], [0.0, 0.0, 1.0, 0.0])

    def test_random_positions_are_stable_within_a_step(self):
        first = self.states(3)
        second = self.states(3)
        apply_effect("random_pos", first, EffectContext(beats=4.1, length=4))
        apply_effect("random_pos", second, EffectContext(beats=4.9, length=4))
        self.assertEqual([s.pan for s in first], [s.pan for s in second])

    def test_spread_puts_fixtures_out_of_phase(self):
        states = self.states(4)
        apply_effect("sweep", states, EffectContext(beats=0.0, size=1.0, spread=1.0))
        self.assertNotAlmostEqual(states[0].pan, states[1].pan)

    def test_strobe_effect_sets_rate(self):
        states = self.states(2)
        apply_effect("strobe_beat", states, EffectContext(beats=0.0, length=1))
        self.assertGreater(states[0].strobe, 0)


class TestCustomPath(unittest.TestCase):
    SQUARE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]

    def test_sample_passes_through_its_points(self):
        for index, point in enumerate(self.SQUARE):
            x, y = sample_path(self.SQUARE, index / len(self.SQUARE))
            self.assertAlmostEqual(x, point[0], places=6)
            self.assertAlmostEqual(y, point[1], places=6)

    def test_sample_is_a_closed_loop(self):
        self.assertEqual(sample_path(self.SQUARE, 0.0), sample_path(self.SQUARE, 1.0))

    def test_sample_survives_degenerate_input(self):
        self.assertEqual(sample_path([], 0.3), (0.5, 0.5))
        self.assertEqual(sample_path([[0.1, 0.9]], 0.7), (0.1, 0.9))

    def test_effect_moves_along_the_curve(self):
        ctx = EffectContext(beats=0.0, length=4, size=0.5,
                            params={"path": self.SQUARE})
        first = [FixtureState()]
        apply_effect("path", first, ctx)
        self.assertAlmostEqual(first[0].pan, 0.2, places=6)
        self.assertAlmostEqual(first[0].tilt, 0.2, places=6)

        later = [FixtureState()]
        apply_effect("path", later, EffectContext(beats=1.0, length=4, size=0.5,
                                                  params={"path": self.SQUARE}))
        self.assertAlmostEqual(later[0].pan, 0.8, places=6)

    def test_size_scales_around_the_centre(self):
        states = [FixtureState()]
        apply_effect("path", states, EffectContext(beats=0.0, length=4, size=0.25,
                                                   params={"path": self.SQUARE}))
        self.assertAlmostEqual(states[0].pan, 0.35, places=6)   # moitie du trace

    def test_empty_path_is_a_no_op(self):
        states = [FixtureState(pan=0.42, tilt=0.11)]
        apply_effect("path", states, EffectContext(beats=3.0, params={"path": []}))
        self.assertEqual((states[0].pan, states[0].tilt), (0.42, 0.11))

    def test_engine_renders_a_drawn_path(self):
        directory = tempfile.mkdtemp()
        show = Show(path=os.path.join(directory, "show.json"))
        engine = Engine(show, output=DummyOutput())
        show.upsert_look({"id": "trace", "name": "Tracé", "dimmer": 1.0,
                          "position_effect": "path", "size": 0.5,
                          "path": self.SQUARE})
        engine.activate_look("trace")
        engine.clock.resync()           # temps 0 = premier point du trace
        engine.render()
        self.assertEqual(engine.universe.get(1), round(0.2 * 255))

    def test_path_survives_a_save_and_reload(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "show.json")
        show = Show(path=path)
        show.upsert_look({"id": "t", "name": "T", "path": self.SQUARE,
                          "position_effect": "path"})
        show.save()
        self.assertEqual(Show(path=path).get_look("t").path, self.SQUARE)


class TestShow(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "show.json")

    def test_defaults_and_roundtrip(self):
        show = Show(path=self.path)
        self.assertEqual(len(show.fixtures), 2)
        self.assertTrue(show.looks)
        show.upsert_look({"id": "x", "name": "Test", "color": "cyan"})
        show.save()

        reloaded = Show(path=self.path)
        self.assertEqual(reloaded.get_look("x").color, "cyan")
        self.assertEqual(len(reloaded.fixtures), 2)
        self.assertIsNotNone(reloaded.fixtures[0].profile)

    def test_patch_conflicts(self):
        show = Show(path=self.path)
        show.set_patch([
            {"id": "a", "name": "A", "profile_id": "beam100_14ch", "address": 1},
            {"id": "b", "name": "B", "profile_id": "beam100_14ch", "address": 5},
        ])
        self.assertTrue(show.patch_conflicts())
        show.set_patch([
            {"id": "a", "name": "A", "profile_id": "beam100_14ch", "address": 1},
            {"id": "b", "name": "B", "profile_id": "beam100_14ch", "address": 15},
        ])
        self.assertEqual(show.patch_conflicts(), [])

    def test_conflict_when_over_512(self):
        show = Show(path=self.path)
        show.set_patch([{"id": "a", "name": "A", "profile_id": "beam100_14ch",
                         "address": 505}])
        self.assertTrue(show.patch_conflicts())

    def test_corrupt_show_file_falls_back(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ pas du json")
        show = Show(path=self.path)
        self.assertEqual(len(show.fixtures), 2)

    def test_delete_look(self):
        show = Show(path=self.path)
        look_id = show.looks[0].id
        self.assertTrue(show.delete_look(look_id))
        self.assertIsNone(show.get_look(look_id))


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.show = Show(path=os.path.join(self.directory, "show.json"))
        self.engine = Engine(self.show, output=DummyOutput())

    def test_render_writes_dmx(self):
        self.engine.activate_look("l12")            # plein feu
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(6), 255)
        self.assertEqual(self.engine.output.frames, 1)

    def test_blackout_kills_output(self):
        self.engine.activate_look("l12")
        self.engine.blackout = True
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(6), 0)
        self.assertEqual(self.engine.universe.get(7), 0)   # shutter ferme

    def test_master_dimmer_scales(self):
        self.engine.activate_look("l12")
        self.engine.master_dimmer = 0.5
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(6), 128)

    def test_live_overrides_look(self):
        self.engine.activate_look("l12")
        self.engine.set_live({"color": "rouge"})
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(8), 14)
        self.engine.clear_live()
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(8), 0)   # blanc

    def test_store_live_writes_into_look(self):
        self.engine.activate_look("l12")
        self.engine.set_live({"color": "cyan"})
        self.engine.store_live_into_look()
        self.assertEqual(self.show.get_look("l12").color, "cyan")
        self.assertEqual(self.engine.live, {})

    def test_channel_override_wins(self):
        self.engine.activate_look("l12")
        self.engine.set_channel_override(6, 7)
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(6), 7)
        self.engine.clear_channel_overrides()
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(6), 255)

    def test_solo_mutes_the_others(self):
        self.engine.activate_look("l12")
        self.engine.solo_fixture = "f2"
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(6), 0)     # lampe 1 eteinte
        self.assertEqual(self.engine.universe.get(20), 255)  # lampe 2 (adresse 15)

    def test_colour_spread_gives_each_fixture_its_colour(self):
        self.show.upsert_look({"id": "spread", "name": "S", "color_mode": "spread",
                               "colors": ["rouge", "bleu"], "dimmer": 1.0})
        self.engine.activate_look("spread")
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(8), 14)    # rouge
        self.assertEqual(self.engine.universe.get(22), 42)   # bleu

    def test_status_snapshot(self):
        self.engine.render(now=0.0)
        status = self.engine.status()
        self.assertIn("bpm", status)
        self.assertEqual(len(status["fixtures"]), 2)
        self.assertEqual(len(status["dmx"]), 64)

    def test_freeze_holds_the_frame(self):
        self.show.upsert_look({"id": "mv", "name": "M", "dimmer": 1.0,
                               "position_effect": "sweep", "length": 4, "size": 1.0})
        self.engine.activate_look("mv")
        self.engine.render(now=0.0)
        self.engine.freeze = True
        first = self.engine.universe.get(1)
        self.engine.clock.set_bpm(200)
        self.engine.render(now=10.0)
        self.assertEqual(self.engine.universe.get(1), first)


class FakeArtNetNode(threading.Thread):
    """Un boitier Art-Net qui repond a un ArtPoll, comme le vrai materiel."""

    daemon = True

    def __init__(self, port: int) -> None:
        super().__init__()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.settimeout(4)
        self.polled = False

    @staticmethod
    def reply() -> bytes:
        packet = b"Art-Net\x00" + struct.pack("<H", 0x2100)
        packet += bytes([192, 168, 1, 50]) + struct.pack("<H", 0x1936)
        packet += bytes([0, 14, 0, 3, 0, 0, 0, 0xD0, 0, 0])
        packet += b"BeamBox".ljust(18, b"\x00")
        packet += b"Boitier Art-Net".ljust(64, b"\x00")
        return packet.ljust(239, b"\x00")

    def run(self) -> None:
        try:
            data, address = self.sock.recvfrom(2048)
        except socket.timeout:
            return
        if data.startswith(b"Art-Net\x00") and struct.unpack("<H", data[8:10])[0] == 0x2000:
            self.polled = True
            self.sock.sendto(self.reply(), address)

    def close(self) -> None:
        self.sock.close()


class TestDiagnostics(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.show = Show(path=os.path.join(self.directory, "show.json"))

    def test_poll_packet_is_valid_artnet(self):
        packet = diagnose.poll_packet()
        self.assertTrue(packet.startswith(b"Art-Net\x00"))
        self.assertEqual(struct.unpack("<H", packet[8:10])[0], 0x2000)
        self.assertEqual(struct.unpack(">H", packet[10:12])[0], 14)

    def test_discovers_a_node_that_answers(self):
        node = FakeArtNetNode(port=6455)
        node.start()
        try:
            found = diagnose.discover_artnet(timeout=2.0, listen_port=6456,
                                             target_port=6455, broadcast="127.0.0.1")
        finally:
            node.join(timeout=3)
            node.close()
        self.assertTrue(node.polled, "le boitier n'a pas recu l'ArtPoll")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["ip"], "192.168.1.50")
        self.assertEqual(found[0]["name"], "BeamBox")

    def test_silence_gives_an_empty_list(self):
        found = diagnose.discover_artnet(timeout=0.4, listen_port=6457,
                                         target_port=6458, broadcast="127.0.0.1")
        self.assertEqual(found, [])

    def test_garbage_is_not_taken_for_a_node(self):
        self.assertIsNone(diagnose._parse_poll_reply(b"pas de l'art-net", "1.2.3.4"))
        self.assertIsNone(diagnose._parse_poll_reply(b"Art-Net\x00" + b"\x00" * 200, "1.2.3.4"))

    def test_probe_reports_a_working_output(self):
        result = diagnose.probe_output({"driver": "artnet", "host": "127.0.0.1"})
        self.assertTrue(result["ok"], result["detail"])

    def test_probe_reports_a_broken_output(self):
        result = diagnose.probe_output({"driver": "opendmx", "port": "/dev/ttyABSENT"})
        self.assertFalse(result["ok"])
        self.assertIn("ttyABSENT", result["detail"])

    def test_running_engine_is_trusted_over_a_second_probe(self):
        """Le port USB ne s'ouvre pas deux fois : on lit l'etat du moteur."""
        engine = Engine(self.show, output=DummyOutput())
        self.show.config["output"] = {"driver": "opendmx", "port": "/dev/ttyABSENT"}
        report = diagnose.run(self.show, discover=False, engine=engine)
        self.assertTrue(report["output"]["ok"])
        engine.output_error = "sortie : cable debranche"
        report = diagnose.run(self.show, discover=False, engine=engine)
        self.assertFalse(report["output"]["ok"])
        self.assertIn("debranche", report["output"]["detail"])

    def test_report_lists_the_patch(self):
        report = diagnose.run(self.show, discover=False)
        self.assertEqual(len(report["lamps"]), 2)
        self.assertEqual(report["lamps"][0]["address"], 1)
        self.assertEqual(report["lamps"][1]["address"], 15)
        self.assertTrue(report["lamps"][0]["known_profile"])
        self.assertIn("driver", report)

    def test_report_formats_as_text(self):
        text = diagnose.format_report(diagnose.run(self.show, discover=False))
        self.assertIn("Diagnostic beamctl", text)
        self.assertIn("Beam 1 : canaux 1-14", text)
        self.assertIn("sens", text)          # le rappel sur le DMX unidirectionnel


class TestLampTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.show = Show(path=os.path.join(self.directory, "show.json"))
        self.engine = Engine(self.show, output=DummyOutput())

    def test_lights_only_the_tested_lamp(self):
        self.engine.lamp_test("f2")
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(6), 0)      # lampe 1 eteinte
        self.assertEqual(self.engine.universe.get(20), 255)   # lampe 2 pleine
        self.assertEqual(self.engine.universe.get(22), 0)     # blanc
        self.assertEqual(self.engine.universe.get(15), 128)   # tete centree

    def test_stopping_the_test_gives_the_show_back(self):
        self.engine.activate_look("l12")
        self.engine.lamp_test("f1")
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(20), 0)
        self.engine.lamp_test(None)
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(20), 255)

    def test_unknown_lamp_is_refused(self):
        self.assertIsNone(self.engine.lamp_test("nexiste-pas"))

    def test_blackout_still_wins(self):
        """Le blackout coupe la lumiere ; les tetes gardent leur position."""
        self.engine.lamp_test("f1")
        self.engine.blackout = True
        self.engine.render(now=0.0)
        self.assertEqual(self.engine.universe.get(6), 0)      # dimmer
        self.assertEqual(self.engine.universe.get(7), 0)      # shutter ferme


class FakeEnttecWidget(threading.Thread):
    """Un widget Enttec sur un pty : il repond a la requete de parametres."""

    daemon = True

    def __init__(self, answer: bool = True) -> None:
        super().__init__()
        self.master, slave = os.openpty()
        self.port = os.ttyname(slave)
        self.answer = answer
        self.asked = False

    def run(self) -> None:
        deadline = time.time() + 3
        buffer = b""
        while time.time() < deadline:
            try:
                buffer += os.read(self.master, 64)
            except OSError:
                return
            if b"\x7e\x03" in buffer:
                self.asked = True
                if self.answer:
                    params = bytes([0, 1, 9, 1, 40, 40, 0])
                    os.write(self.master, b"\x7e\x03"
                             + len(params).to_bytes(2, "little") + params + b"\xe7")
                return


@unittest.skipUnless(hasattr(os, "openpty") and _pyserial_available(),
                     "pty ou pyserial indisponible")
class TestUsbDetection(unittest.TestCase):
    def test_recognises_an_enttec_widget(self):
        widget = FakeEnttecWidget(answer=True)
        widget.start()
        driver = output.identify_interface(widget.port, timeout=1.0)
        widget.join(timeout=2)
        self.assertTrue(widget.asked, "le widget n'a pas recu la requete")
        self.assertEqual(driver, "enttec")

    def test_a_silent_box_is_treated_as_open_dmx(self):
        widget = FakeEnttecWidget(answer=False)
        widget.start()
        driver = output.identify_interface(widget.port, timeout=0.5)
        widget.join(timeout=2)
        self.assertEqual(driver, "opendmx")

    def test_missing_pyserial_says_so_instead_of_blaming_the_hardware(self):
        """Sans pyserial on ne peut pas voir les ports : il faut le dire."""
        real_import = builtins.__import__

        def no_serial(name, *args, **kwargs):
            if name == "serial" or name.startswith("serial."):
                raise ImportError("pas de pyserial")
            return real_import(name, *args, **kwargs)

        with unittest.mock.patch.object(builtins, "__import__", no_serial):
            with self.assertRaises(RuntimeError) as caught:
                output.create_output({"driver": "usb"})
        message = str(caught.exception)
        self.assertIn("pyserial", message)
        self.assertIn("pip install", message)
        self.assertNotIn("branche", message)

    def test_usb_driver_refuses_to_guess_when_nothing_is_plugged(self):
        with unittest.mock.patch.object(output, "serial_candidates", return_value=[]):
            self.assertIsNone(output.find_usb_interface())
            with self.assertRaises(RuntimeError) as caught:
                output.create_output({"driver": "usb"})
        self.assertIn("aucun boitier USB-DMX", str(caught.exception))

    def test_a_plain_serial_port_is_not_mistaken_for_an_interface(self):
        """Un COM de carte mere, muet et sans puce FTDI, doit etre ignore."""
        widget = FakeEnttecWidget(answer=False)
        widget.start()
        plain = [{"device": widget.port, "description": "port serie",
                  "vid": None, "pid": None, "likely_dmx": False, "why": ""}]
        with unittest.mock.patch.object(output, "serial_candidates", return_value=plain):
            found = output.find_usb_interface()
        widget.join(timeout=2)
        self.assertIsNone(found)

    def test_an_answering_box_is_accepted_even_without_a_known_chip(self):
        widget = FakeEnttecWidget(answer=True)
        widget.start()
        unknown = [{"device": widget.port, "description": "boitier inconnu",
                    "vid": None, "pid": None, "likely_dmx": False, "why": ""}]
        with unittest.mock.patch.object(output, "serial_candidates", return_value=unknown):
            found = output.find_usb_interface()
        widget.join(timeout=2)
        self.assertIsNotNone(found)
        self.assertEqual(found["driver"], "enttec")

    def test_full_chain_reaches_the_wire(self):
        """Moteur -> detection USB -> vraies trames Enttec sur le port."""
        widget = FakeEnttecWidget(answer=True)
        widget.start()
        fake = [{"device": widget.port, "description": "FT232R USB UART",
                 "vid": 0x0403, "pid": 0x6001, "likely_dmx": True, "why": "FTDI"}]

        directory = tempfile.mkdtemp()
        show = Show(path=os.path.join(directory, "show.json"))
        show.config["output"] = {"driver": "usb"}
        with unittest.mock.patch.object(output, "serial_candidates", return_value=fake):
            engine = Engine(show)
        widget.join(timeout=2)
        self.assertIn("Enttec", engine.output.describe())

        engine.activate_look("l12")           # plein feu
        engine.clock.resync()
        engine.render()
        engine.output.close()

        os.set_blocking(widget.master, False)
        time.sleep(0.1)
        raw = b""
        try:
            while True:
                chunk = os.read(widget.master, 4096)
                if not chunk:
                    break
                raw += chunk
        except BlockingIOError:
            pass

        start = raw.find(b"\x7e\x06")
        self.assertGreaterEqual(start, 0, "aucune trame DMX envoyee")
        frame = raw[start:]
        length = struct.unpack("<H", frame[2:4])[0]
        self.assertEqual(length, 513)         # start code + 512 canaux
        self.assertEqual(frame[4 + length], 0xE7)
        slots = frame[5:5 + 512]
        self.assertEqual(slots[5], 255)       # dimmer lampe 1
        self.assertEqual(slots[6], 255)       # shutter lampe 1
        self.assertEqual(slots[19], 255)      # dimmer lampe 2, adresse 15

    def test_known_dmx_chips_come_first(self):
        ports = [{"device": "COM1", "likely_dmx": False},
                 {"device": "COM7", "likely_dmx": True}]
        class FakePort:
            def __init__(self, device, vid):
                self.device, self.vid, self.pid = device, vid, None
                self.description = ""
        fake = [FakePort("COM1", None), FakePort("COM7", 0x0403)]
        with unittest.mock.patch("serial.tools.list_ports.comports", return_value=fake):
            ordered = output.serial_candidates()
        self.assertEqual(ordered[0]["device"], "COM7")
        self.assertTrue(ordered[0]["likely_dmx"])


class TestOutputPackets(unittest.TestCase):
    def test_artnet_header(self):
        output = ArtNetOutput(host="127.0.0.1", universe=3)
        packet = output._packet(bytes(512))
        self.assertTrue(packet.startswith(b"Art-Net\x00"))
        self.assertEqual(struct.unpack("<H", packet[8:10])[0], 0x5000)
        self.assertEqual(packet[14], 3)                       # univers
        self.assertEqual(struct.unpack(">H", packet[16:18])[0], 512)
        self.assertEqual(len(packet), 18 + 512)
        output.close()

    def test_sacn_lengths(self):
        output = SacnOutput(universe=1)
        packet = output._packet(bytes(512))
        self.assertEqual(len(packet), 638)
        self.assertEqual(packet[4:16], b"ASC-E1.17\x00\x00\x00")
        self.assertEqual(struct.unpack(">H", packet[16:18])[0] & 0x0FFF, 622)
        self.assertEqual(struct.unpack(">H", packet[38:40])[0] & 0x0FFF, 600)
        self.assertEqual(struct.unpack(">H", packet[115:117])[0] & 0x0FFF, 523)
        self.assertEqual(output.host, "239.255.0.1")
        output.close()


class TestAutopilot(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.show = Show(path=os.path.join(self.directory, "show.json"))
        self.engine = Engine(self.show, output=DummyOutput())

    def test_off_by_default(self):
        first = self.engine.active_look_id
        for beats in (0.0, 40.0, 400.0):
            self.engine._tick_auto(beats)
        self.assertEqual(self.engine.active_look_id, first)

    def test_changes_look_after_the_right_number_of_bars(self):
        self.engine.clock.resync()
        self.engine.set_auto("feu")                 # 4 mesures = 16 temps
        start = self.engine.active_look_id
        self.engine._tick_auto(self.engine.clock.beats() + 8)
        self.assertEqual(self.engine.active_look_id, start)
        self.engine._tick_auto(self.engine.clock.beats() + 17)
        self.assertNotEqual(self.engine.active_look_id, start)

    def test_pool_follows_the_mode_energy(self):
        self.engine.set_auto("doux")
        self.assertTrue(all(l.energy == 1 for l in self.engine.auto_pool()))
        self.engine.set_auto("feu")
        self.assertTrue(all(l.energy in (2, 3) for l in self.engine.auto_pool()))

    def test_unknown_mode_disables(self):
        self.engine.set_auto("n'importe quoi")
        self.assertIsNone(self.engine.auto_mode)

    def test_never_picks_the_same_look_twice_in_a_row(self):
        self.engine.set_auto("normal")
        seen = []
        beats = self.engine.clock.beats()
        for _ in range(12):
            beats += 33
            self.engine._tick_auto(beats)
            seen.append(self.engine.active_look_id)
        self.assertTrue(all(a != b for a, b in zip(seen, seen[1:])))
        self.assertGreater(len(set(seen)), 1)

    def test_auto_clears_live_tweaks(self):
        self.engine.set_live({"color": "rouge"})
        self.engine.set_auto("feu")
        self.engine._tick_auto(self.engine.clock.beats() + 100)
        self.assertEqual(self.engine.live, {})

    def test_surprise_produces_a_playable_look(self):
        values = self.engine.surprise()
        self.assertIn(values["position_effect"], EFFECTS)
        self.assertGreaterEqual(len(values["colors"]), 2)
        self.engine.render(now=0.0)                 # doit rendre sans exception
        self.assertEqual(self.engine.current_look().position_effect,
                         values["position_effect"])


class TestWizardPatch(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.show = Show(path=os.path.join(self.directory, "show.json"))

    def test_addresses_follow_the_footprint(self):
        addresses = self.show.auto_patch(4, "beam100_14ch")
        self.assertEqual(addresses, [1, 15, 29, 43])
        self.assertEqual(self.show.patch_conflicts(), [])

    def test_eleven_channel_mode_packs_tighter(self):
        self.assertEqual(self.show.auto_patch(3, "beam100_11ch"), [1, 12, 23])

    def test_count_is_clamped(self):
        self.assertEqual(len(self.show.auto_patch(0, "beam100_14ch")), 1)
        self.assertEqual(len(self.show.auto_patch(99, "beam100_14ch")), 32)


@unittest.skipUnless(_pyserial_available(),
                     "pyserial ou openpty indisponible (Windows / dependance absente)")
class TestSerialOutputs(unittest.TestCase):
    """Les pilotes USB sont verifies sur un faux port serie (pty)."""

    def _fake_port(self):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        return master, os.ttyname(slave)

    def test_enttec_frame(self):
        from beamctl.output import EnttecProOutput

        master, port = self._fake_port()
        output = EnttecProOutput(port=port)
        data = bytearray(512)
        data[0], data[5] = 255, 128
        output.send(bytes(data))
        frame = os.read(master, 2048)
        output.close()

        self.assertEqual(len(frame), 518)
        self.assertEqual(frame[0], 0x7E)
        self.assertEqual(frame[1], 6)                                  # envoi DMX
        self.assertEqual(int.from_bytes(frame[2:4], "little"), 513)
        self.assertEqual(frame[4], 0)                                  # start code
        self.assertEqual(frame[5], 255)
        self.assertEqual(frame[10], 128)
        self.assertEqual(frame[-1], 0xE7)

    def test_opendmx_frame(self):
        from beamctl.output import OpenDmxOutput

        master, port = self._fake_port()
        output = OpenDmxOutput(port=port)
        data = bytearray(512)
        data[0] = 200
        output.send(bytes(data))
        frame = os.read(master, 2048)
        output.close()

        self.assertEqual(len(frame), 513)
        self.assertEqual(frame[0], 0)
        self.assertEqual(frame[1], 200)

    def test_missing_port_explains_itself(self):
        from beamctl.output import create_output

        with self.assertRaises(RuntimeError) as caught:
            create_output({"driver": "enttec", "port": "/dev/ttyINEXISTANT"})
        self.assertIn("--list-serial", str(caught.exception))


class TestLook(unittest.TestCase):
    def test_from_dict_ignores_unknown_keys(self):
        look = Look.from_dict({"id": "a", "name": "A", "inconnu": 12})
        self.assertEqual(look.id, "a")

    def test_json_roundtrip(self):
        look = Look(id="a", name="A", colors=["rouge"])
        self.assertEqual(Look.from_dict(json.loads(json.dumps(look.to_dict()))), look)


if __name__ == "__main__":
    unittest.main()
