"""Sites mobiles (remorques) déployés pour un événement : position, secteurs et cellules
déclarés dans l'événement (``Evenement.deploiements``), pas dans le référentiel.

Format enregistré, codes de site en clé (comme ``sites``, il survit aux rechargements) :
``{"1RM128": {"lat": -22.27, "lon": 166.44, "secteurs": [{"numero": 1, "azimut": 0,
"cellules": [["1RMe1", "LTE"], ["1RM128A", "WCDMA"]]}]}}``. Position facultative (la remorque
n'est alors pas dessinée) ; azimut vide : inconnu ; un seul secteur à 0° : omni (360°).
"""

import json

from django.core.exceptions import ValidationError

from apps.referentiel.models import Cellule, Site

TECHNOS = {"LTE", "WCDMA"}
MAX_SECTEURS = 9


def _nombre(valeur, libelle, mini, maxi, entier=False):
    if valeur in (None, ""):
        return None
    try:
        nombre = float(str(valeur).replace(",", "."))
    except ValueError:
        raise ValidationError(f"{libelle} : nombre attendu.") from None
    if entier:
        if nombre != int(nombre):
            raise ValidationError(f"{libelle} : nombre entier attendu.")
        nombre = int(nombre)
    if not mini <= nombre <= maxi:
        raise ValidationError(f"{libelle} : entre {mini} et {maxi}.")
    return nombre


def normaliser(brut) -> dict:
    """Déploiements saisis (JSON ou dict) -> format enregistré ; ``ValidationError`` sinon."""
    if brut in (None, ""):
        return {}
    if isinstance(brut, str):
        try:
            brut = json.loads(brut)
        except ValueError:
            raise ValidationError("Sites mobiles : données illisibles, rechargez la page.") from None
    if not isinstance(brut, dict):
        raise ValidationError("Sites mobiles : données illisibles, rechargez la page.")
    connus = dict(Site.objects.filter(code_site__in=list(brut), mobile=True).values_list("code_site", "nom"))
    resultat, erreurs, vues = {}, [], {}
    for code, dep in brut.items():
        if code not in connus:
            erreurs.append(f"{code} n'est pas un site mobile du référentiel.")
            continue
        nom = connus[code]
        try:
            resultat[code] = _deploiement(nom, dep if isinstance(dep, dict) else {})
        except ValidationError as e:
            erreurs.extend(e.messages)
            continue
        for sec in resultat[code]["secteurs"]:
            for cellule, techno in sec["cellules"]:
                if (techno, cellule) in vues and vues[(techno, cellule)] != code:
                    erreurs.append(f"{cellule} est déclarée sur deux remorques ({vues[(techno, cellule)]} et {code}).")
                vues[(techno, cellule)] = code
    if erreurs:
        raise ValidationError(erreurs)
    return resultat


def _deploiement(nom: str, dep: dict) -> dict:
    erreurs = []

    def lire(valeur, libelle, mini, maxi, entier=False):
        try:
            return _nombre(valeur, f"{nom}, {libelle}", mini, maxi, entier)
        except ValidationError as e:
            erreurs.extend(e.messages)
            return None

    lat = lire(dep.get("lat"), "latitude", -90, 90)
    lon = lire(dep.get("lon"), "longitude", -180, 180)
    if (lat is None) != (lon is None) and not erreurs:
        erreurs.append(f"{nom} : renseignez la latitude et la longitude, ou aucune des deux.")
    secteurs, numeros, cellules = [], set(), set()
    brut = dep.get("secteurs") if isinstance(dep.get("secteurs"), list) else []
    if len(brut) > MAX_SECTEURS:
        erreurs.append(f"{nom} : {MAX_SECTEURS} secteurs au plus.")
    for sec in brut[:MAX_SECTEURS]:
        sec = sec if isinstance(sec, dict) else {}
        if sec.get("numero") in (None, ""):
            erreurs.append(f"{nom} : numéro de secteur manquant.")
            continue
        numero = lire(sec.get("numero"), "n° de secteur", 1, MAX_SECTEURS, entier=True)
        if numero is None:
            continue
        if numero in numeros:
            erreurs.append(f"{nom} : secteur {numero} déclaré deux fois.")
            continue
        numeros.add(numero)
        azimut = lire(sec.get("azimut"), f"azimut du secteur {numero}", 0, 359, entier=True)
        liste = []
        for paire in sec.get("cellules") or []:
            cellule, techno = (list(paire) + ["", ""])[:2] if isinstance(paire, (list, tuple)) else ("", "")
            cellule = str(cellule).strip()
            if not cellule or len(cellule) > 32 or techno not in TECHNOS:
                erreurs.append(f"{nom}, secteur {numero} : cellule invalide ({cellule or 'sans nom'}).")
                continue
            if (techno, cellule) in cellules:
                erreurs.append(f"{nom} : {cellule} est déclarée dans deux secteurs.")
                continue
            cellules.add((techno, cellule))
            liste.append([cellule, techno])
        secteurs.append({"numero": numero, "azimut": azimut, "cellules": sorted(liste, key=lambda c: (c[1], c[0]))})
    if not cellules and not erreurs:
        erreurs.append(f"{nom} : rattachez au moins une cellule à un secteur.")
    if erreurs:
        raise ValidationError(erreurs)
    return {"lat": lat, "lon": lon, "secteurs": sorted(secteurs, key=lambda s: s["numero"])}


def cellules(deploiements: dict, techno: str | None = None) -> dict[str, tuple[str, int]]:
    """Cellule -> (code site, n° secteur) des remorques déployées (une techno, ou toutes)."""
    return {nom: (code, sec["numero"])
            for code, dep in deploiements.items() for sec in dep.get("secteurs", [])
            for nom, t in sec.get("cellules", []) if techno in (None, t)}


def entites(deploiements: dict, techno: str, niveau: str) -> dict[str, str]:
    """Cellule -> secteur (``<codeSite><n°>``) ou nom du site, selon la disposition déclarée."""
    declarees = cellules(deploiements, techno)
    if niveau == "secteur":
        return {nom: f"{code}{numero}" for nom, (code, numero) in declarees.items()}
    noms = dict(Site.objects.filter(code_site__in=list(deploiements)).values_list("code_site", "nom"))
    return {nom: noms.get(code, code) for nom, (code, _) in declarees.items()}


def sites_des_cellules(noms) -> set[str]:
    """Codes des sites mobiles auxquels le référentiel rattache ces cellules."""
    return set(Cellule.objects.filter(nom__in=list(noms), secteur__site__mobile=True)
               .values_list("secteur__site__code_site", flat=True))
