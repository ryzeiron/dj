#!/usr/bin/env python3
"""Point d'entree direct : `python run.py`.

Equivalent de `python -m beamctl`, mais utilisable quand le dossier du projet
n'est pas dans le chemin de recherche — cas d'un Python portable, ou d'un
double-clic sur ce fichier.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from beamctl.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
