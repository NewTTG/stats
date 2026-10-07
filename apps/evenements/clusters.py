"""Import ponctuel de l'onglet ``Cluster`` du référentiel comme base initiale d'événements.

Les clusters n'ont pas de dates : les événements créés sont à compléter (créneaux)
dans l'admin. Un cluster déjà présent (même nom) n'est pas modifié.
"""

from pathlib import Path

import pandas as pd
from django.db import transaction

from .models import Evenement


@transaction.atomic
def importer_clusters(chemin: Path, auteur=None) -> tuple[list[str], list[str]]:
    """Renvoie (événements créés, clusters ignorés car déjà présents)."""
    df = pd.read_excel(chemin, sheet_name="Cluster", dtype=str)
    manquantes = {"Cluster", "Cellule"} - set(df.columns)
    if manquantes:
        raise ValueError(f"onglet Cluster : colonnes manquantes {sorted(manquantes)}")
    df = df.dropna(subset=["Cluster", "Cellule"])
    crees, ignores = [], []
    for nom, groupe in df.groupby(df["Cluster"].str.strip(), sort=True):
        if Evenement.objects.filter(nom=nom).exists():
            ignores.append(nom)
            continue
        types = groupe["Type"].dropna().str.strip() if "Type" in groupe else pd.Series(dtype=str)
        Evenement.objects.create(
            nom=nom,
            type=types.mode().iloc[0] if len(types) else "",
            description="Importé de l'onglet Cluster du référentiel : créneaux à renseigner.",
            cellules=sorted(set(groupe["Cellule"].str.strip())),
            cree_par=auteur,
        )
        crees.append(nom)
    return crees, ignores
