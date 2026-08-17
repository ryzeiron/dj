"""Tests unitaires : `python3 -m unittest discover tests`."""

import json
import unittest.mock
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beamctl.beat import BeatClock
from beamctl.dmx import Universe
from beamctl.effects import EFFECTS, EffectContext, apply_effect
from beamctl.engine import Engine
from beamctl.fixtures import Fixture, FixtureState, ProfileLibrary
from beamctl.output import ArtNetOutput, DummyOutput, SacnOutput
from beamctl.show import Look, Show


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


def _pyserial_available() -> bool:
    try:
        import serial  # noqa: F401
    except ImportError:
        return False
    return hasattr(os, "openpty")


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
