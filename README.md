# beamctl — piloter tes BEAM 100 en soirée

Oui, c'est tout à fait faisable : tes BEAM 100 sont des projecteurs DMX512, et
n'importe quel ordinateur peut leur parler à condition d'avoir une petite
interface DMX entre les deux. C'est ce que fait ce logiciel.

Tu lances un programme sur ton portable, tu ouvres une page web (sur le portable
ou sur ton téléphone), et tu as devant toi un aperçu animé de tes lampes, des
gros boutons de looks, un tap tempo, un blackout et un strobe. Les mouvements et
les chases sont calés sur le BPM, donc les lumières suivent le morceau au lieu
de tourner dans le vide.

- **Assistant de démarrage** : trois questions au premier lancement et tout est
  réglé, y compris les adresses à saisir sur chaque lampe.
- **Pilote automatique** : *Chill*, *Normal* ou *Ça envoie* — le logiciel
  enchaîne les looks tout seul, en rythme, pendant que tu mixes.
- **Aperçu à l'écran** : tu vois les faisceaux bouger même sans lampe branchée,
  et tu peux viser ou dessiner la trajectoire directement dessus, au doigt.
- Aucune dépendance obligatoire : Python 3.9+ et c'est tout.
- L'interface web marche depuis le téléphone (même Wi-Fi) : tu peux régler la
  lumière depuis la piste.

---

## 1. Ce qu'il te faut

| Élément | Détail |
|---|---|
| Interface DMX | c'est la seule pièce indispensable, voir ci-dessous |
| Câbles DMX | XLR 3 points, de l'interface vers la lampe 1, puis lampe 1 → lampe 2 |
| Bouchon de terminaison | résistance 120 Ω sur la dernière lampe — évite les mouvements parasites |

**Le montage normal, tout en câble :**

```
PC ──USB──> boîtier USB-DMX ──XLR──> Beam 1 ──XLR──> Beam 2 ──> bouchon 120 Ω
```

Un PC n'a pas de sortie DMX : le petit boîtier USB-DMX est la pièce qui manque
entre les deux. Une fois qu'il est branché, tu n'as **rien à configurer** :

```bash
pip install pyserial          # une fois, pour l'USB
python -m beamctl --output usb
```

Le logiciel cherche le boîtier, reconnaît tout seul son protocole et s'y
connecte — y compris quand Windows lui change son numéro de port (COM3 un soir,
COM5 le lendemain).

| Type | Exemples | Choix dans le logiciel |
|---|---|---|
| **USB → DMX** | Enttec DMX USB Pro, Open DMX USB, dongles FTDI à ~20 € | **`usb`** (détection automatique) |
| Réseau → DMX | boîtiers Art-Net ou sACN | `artnet` / `sacn`, si un jour tu en veux |

Sur Windows, le boîtier doit apparaître comme un port COM dans le gestionnaire
de périphériques. Si ce n'est pas le cas, installe le **pilote VCP FTDI**
(ftdichip.com) — c'est le cas le plus fréquent de boîtier non détecté.

## 2. Installation locale

### Windows

1. **Python** — <https://www.python.org/downloads/>, et pendant l'installation
   **coche « Add python.exe to PATH »**. Si `python` ouvre le Microsoft Store :
   *Paramètres → Applications → Paramètres avancés → Alias d'exécution* et
   désactive `python.exe` et `python3.exe`. Ferme et rouvre le terminal.
2. **Le code**
   ```powershell
   git clone -b claude/beam-100-lighting-software-bbvzbl https://github.com/ryzeiron/dj.git
   cd dj
   ```
   Sans git : bouton **Code → Download ZIP** sur la page de la branche, puis dézippe.
3. **pyserial**, pour l'USB
   ```powershell
   py -m pip install pyserial
   ```
4. **Lancer** — double-clique `beamctl.bat`, ou :
   ```powershell
   py -m beamctl --output usb --open
   ```

### macOS / Linux

```bash
git clone -b claude/beam-100-lighting-software-bbvzbl https://github.com/ryzeiron/dj.git
cd dj
python3 -m pip install pyserial
./beamctl.sh
```

### Ce que tu dois voir

```
beamctl 1.0.0 — show : .../show.json
sortie DMX : Enttec DMX USB Pro sur COM3
lampes     : 2

  ordinateur : http://127.0.0.1:8080/
  telephone  : http://192.168.x.x:8080/
```

Si la ligne dit `aucune sortie (mode simulation)`, le boîtier n'a pas été
trouvé : le logiciel démarre quand même, tu peux tout préparer, mais rien ne
part vers les lampes. Voir la section 6.

Tout tourne sur ta machine : aucun compte, aucun serveur distant, aucune
connexion Internet nécessaire une fois le code téléchargé.

