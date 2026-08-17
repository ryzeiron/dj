"""The show file: patch, looks and output settings, persisted as JSON."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, asdict, field, fields

from .fixtures import Fixture, ProfileLibrary

DEFAULT_SHOW_PATH = os.path.join(os.getcwd(), "show.json")


@dataclass
class Look:
    """One button on the live page: a base state plus two effects."""

    id: str
    name: str
    color: str = "blanc"
    color_mode: str = "static"        # static | chase | spread | random
    color_beats: float = 4.0
    colors: list[str] = field(default_factory=list)
    gobo: str = "ouvert"
    dimmer: float = 1.0
    strobe: float = 0.0
    pan: float = 0.5
    tilt: float = 0.35
    speed: float = 0.0
    prism: bool = False
    focus: float = 0.5
    position_effect: str = "none"
    intensity_effect: str = "none"
    length: float = 4.0               # beats per effect cycle
    size: float = 0.6
    spread: float = 1.0
    energy: int = 2                   # 1 = calme, 2 = normal, 3 = gros son

    @classmethod
    def from_dict(cls, data: dict) -> "Look":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)


def default_looks() -> list[Look]:
    """A usable set of looks so the first gig works straight out of the box."""
    return [
        Look(id="l1", name="Ambiance", color="bleu", dimmer=0.55, tilt=0.4,
             position_effect="sweep", length=16, size=0.35, speed=0.6, energy=1),
        Look(id="l2", name="Couleurs lentes", color_mode="chase", color_beats=8,
             colors=["bleu", "rose", "cyan", "violet"], dimmer=0.7,
             position_effect="circle", length=16, size=0.4, speed=0.5, energy=1),
        Look(id="l3", name="Eventail", color="cyan", position_effect="fan",
             size=0.8, dimmer=0.9, tilt=0.3, energy=2),
        Look(id="l4", name="Vague", color="rose", intensity_effect="wave",
             position_effect="nod", length=4, size=0.8, dimmer=1.0, energy=2),
        Look(id="l5", name="Chenillard", color="rouge", intensity_effect="chase",
             length=1, position_effect="fan", size=0.7, energy=2),
        Look(id="l6", name="Huit rapide", color="vert", position_effect="figure8",
             length=4, size=0.7, dimmer=1.0, speed=0.0, energy=2),
        Look(id="l7", name="Croisement", color="blanc", position_effect="cross",
             length=2, size=0.9, dimmer=1.0, energy=2),
        Look(id="l8", name="Pulsation", color_mode="spread",
             colors=["rouge", "bleu", "vert", "jaune"],
             intensity_effect="pulse", length=1, size=1.0,
             position_effect="circle", prism=True, energy=3),
        Look(id="l9", name="Drop", color="blanc", intensity_effect="blinder",
             length=1, position_effect="random_pos", size=1.0, energy=3),
        Look(id="l10", name="Strobe rythme", color="blanc",
             intensity_effect="strobe_beat", length=1, size=1.0,
             position_effect="none", energy=3),
        Look(id="l11", name="Aleatoire", color_mode="random", color_beats=2,
             colors=["rouge", "vert", "bleu", "jaune", "cyan", "rose"],
             position_effect="random_pos", length=2, size=0.9, dimmer=1.0, energy=3),
        Look(id="l12", name="Plein feu", color="blanc", dimmer=1.0,
             position_effect="none", tilt=0.45, energy=2),
    ]


DEFAULT_CONFIG = {
    "output": {"driver": "dummy"},
    "fps": 40,
    "beats_per_bar": 4,
    "bpm": 128.0,
    "wizard_done": False,
}


class Show:
    def __init__(self, path: str = DEFAULT_SHOW_PATH,
                 library: ProfileLibrary | None = None) -> None:
        self.path = path
        self.library = library or ProfileLibrary()
        self.config: dict = json.loads(json.dumps(DEFAULT_CONFIG))
        self.fixtures: list[Fixture] = []
        self.looks: list[Look] = []
        self.load()

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        data: dict = {}
        if os.path.exists(self.path):
            try:
                with open(self.path, encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, ValueError) as exc:
                print(f"[show] {self.path} illisible ({exc}), configuration par defaut")
                data = {}

        config = dict(DEFAULT_CONFIG)
        config.update(data.get("config", {}))
        self.config = config

        self.fixtures = [self._fixture_from_dict(f) for f in data.get("fixtures", [])]
        if not self.fixtures:
            self.fixtures = self.default_patch()

        looks = [Look.from_dict(l) for l in data.get("looks", [])]
        self.looks = looks or default_looks()

    def save(self) -> None:
        payload = {
            "config": self.config,
            "fixtures": [f.to_dict() for f in self.fixtures],
            "looks": [l.to_dict() for l in self.looks],
        }
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        if os.path.exists(self.path):
            shutil.copyfile(self.path, self.path + ".bak")
        temporary = self.path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        os.replace(temporary, self.path)

    # -- patch -------------------------------------------------------------
    def default_patch(self) -> list[Fixture]:
        """Two BEAM 100 in 14 channel mode, addressed 1 and 15."""
        profile_id = "beam100_14ch" if self.library.get("beam100_14ch") else \
            next(iter(self.library.profiles), "beam100_14ch")
        footprint = self.library.get(profile_id).footprint if self.library.get(profile_id) else 14
        return [
            self._attach(Fixture(id="f1", name="Beam 1", profile_id=profile_id,
                                 address=1, order=0)),
            self._attach(Fixture(id="f2", name="Beam 2", profile_id=profile_id,
                                 address=1 + footprint, order=1)),
        ]

    def _fixture_from_dict(self, data: dict) -> Fixture:
        allowed = {f.name for f in fields(Fixture) if f.name != "profile"}
        fixture = Fixture(**{k: v for k, v in data.items() if k in allowed})
        return self._attach(fixture)

    def _attach(self, fixture: Fixture) -> Fixture:
        fixture.profile = self.library.get(fixture.profile_id)
        if fixture.profile is None:
            print(f"[show] profil inconnu pour {fixture.name} : {fixture.profile_id}")
        return fixture

    def sorted_fixtures(self) -> list[Fixture]:
        return sorted(self.fixtures, key=lambda f: (f.order, f.address))

    def set_patch(self, entries: list[dict]) -> None:
        fixtures = []
        for index, entry in enumerate(entries):
            entry = dict(entry)
            entry.setdefault("id", f"f{index + 1}")
            entry.setdefault("name", f"Lampe {index + 1}")
            entry.setdefault("order", index)
            entry["address"] = max(1, min(512, int(entry.get("address", 1))))
            fixtures.append(self._fixture_from_dict(entry))
        self.fixtures = fixtures

    def auto_patch(self, count: int, profile_id: str) -> list[int]:
        """Patch `count` identical lamps back to back. Returns their addresses.

        This is what the first-run wizard uses: the DJ says how many lamps they
        own, and gets the list of addresses to type into each lamp's menu.
        """
        profile = self.library.get(profile_id)
        footprint = profile.footprint if profile else 1
        entries = []
        address = 1
        for index in range(max(1, min(32, int(count)))):
            entries.append({
                "id": f"f{index + 1}",
                "name": f"Beam {index + 1}",
                "profile_id": profile_id,
                "address": address,
                "order": index,
            })
            address += footprint
        self.set_patch(entries)
        return [fixture.address for fixture in self.sorted_fixtures()]

    def patch_conflicts(self) -> list[str]:
        """Overlapping addresses are the classic 'why do they mirror' bug."""
        problems: list[str] = []
        used: dict[int, str] = {}
        for fixture in self.sorted_fixtures():
            if not fixture.enabled:
                continue
            if fixture.last_address > 512:
                problems.append(
                    f"{fixture.name} depasse le canal 512 (adresse {fixture.address})")
            for channel in range(fixture.address, min(fixture.last_address, 512) + 1):
                if channel in used and used[channel] != fixture.name:
                    problems.append(
                        f"{fixture.name} et {used[channel]} se chevauchent au canal {channel}")
                    break
                used[channel] = fixture.name
        return problems

    # -- looks -------------------------------------------------------------
    def get_look(self, look_id: str) -> Look | None:
        for look in self.looks:
            if look.id == look_id:
                return look
        return None

    def upsert_look(self, data: dict) -> Look:
        look = Look.from_dict(data)
        for index, existing in enumerate(self.looks):
            if existing.id == look.id:
                self.looks[index] = look
                return look
        self.looks.append(look)
        return look

    def delete_look(self, look_id: str) -> bool:
        before = len(self.looks)
        self.looks = [l for l in self.looks if l.id != look_id]
        return len(self.looks) != before
