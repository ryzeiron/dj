# beamctl — piloter tes BEAM 100 en soirée

Oui, c'est tout à fait faisable : tes BEAM 100 sont des projecteurs DMX512, et
n'importe quel ordinateur peut leur parler à condition d'avoir une petite
interface DMX entre les deux. C'est ce que fait ce logiciel.

Tu lances un programme sur ton portable, tu ouvres une page web (sur le portable
ou sur ton téléphone), et tu as devant toi des gros boutons de looks, un tap
tempo, un blackout et un strobe. Les mouvements et les chases sont calés sur le
BPM, donc les lumières suivent le morceau au lieu de tourner dans le vide.

- Aucune dépendance obligatoire : Python 3.9+ et c'est tout.
- L'interface web marche depuis le téléphone (même Wi-Fi) : tu peux régler la
  lumière depuis la piste.
- Mode simulation intégré : tu peux préparer ta soirée dans le train, sans lampe.

---

## 1. Ce qu'il te faut

| Élément | Détail |
|---|---|
| Interface DMX | c'est la seule pièce indispensable, voir ci-dessous |
| Câbles DMX | XLR 3 points, de l'interface vers la lampe 1, puis lampe 1 → lampe 2 |
| Bouchon de terminaison | résistance 120 Ω sur la dernière lampe — évite les mouvements parasites |

Trois familles d'interfaces, toutes gérées :

| Type | Exemples | Choix dans le logiciel |
|---|---|---|
| USB → DMX « Pro » | Enttec DMX USB Pro et clones | `enttec` (le plus fiable) |
| USB → DMX FTDI simple | Open DMX USB, dongles à ~20 € | `opendmx` |
| Réseau → DMX | boîtiers Art-Net ou sACN, filaire ou Wi-Fi | `artnet` / `sacn` |

Les deux interfaces USB ont besoin d'une bibliothèque en plus :

```bash
pip install pyserial
```

Art-Net et sACN ne demandent rien du tout. Un boîtier Art-Net Wi-Fi est la
solution la plus confortable en soirée : plus de câble USB à faire tomber.

## 2. Installation

```bash
git clone https://github.com/ryzeiron/dj.git
cd dj
python3 -m beamctl            # démarre en mode simulation
```

Puis ouvre <http://127.0.0.1:8080>. Le lien pour le téléphone est affiché au
démarrage.

## 3. Adresser les lampes

Sur chaque BEAM 100, dans le menu du projecteur, règle l'adresse DMX :

- Beam 1 → adresse **1**
- Beam 2 → adresse **15** (mode 14 canaux : 1 + 14)
- Beam 3 → adresse **29**, etc.

Mets les deux lampes dans le **même mode de canaux** (14 canaux de préférence),
et déclare le même mode dans l'onglet **Config → Patch**. Le logiciel prévient
si deux lampes se chevauchent.

## 4. Lancer pour de vrai

```bash
# boîtier Art-Net / sACN sur le réseau
python3 -m beamctl --output artnet --dmx-host 192.168.1.50

# interface USB
python3 -m beamctl --list-serial            # trouver le port
python3 -m beamctl --output enttec --serial-port /dev/ttyUSB0
python3 -m beamctl --output opendmx --serial-port COM3        # Windows
```

L'interface est aussi réglable dans l'onglet **Config**, sans relancer.

Options utiles : `--port 8080` (port web), `--bind 127.0.0.1` (n'écouter que
l'ordinateur), `--token moncode` (exige `?t=moncode` dans l'URL — pense-y si tu
es sur le Wi-Fi ouvert du lieu), `--show masoiree.json` (plusieurs configs).

## 5. En soirée

**Page Live**

- 12 **looks** : un clic, tout le rig change. Touches `1`–`9` et `0`.
- **TAP** (touche `T`) : tape 4 fois sur le kick, tout se cale dessus.
  `SYNC` recale le premier temps sur le drop.
- **BLACKOUT** (barre espace), **STROBE** (maintenir `S`), **FREEZE** (`F`).
- **Master** : l'intensité générale.
- Les réglages en direct (couleur, gobo, mouvement, amplitude, vitesse, pan,
  tilt) modifient le look en cours ; *enregistrer dans le look* les garde.

**Réglages d'un look**

| Réglage | Effet |
|---|---|
| Mouvement | balayage, cercle, huit, éventail, croisement, positions aléatoires |
| Intensité | chenillard, pulsation, vague, blinder, strobe rythmé |
| Vitesse | durée d'un cycle en temps (0,5 → 32) — c'est ça qui suit le BPM |
| Amplitude | à quel point les têtes bougent |
| Décalage | déphasage entre les lampes (0 = toutes ensemble) |
| Mode couleur | fixe, défilement, une couleur par lampe, aléatoire |

En quittant avec Ctrl+C, le logiciel envoie une trame noire : les lampes
s'éteignent proprement.

## 6. Si les lampes ne font pas ce qu'il faut

Les BEAM 100 sont vendus sous beaucoup de marques et les tables de canaux
varient. Les profils fournis (`beamctl/profiles/beam100_14ch.json` et
`beam100_11ch.json`) correspondent au mapping le plus répandu, mais **vérifie le
tien** :

1. Onglet **Config → Trouver les canaux**.
2. Choisis un canal, monte la valeur, regarde ce qui se passe sur la lampe.
3. Note à quoi sert chaque canal, puis corrige le fichier JSON du profil.

Le format est lisible : les numéros de canaux sont relatifs à l'adresse de la
lampe, exactement comme dans la notice.

```json
"dimmer": {"channel": 6},
"color":  {"channel": 8, "slots": {"blanc": 0, "rouge": 14, "bleu": 42}}
```

Symptômes courants :

- **Rien ne s'allume** : shutter/dimmer sur le mauvais canal, ou adresse DMX
  fausse, ou bouchon 120 Ω manquant.
- **Les têtes bougent par saccades** : câble micro utilisé à la place d'un câble
  DMX, ou pas de terminaison.
- **Les deux lampes font exactement pareil** : elles ont la même adresse.
- **Pan et tilt inversés** entre les deux lampes : coche *inverser pan* dans le
  patch pour celle qui est en face.

## 7. Organisation du code

| Fichier | Rôle |
|---|---|
| `beamctl/dmx.py` | l'univers DMX (512 canaux) |
| `beamctl/output.py` | Art-Net, sACN, Enttec Pro, Open DMX, simulation |
| `beamctl/fixtures.py` | profils de lampes et conversion état → DMX |
| `beamctl/effects.py` | mouvements et effets d'intensité calés sur le tempo |
| `beamctl/beat.py` | horloge de temps, tap tempo |
| `beamctl/engine.py` | boucle de rendu 40 images/seconde |
| `beamctl/show.py` | patch, looks, sauvegarde `show.json` |
| `beamctl/server.py` | serveur HTTP + API JSON |
| `beamctl/web/` | interface (HTML/CSS/JS, sans framework) |

Ta configuration est enregistrée dans `show.json` (avec une copie `.bak`) :
sauvegarde-le, c'est toute ta soirée.

## 8. Tests

```bash
python3 -m unittest discover -s tests
```

## 9. Ce que ça ne fait pas (encore)

- Pas de détection automatique du BPM par le micro : le tap tempo fait le job.
- Pas de contrôleur MIDI/USB : tout passe par la page web et le clavier.
- Un seul univers DMX (512 canaux, largement assez pour une trentaine de beams).