### Mettre à jour plus tard

```bash
git pull
```

Ton fichier `show.json` (lampes, looks, tracés) n'est pas suivi par git : il
reste intact.

## 3. Adresser les lampes

L'assistant fait ce calcul pour toi, mais voici la règle. Sur chaque BEAM 100,
dans le menu du projecteur, règle l'adresse DMX :

- Beam 1 → adresse **1**
- Beam 2 → adresse **15** (mode 14 canaux : 1 + 14)
- Beam 3 → adresse **29**, etc.

Mets les deux lampes dans le **même mode de canaux** (14 canaux de préférence),
et déclare le même mode dans l'onglet **Réglages → Mes lampes**. Le logiciel prévient
si deux lampes se chevauchent.

## 4. Lancer pour de vrai

```bash
# le cas normal : boîtier USB branché, détection automatique
python -m beamctl --output usb

# si jamais tu veux forcer un protocole et un port precis
python -m beamctl --list-serial                               # voir les ports
python -m beamctl --output enttec --serial-port COM3
python -m beamctl --output opendmx --serial-port /dev/ttyUSB0

# boîtier réseau, si un jour tu en utilises un
python -m beamctl --output artnet --dmx-host 192.168.1.50
```

L'interface est aussi réglable dans l'onglet **Réglages**, sans relancer.

Options utiles : `--port 8080` (port web), `--bind 127.0.0.1` (n'écouter que
l'ordinateur), `--token moncode` (exige `?t=moncode` dans l'URL — pense-y si tu
es sur le Wi-Fi ouvert du lieu), `--show masoiree.json` (plusieurs configs).

## 5. En soirée

**Page Live**

- 12 **looks** : un clic, tout le rig change. Touches `1`–`9` et `0`.
- **TAP** (touche `T`) : tape 4 fois sur le kick, tout se cale dessus.
  `SYNC` recale le premier temps sur le drop.
- **BLACKOUT** (barre espace), **STROBE** (maintenir `S`).
- **Luminosité** : l'intensité générale (`↑` / `↓`).
- **🎲 Surprise** (touche `R`) : invente un look à la volée. Si tu l'aimes,
  *garder* l'enregistre dans le look en cours.

**Piloter à la main, avec des points**

Trois outils au-dessus de l'aperçu :

| Outil | Ce que tu fais |
|---|---|
| 👁 Regarder | rien, tu observes |
| 🎯 Viser | tu glisses sur l'aperçu, les lampes suivent ton doigt |
| ✏️ Tracé | tu poses des points, les têtes tournent en boucle sur la courbe qui les relie |

Le tracé est une vraie trajectoire : les points sont reliés par une courbe
lisse et fermée, parcourue en rythme (la durée d'un tour est réglée par
*Vitesse*, l'*Amplitude* rétrécit ou agrandit la figure autour de son centre, et
le *Décalage* échelonne les lampes le long de la courbe). Glisse un point pour
déformer la figure en direct, `↩ dernier point` retire le dernier, `effacer le
tracé` revient aux mouvements préréglés. `garder dans le look` enregistre tout.

**Couleurs à points**

Tes BEAM 100 ont une roue de couleurs, donc un nombre fixe de teintes : chaque
point affiché est une de ces couleurs. Tu choisis d'abord comment elles
changent — *une seule*, *défilement*, *une par lampe*, *au hasard* — puis tu
cliques les couleurs pour construire ta palette, dans l'ordre. Un clic sur un
point de la palette l'enlève. Le curseur règle tous les combien de temps la
couleur change.

**Pilote automatique** — le bouton à connaître quand tu mixes seul :

| Mode | Ce qu'il fait |
|---|---|
| Je pilote | rien d'automatique, c'est toi qui cliques |
| Chill | change de look toutes les 16 mesures, parmi les looks calmes |
| Normal | toutes les 8 mesures, looks calmes et moyens |
| Ça envoie | toutes les 4 mesures, looks énergiques |

Les changements tombent sur une mesure, donc toujours en musique. Tu peux
reprendre la main à tout moment en cliquant un look (touche `A` pour basculer).

**Mode simple / mode expert**

Par défaut l'interface reste minimale. *Réglages → mode expert* fait apparaître
les sliders fins du look, le patch DMX détaillé, la recherche de canaux et
l'univers brut.

**Réglages d'un look** (mode expert)

| Réglage | Effet |
|---|---|
| Mouvement | balayage, cercle, huit, éventail, croisement, aléatoire, tracé perso |
| Intensité | chenillard, pulsation, vague, blinder, strobe rythmé |
| Vitesse | durée d'un cycle en temps (0,5 → 32) — c'est ça qui suit le BPM |
| Amplitude | à quel point les têtes bougent |
| Décalage | déphasage entre les lampes (0 = toutes ensemble) |
| Mode couleur | fixe, défilement, une couleur par lampe, aléatoire |
| Énergie | calme / normal / gros son — sert au pilote automatique |

