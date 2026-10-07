"""Export Excel d'un ``Resultat`` (brief §8) : onglet synthèse + données par technologie."""

import math
from io import BytesIO

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .service import Resultat

MARINE, AMBRE = "14284B", "F0A500"
REMPLISSAGE = {
    "alerte": PatternFill("solid", fgColor="FFF1CC"),
    "critique": PatternFill("solid", fgColor="F8D0CC"),
}
ENTETE = PatternFill("solid", fgColor=MARINE)
FORMAT_PERIODE = {"heure": "dd/mm/yyyy hh:mm", "jour": "dd/mm/yyyy", "semaine": "dd/mm/yyyy", "mois": "mm/yyyy"}
LIBELLES_FENETRE = {"journee": "Journée complète", "heure_chargee": "Heure chargée par cellule"}


def _valeur(v) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return float(v)


def _entete(ws, ligne: int, titres: list[str]):
    for col, titre in enumerate(titres, start=1):
        c = ws.cell(row=ligne, column=col, value=titre)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = ENTETE
        c.alignment = Alignment(wrap_text=True, vertical="center")


def _largeurs(ws, largeurs: list[int]):
    for i, l in enumerate(largeurs, start=1):
        ws.column_dimensions[get_column_letter(i)].width = l


def _titre_kpi(k) -> str:
    return f"{k.libelle} ({k.unite})" + (" ≈" if k.qualite == "approx" else "")


def description_requete(resultat: Resultat) -> list[tuple[str, str]]:
    r = resultat.requete
    p = r.perimetre
    fenetre = LIBELLES_FENETRE.get(r.fenetre_horaire, r.fenetre_horaire.replace("-", "h – ") + "h")
    return [
        ("Technologies", ", ".join(r.techno)),
        ("Périmètre", p.type + (f" : {', '.join(p.valeurs)}" if p.valeurs else "")),
        ("Période", f"{r.periode.debut:%d/%m/%Y} → {r.periode.fin:%d/%m/%Y}"),
        ("Fenêtre horaire", fenetre),
        ("Pas de temps", r.granularite_temps),
        ("Niveau d'agrégation", r.granularite_espace),
        ("Généré le", timezone.localtime().strftime("%d/%m/%Y %H:%M")),
    ]


def _onglet_synthese(ws, resultat: Resultat):
    ws.title = "Synthèse"
    ws["A1"] = "Synthèse KPI"
    ws["A1"].font = Font(bold=True, size=14, color=MARINE)
    ligne = 3
    for cle, valeur in description_requete(resultat):
        ws.cell(row=ligne, column=1, value=cle).font = Font(bold=True)
        ws.cell(row=ligne, column=2, value=valeur)
        ligne += 1

    ligne += 1
    _entete(ws, ligne, ["Techno", "KPI", "Unité", "Valeur", "Statut", "Cellules", "Sans données", "Remarque"])
    for res in resultat.par_techno:
        for k in res.kpis:
            ligne += 1
            v = _valeur(res.synthese.get(k.code))
            statut = k.statut(v)
            remarque = {"approx": "Valeur approximative", "reconstruit": "Valeur reconstruite"}.get(k.qualite, "")
            valeurs = [res.techno, k.libelle, k.unite, v, statut.capitalize() or ("OK" if v is not None else "—"),
                       res.cellules_demandees, len(res.cellules_sans_donnees), remarque]
            for col, val in enumerate(valeurs, start=1):
                ws.cell(row=ligne, column=col, value=val)
            c = ws.cell(row=ligne, column=4)
            c.number_format = "0.00"
            if statut:
                c.fill = ws.cell(row=ligne, column=5).fill = REMPLISSAGE[statut]

    if resultat.avertissements:
        ligne += 2
        ws.cell(row=ligne, column=1, value="Avertissements").font = Font(bold=True, color=AMBRE)
        for a in resultat.avertissements:
            ligne += 1
            ws.cell(row=ligne, column=1, value=a)
    _largeurs(ws, [22, 40, 8, 12, 10, 10, 13, 24])


def _onglet_donnees(wb, res, granularite_temps: str):
    ws = wb.create_sheet(f"Données {res.techno}")
    _entete(ws, 1, ["Période", "Entité", *(_titre_kpi(k) for k in res.kpis)])
    ws.freeze_panes = "C2"
    for i, ((periode, entite), valeurs) in enumerate(res.table.iterrows(), start=2):
        c = ws.cell(row=i, column=1, value=periode.to_pydatetime())
        c.number_format = FORMAT_PERIODE[granularite_temps]
        ws.cell(row=i, column=2, value=entite)
        for j, k in enumerate(res.kpis, start=3):
            v = _valeur(valeurs[k.code])
            c = ws.cell(row=i, column=j, value=v)
            c.number_format = "0.00"
            statut = k.statut(v)
            if statut:
                c.fill = REMPLISSAGE[statut]
    if res.table.shape[0]:
        ws.auto_filter.ref = ws.dimensions
    _largeurs(ws, [18, 24, *([18] * len(res.kpis))])


def _onglet_sans_donnees(wb, resultat: Resultat):
    lignes = [(r.techno, c) for r in resultat.par_techno for c in r.cellules_sans_donnees]
    if not lignes:
        return
    ws = wb.create_sheet("Cellules sans données")
    _entete(ws, 1, ["Techno", "Cellule"])
    for i, (techno, cellule) in enumerate(lignes, start=2):
        ws.cell(row=i, column=1, value=techno)
        ws.cell(row=i, column=2, value=cellule)
    _largeurs(ws, [10, 20])


def classeur(resultat: Resultat) -> bytes:
    wb = Workbook()
    _onglet_synthese(wb.active, resultat)
    for res in resultat.par_techno:
        _onglet_donnees(wb, res, resultat.requete.granularite_temps)
    _onglet_sans_donnees(wb, resultat)
    flux = BytesIO()
    wb.save(flux)
    return flux.getvalue()


def nom_fichier(resultat: Resultat) -> str:
    r = resultat.requete
    return f"kpi_{'_'.join(r.techno)}_{r.periode.debut:%Y%m%d}_{r.periode.fin:%Y%m%d}.xlsx".lower()
