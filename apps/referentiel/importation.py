"""Import versionné du référentiel (xlsx, onglet Site_File) et des cellules radio.

Règles :
- seuls les sites (Site_File) sont lus dans le xlsx : commune, nom unifié (``siteName``)… ;
  l'onglet Cell_File n'est pas utilisé (numérotation des secteurs peu fiable) ;
- secteurs et cellules sont déduits des noms de cellules (cf. ``nommage``) et rattachés
  au site par le trigramme ; en 3G, par le codeSite s'il existe, sinon par le trigramme ;
- trigramme partagé par plusieurs sites : le premier site du fichier fait foi (provisoire) ;
- site à 4 secteurs : ``nbSect`` = 4, cellule 3G M, ou une porteuse LTE avec e1 à e4 ;
  les cellules qui changent de secteur à la bascule 3 -> 4 secteurs (D, e4…) gardent
  leur secteur d'avant dans ``secteur_avant`` ;
- chaque anomalie est consignée dans l'``ImportReferentiel`` créé.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from django.db import transaction

from .models import Cellule, ImportReferentiel, Secteur, Site
from .nommage import (decoder_lte, decoder_wcdma, lte_4_secteurs, lte_brut, prefixe_wcdma,
                      sites_wcdma_4_secteurs)

COLONNES_SITE = ["codeSite", "Trigramme", "siteName", "commune", "region"]


@dataclass
class Rapport:
    anomalies: list[str] = field(default_factory=list)

    def signaler(self, message: str):
        self.anomalies.append(message)


def _texte(valeur) -> str:
    return "" if pd.isna(valeur) else str(valeur).strip()


def _nombre(valeur):
    return None if pd.isna(valeur) else valeur


def lire_sites(chemin: Path, rapport: Rapport) -> pd.DataFrame:
    sites = pd.read_excel(chemin, sheet_name="Site_File", dtype={"codeSite": str, "Trigramme": str})
    manquantes = [c for c in COLONNES_SITE if c not in sites.columns]
    if manquantes:
        raise ValueError(f"onglet Site_File : colonnes manquantes {manquantes}")

    sites["codeSite"] = sites["codeSite"].map(_texte)
    sites = sites[sites["codeSite"] != ""]
    for code in sites.loc[sites["codeSite"].duplicated(), "codeSite"]:
        rapport.signaler(f"site {code} en double : première ligne conservée")
    return sites.drop_duplicates("codeSite")


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
def fusionner_cellules(*sources: dict[str, list[str]]) -> dict[str, list[str]]:
    return {t: sorted(set().union(*(s.get(t, []) for s in sources))) for t in ("LTE", "WCDMA")}


def importer(chemin: Path, fichiers_cellules: list[Path] = (), auteur=None,
             cellules: dict[str, list[str]] | None = None) -> ImportReferentiel:
    """``cellules`` : noms par techno lus ailleurs (base KPI), ajoutés à ceux des exports CSV."""
    rapport = Rapport()
    df_sites = lire_sites(chemin, rapport)

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

    supprimes_sites = sorted(avant_sites - set(sites))
    Site.objects.filter(code_site__in=supprimes_sites).delete()

    if fichiers_cellules or cellules:
        _importer_cellules(fusionner_cellules(lire_cellules(list(fichiers_cellules)), cellules or {}), sites, rapport)

    apres_secteurs = set(Secteur.objects.values_list("code", flat=True))
    return ImportReferentiel.objects.create(
        auteur=auteur,
        fichier=Path(chemin).name,
        nb_sites=len(sites),
        nb_secteurs=len(apres_secteurs),
        ajouts=sorted(set(sites) - avant_sites) + sorted(apres_secteurs - avant_secteurs),
        suppressions=supprimes_sites + sorted(avant_secteurs - apres_secteurs),
        anomalies=rapport.anomalies,
    )


def _site_par_trigramme(sites: dict[str, Site], rapport: Rapport) -> dict[str, str]:
    """Trigramme -> premier site du fichier (règle provisoire pour les trigrammes partagés)."""
    resultat = {}
    for code_site, site in sites.items():
        if site.trigramme and site.trigramme in resultat:
            rapport.signaler(f"trigramme {site.trigramme} partagé : {resultat[site.trigramme]} retenu, "
                             f"{code_site} ignoré")
        resultat.setdefault(site.trigramme, code_site)
    return resultat


def _rattacher(cellules, sites: dict[str, Site], rapport: Rapport) -> dict[tuple[str, str], str | None]:
    """(techno, cellule) -> code du site : trigramme en 4G ; codeSite, sinon trigramme, en 3G."""
    par_trigramme = _site_par_trigramme(sites, rapport)
    rattachement, signales = {}, set()
    for nom in cellules["LTE"]:
        brut = lte_brut(nom)
        code_site = par_trigramme.get(brut[0]) if brut else None
        if brut and code_site is None and brut[0] not in signales:
            signales.add(brut[0])
            rapport.signaler(f"trigramme {brut[0]} (cellules LTE) absent de Site_File")
        rattachement[("LTE", nom)] = code_site
    for nom in cellules["WCDMA"]:
        prefixe = prefixe_wcdma(nom)
        code_site = None
        if prefixe in sites:
            code_site = prefixe
        elif prefixe:
            code_site = par_trigramme.get(prefixe[:3])
            if prefixe not in signales:
                signales.add(prefixe)
                rapport.signaler(f"codeSite {prefixe} (cellules WCDMA) absent de Site_File"
                                 + (f" : rattaché à {code_site} par le trigramme" if code_site else ""))
        rattachement[("WCDMA", nom)] = code_site
    return rattachement


def sites_a_4_secteurs(rattachement: dict[tuple[str, str], str | None], sites: dict[str, Site]) -> set[str]:
    """Sites à 4 secteurs : ``nbSect`` >= 4, cellule 3G M, ou porteuse LTE avec e1 à e4."""
    quatre = {code for code, site in sites.items() if (site.nb_secteurs or 0) >= 4}
    par_site = {}
    for (techno, nom), code_site in rattachement.items():
        if code_site:
            par_site.setdefault((techno, code_site), []).append(nom)
    for (techno, code_site), noms in par_site.items():
        if techno == "WCDMA" and sites_wcdma_4_secteurs(noms):
            quatre.add(code_site)
        if techno == "LTE" and lte_4_secteurs(noms):
            quatre.add(code_site)
    return quatre


def _decoder(techno: str, nom: str, quatre_secteurs: bool):
    if techno == "LTE":
        return decoder_lte(nom, quatre_secteurs)
    return decoder_wcdma(nom, quatre_secteurs)


def _importer_cellules(cellules, sites: dict[str, Site], rapport: Rapport):
    rattachement = _rattacher(cellules, sites, rapport)
    quatre = sites_a_4_secteurs(rattachement, sites)
    for code_site in sorted(quatre):
        bascule = sites[code_site].bascule_4_secteurs
        rapport.signaler(f"site {code_site} : 4 secteurs"
                         + (f" depuis le {bascule:%d/%m/%Y}" if bascule else " (pas de date de passage renseignée)"))

    secteurs = {}

    def secteur(code_site: str, numero: int) -> Secteur:
        if (code_site, numero) not in secteurs:
            secteurs[(code_site, numero)], _ = Secteur.objects.update_or_create(
                code=f"{code_site}{numero}", defaults={"site": sites[code_site], "numero": numero})
        return secteurs[(code_site, numero)]

    a_creer = []
    for (techno, nom), code_site in rattachement.items():
        if code_site is None:
            if _decoder(techno, nom, False) is None:
                rapport.signaler(f"cellule {techno} {nom} : nom non décodable")
            a_creer.append(Cellule(nom=nom, techno=techno))
            continue
        actuel, avant = _decoder(techno, nom, code_site in quatre), None
        if code_site in quatre:
            avant = _decoder(techno, nom, False)
            if actuel is None:  # E, F… : n'existent qu'avant le passage à 4 secteurs
                actuel, avant = avant, None
            elif avant and avant.secteur == actuel.secteur:
                avant = None
        if actuel is None:
            rapport.signaler(f"cellule {techno} {nom} : nom non décodable")
            a_creer.append(Cellule(nom=nom, techno=techno))
            continue
        a_creer.append(Cellule(nom=nom, techno=techno, secteur=secteur(code_site, actuel.secteur),
                               porteuse=actuel.porteuse,
                               secteur_avant=secteur(code_site, avant.secteur) if avant else None))

    Cellule.objects.all().delete()
    Cellule.objects.bulk_create(a_creer)
    Secteur.objects.exclude(pk__in=[s.pk for s in secteurs.values()]).delete()