En quittant avec Ctrl+C, le logiciel envoie une trame noire : les lampes
s'éteignent proprement.

## 6. Vérifier que le branchement fonctionne

**Important :** le DMX ne circule que dans un sens. Une lampe ne renvoie jamais
rien, donc **aucun logiciel au monde ne peut « détecter » un BEAM 100**. Ce qui
est vérifiable, c'est l'interface, le réseau, les adresses — et le fait qu'une
lampe donnée s'allume quand on lui parle.

En ligne de commande :

```bash
python -m beamctl --check
```

Il teste l'interface configurée, cherche le boîtier USB et identifie son
protocole (le modèle Enttec répond à une requête, les dongles simples restent
muets — c'est la seule chose qu'une interface DMX renvoie), et affiche les
adresses attendues. Il cherche aussi les boîtiers réseau, à ignorer si tu es
en USB.

Le même rapport est dans **Réglages → Vérifier mon installation**, avec un
bouton *utiliser* à côté de chaque boîtier trouvé pour le configurer d'un clic.

**Le seul vrai test des lampes** est visuel, lampe par lampe. Dans
*Réglages → Mes lampes*, le bouton **allumer** met une seule lampe en blanc
plein, tête au centre, et éteint toutes les autres :

- la bonne lampe s'allume → son adresse est correcte ;
- une autre lampe s'allume → tu as inversé deux adresses ;
- rien ne s'allume → voir la section suivante.

## 7. Si les lampes ne font pas ce qu'il faut

Les BEAM 100 sont vendus sous beaucoup de marques et les tables de canaux
varient. Les profils fournis (`beamctl/profiles/beam100_14ch.json` et
`beam100_11ch.json`) correspondent au mapping le plus répandu, mais **vérifie le
tien** :

1. Onglet **Réglages → mode expert → Trouver les canaux**.
2. Choisis un canal, monte la valeur, regarde ce qui se passe sur la lampe.
3. Note à quoi sert chaque canal, puis corrige le fichier JSON du profil.

Le format est lisible : les numéros de canaux sont relatifs à l'adresse de la
lampe, exactement comme dans la notice.

```json
"dimmer": {"channel": 6},
"color":  {"channel": 8, "slots": {"blanc": 0, "rouge": 14, "bleu": 42}}
```

Symptômes courants :

- **Rien ne s'allume** : commence par *Vérifier mon installation*. Si le boîtier
  n'est pas détecté, c'est le pilote FTDI qui manque, ou un autre logiciel
  (QLC+, une autre fenêtre beamctl) qui garde le port ouvert. Sinon : adresse
  DMX fausse, shutter/dimmer sur le mauvais canal, ou bouchon 120 Ω manquant.
- **Les têtes bougent par saccades** : câble micro utilisé à la place d'un câble
  DMX, ou pas de terminaison.
- **Les deux lampes font exactement pareil** : elles ont la même adresse.
- **Pan et tilt inversés** entre les deux lampes : coche *inverser pan* dans le
  patch pour celle qui est en face (mode expert).

## 8. Organisation du code

| Fichier | Rôle |
|---|---|
| `beamctl/dmx.py` | l'univers DMX (512 canaux) |
| `beamctl/output.py` | Art-Net, sACN, Enttec Pro, Open DMX, simulation |
| `beamctl/fixtures.py` | profils de lampes et conversion état → DMX |
| `beamctl/effects.py` | mouvements et effets d'intensité calés sur le tempo |
| `beamctl/beat.py` | horloge de temps, tap tempo |
| `beamctl/engine.py` | boucle de rendu 40 images/seconde |
| `beamctl/show.py` | patch, looks, sauvegarde `show.json` |
| `beamctl/diagnose.py` | vérification : interface, ports USB, découverte Art-Net |
| `beamctl/server.py` | serveur HTTP + API JSON |
| `beamctl/web/` | interface : aperçu canvas, assistant, looks (sans framework) |

Ta configuration est enregistrée dans `show.json` (avec une copie `.bak`) :
sauvegarde-le, c'est toute ta soirée.

## 9. Tests

```bash
python3 -m unittest discover -s tests
```

## 10. Ce que ça ne fait pas (encore)

- Pas de détection automatique du BPM par le micro : le tap tempo fait le job.
- Pas de contrôleur MIDI/USB : tout passe par la page web et le clavier.
- Un seul univers DMX (512 canaux, largement assez pour une trentaine de beams).
- Pas de détection des lampes : le DMX est unidirectionnel, c'est une limite du
  protocole, pas du logiciel.
