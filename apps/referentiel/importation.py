"""Import versionné du référentiel (xlsx Site_File / Cell_File) et des cellules radio.

Règles :
- un secteur (``Cell_File.cells``) dont le site est absent de ``Site_File`` est rejeté ;
- doublons (codeSite, secteur) : la première ligne est conservée ;
- trigramme partagé par plusieurs sites : le premier site du fichier fait foi pour
  rattacher les cellules LTE (règle provisoire) ;
- chaque anomalie est consignée dans l'``ImportReferentiel`` créé.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from django.db import transaction

from .models import Cellule, ImportReferentiel, Secteur, Site
from .nommage import decoder_lte, decoder_wcdma, sites_wcdma_4_secteurs

COLONNES_SITE = ["codeSite", "Trigramme", "siteName", "commune", "region"]
COLONNES_SECTEUR = ["cells", "codeSite"]


@dataclass
class Rapport:
    anomalies: list[str] = field(default_factory=list)

    def signaler(self, message: str):
        self.anomalies.append(message)


def _texte(valeur) -> str:
    return "" if pd.isna(valeur) else str(valeur).strip()


def _nombre(valeur):
    return None if pd.isna(valeur) else valeur


def lire_referentiel(chemin: Path, rapport: Rapport) -> tuple[pd.DataFrame, pd.DataFrame]:
    sites = pd.read_excel(chemin, sheet_name="Site_File", dtype={"codeSite": str, "Trigramme": str})
    secteurs = pd.read_excel(chemin, sheet_name="Cell_File", dtype={"cells": str, "codeSite": str})
    for df, colonnes, onglet in ((sites, COLONNES_SITE, "Site_File"), (secteurs, COLONNES_SECTEUR, "Cell_File")):
        manquantes = [c for c in colonnes if c not in df.columns]
        if manquantes:
            raise ValueError(f"onglet {onglet} : colonnes manquantes {manquantes}")

    sites["codeSite"] = sites["codeSite"].map(_texte)
    sites = sites[sites["codeSite"] != ""]
    for code in sites.loc[sites["codeSite"].duplicated(), "codeSite"]:
        rapport.signaler(f"site {code} en double : première ligne conservée")
    sites = sites.drop_duplicates("codeSite")

    secteurs["cells"] = secteurs["cells"].map(_texte)
    secteurs["codeSite"] = secteurs["codeSite"].map(_texte)
    for code in secteurs.loc[secteurs["cells"].duplicated(), "cells"]:
        rapport.signaler(f"secteur {code} en double : première ligne conservée")
    secteurs = secteurs.drop_duplicates("cells")
    orphelins = ~secteurs["codeSite"].isin(sites["codeSite"])
    for code, site in secteurs.loc[orphelins, ["cells", "codeSite"]].itertuples(index=False):
        rapport.signaler(f"secteur {code} rejeté : site {site} absent de Site_File")
    return sites, secteurs[~orphelins]


def _numero_secteur(code: str, code_site: str) -> int | None:
    suffixe = code[len(code_site):] if code.startswith(code_site) else code[-1:]
    return int(suffixe) if suffixe.isdigit() else None


def lire_cellules(chemins: list[Path]) -> dict[str, list[str]]:
    """Noms de cellules distincts par techno, lus dans des exports KPI CSV."""
    cellules = {"LTE": set(), "WCDMA": set()}
    for chemin in chemins:
        entete = pd.read_csv(chemin, sep=";", nrows=0).columns
        if "EutranCell_Id" in entete:
            techno, colonne = "LTE", "EutranCell_Id"
        elif "CellWcdma" in entete:
            techno, colonne = "WCDMA", "CellWcdma"
        else:
            raise ValueError(f"{chemin} : ni EutranCell_Id ni CellWcdma dans l'en-tête")
        cellules[techno] |= set(pd.read_csv(chemin, sep=";", usecols=[colonne], dtype=str)[colonne].dropna())
    return {t: sorted(n) for t, n in cellules.items()}


@transaction.atomic
def importer(chemin: Path, fichiers_cellules: list[Path] = (), auteur=None) -> ImportReferentiel:
    rapport = Rapport()
    df_sites, df_secteurs = lire_referentiel(chemin, rapport)

    avant_sites = set(Site.objects.values_list("code_site", flat=True))
    avant_secteurs = set(Secteur.objects.values_list("code", flat=True))

    sites = {}
    for ligne in df_sites.to_dict("records"):
        site, _ = Site.objects.update_or_create(
            code_site=ligne["codeSite"],
            defaults={
                "trigramme": _texte(ligne.get("Trigramme")),
                "nom": _texte(ligne.get("siteName")),
                "commune": _texte(ligne.get("commune")),
                "region": _texte(ligne.get("region")),
                "nom_wcdma": _texte(ligne.get("siteNameWcdma")),
                "nom_lte": _texte(ligne.get("siteNameLte")),
                "latitude": _nombre(ligne.get("latWgs84")),
                "longitude": _nombre(ligne.get("lonWgs84")),
                "type_zone": _texte(ligne.get("bandType")),
                "nb_secteurs": _nombre(ligne.get("nbSect")),
            },
        )
        sites[site.code_site] = site

    secteurs = {}
    for ligne in df_secteurs.to_dict("records"):
        code, code_site = ligne["cells"], ligne["codeSite"]
        numero = _numero_secteur(code, code_site)
        if numero is None:
            rapport.signaler(f"secteur {code} rejeté : numéro de secteur illisible")
            continue
        secteur, _ = Secteur.objects.update_or_create(
            code=code,
            defaults={
                "site": sites[code_site],
                "numero": numero,
                "azimut": _nombre(ligne.get("azimut")),
                "province": _texte(ligne.get("province")),
            },
        )
        secteurs[(code_site, numero)] = secteur

    supprimes_sites = sorted(avant_sites - set(sites))
    supprimes_secteurs = sorted(avant_secteurs - {s.code for s in secteurs.values()})
    Secteur.objects.filter(code__in=supprimes_secteurs).delete()
    Site.objects.filter(code_site__in=supprimes_sites).delete()

    if fichiers_cellules:
        _importer_cellules(lire_cellules(list(fichiers_cellules)), df_sites, secteurs, rapport)

    return ImportReferentiel.objects.create(
        auteur=auteur,
        fichier=Path(chemin).name,
        nb_sites=len(sites),
        nb_secteurs=len(secteurs),
        ajouts=sorted(set(sites) - avant_sites) + sorted({s.code for s in secteurs.values()} - avant_secteurs),
        suppressions=supprimes_sites + supprimes_secteurs,
        anomalies=rapport.anomalies,
    )


def _importer_cellules(cellules, df_sites, secteurs, rapport: Rapport):
    # Trigramme -> premier site du fichier (règle provisoire pour les trigrammes partagés).
    site_par_trigramme = {}
    for code_site, trigramme in df_sites[["codeSite", "Trigramme"]].itertuples(index=False):
        trigramme = _texte(trigramme)
        if trigramme and trigramme in site_par_trigramme:
            rapport.signaler(f"trigramme {trigramme} partagé : {site_par_trigramme[trigramme]} retenu, {code_site} ignoré")
        site_par_trigramme.setdefault(trigramme, code_site)

    a_creer = []
    for nom in cellules["LTE"]:
        decodee = decoder_lte(nom)
        code_site = site_par_trigramme.get(decodee.prefixe) if decodee else None
        a_creer.append(_cellule(nom, "LTE", decodee, code_site, secteurs, rapport))

    quatre = sites_wcdma_4_secteurs(cellules["WCDMA"])
    for nom in cellules["WCDMA"]:
        decodee = decoder_wcdma(nom, quatre_secteurs=nom[:-1] in quatre)
        a_creer.append(_cellule(nom, "WCDMA", decodee, decodee and decodee.prefixe, secteurs, rapport))

    Cellule.objects.all().delete()
    Cellule.objects.bulk_create(a_creer)


def _cellule(nom, techno, decodee, code_site, secteurs, rapport: Rapport) -> Cellule:
    if decodee is None:
        rapport.signaler(f"cellule {techno} {nom} : nom non décodable")
        return Cellule(nom=nom, techno=techno)
    secteur = secteurs.get((code_site, decodee.secteur))
    if secteur is None:
        rapport.signaler(f"cellule {techno} {nom} : secteur {decodee.secteur} du site {code_site or decodee.prefixe} introuvable")
    return Cellule(nom=nom, techno=techno, secteur=secteur, porteuse=decodee.porteuse)
