"""Rapports PDF (reportlab, A4) : requête KPI et événement.

Même contenu que les rapports PowerPoint, mis en page pour la lecture et l'impression :
en-tête de page, paramètres, synthèse en cartes (valeur, statut, seuils), courbes par KPI,
répartition par cause, classements, tableaux et annexe des cellules sans données.

Polices standard du PDF (Helvetica) : aucun fichier de police à installer sur le serveur ;
les rares caractères hors de leur jeu (≈, →, −, espaces fines…) sont remplacés.
"""

import math
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

from apps.evenements.analyse import NIVEAUX, Analyse
from apps.kpi.export_excel import parametres
from apps.kpi.recherche import affichage
from apps.kpi.service import Resultat

from .powerpoint import nombre, pourcentage

PRIMAIRE = colors.HexColor("#3b5bdb")
ACCENT = colors.HexColor("#f59e0b")
TEXTE = colors.HexColor("#0f172a")
TEXTE_2 = colors.HexColor("#475467")
TEXTE_3 = colors.HexColor("#667085")
BORD = colors.HexColor("#e6e9f1")
FOND = colors.HexColor("#f8f9fc")
FOND_PRIMAIRE = colors.HexColor("#eef2ff")
STATUTS = {  # (trait, fond, texte)
    "ok": (colors.HexColor("#12b76a"), colors.HexColor("#ecfdf3"), colors.HexColor("#067647")),
    "alerte": (colors.HexColor("#f79009"), colors.HexColor("#fffaeb"), colors.HexColor("#b54708")),
    "critique": (colors.HexColor("#f04438"), colors.HexColor("#fef3f2"), colors.HexColor("#b42318")),
}
PALETTE = ["#3b5bdb", "#f59e0b", "#12b76a", "#8b5cf6", "#ef4444", "#06b6d4", "#ec4899", "#84cc16", "#0ea5e9",
           "#a16207", "#64748b", "#d946ef"]
LIBELLES_STATUT = {"ok": "OK", "alerte": "Alerte", "critique": "Critique"}
LIBELLES_REGLE = {"seuil": "Seuil dépassé", "ecart": "Écart à la référence",
                  "sans_donnees": "Données absentes", "saturation": "Saturation"}
REMPLACEMENTS = {"Σ ": "somme des ", "Σ": "somme", "≈": "~", "→": "–", "−": "-", " ": " ", " ": " ", "✨": "", "≥": ">=", "≤": "<=",
                 "▲": "+", "▼": "-", "━": "-", "×": "x"}
MAX_CELLULES_ANNEXE = 300
MAX_ANOMALIES = 200

_BASE = {"fontName": "Helvetica", "textColor": TEXTE, "leading": 13, "fontSize": 9.5}
STYLES = {
    "titre": ParagraphStyle("titre", **{**_BASE, "fontName": "Helvetica-Bold", "fontSize": 20, "leading": 25}),
    "sous_titre": ParagraphStyle("sous_titre", **{**_BASE, "fontSize": 11, "leading": 15, "textColor": TEXTE_2}),
    "h2": ParagraphStyle("h2", **{**_BASE, "fontName": "Helvetica-Bold", "fontSize": 14, "leading": 18,
                                  "spaceBefore": 10, "spaceAfter": 6}),
    "h3": ParagraphStyle("h3", **{**_BASE, "fontName": "Helvetica-Bold", "fontSize": 8, "leading": 11,
                                  "textColor": TEXTE_3, "spaceBefore": 10, "spaceAfter": 5}),
    "corps": ParagraphStyle("corps", **_BASE),
    "petit": ParagraphStyle("petit", **{**_BASE, "fontSize": 8, "leading": 10.5, "textColor": TEXTE_3}),
    "cellule": ParagraphStyle("cellule", **{**_BASE, "fontSize": 8, "leading": 10}),
    "cellule_droite": ParagraphStyle("cellule_droite", **{**_BASE, "fontSize": 8, "leading": 10, "alignment": TA_RIGHT}),
    "entete": ParagraphStyle("entete", **{**_BASE, "fontName": "Helvetica-Bold", "fontSize": 7, "leading": 9,
                                          "textColor": TEXTE_3}),
    "carte_libelle": ParagraphStyle("carte_libelle", **{**_BASE, "fontSize": 7.5, "leading": 9.5, "textColor": TEXTE_2}),
    "carte_valeur": ParagraphStyle("carte_valeur", **{**_BASE, "fontName": "Helvetica-Bold", "fontSize": 15, "leading": 19}),
    "carte_pied": ParagraphStyle("carte_pied", **{**_BASE, "fontSize": 6.8, "leading": 9, "textColor": TEXTE_3}),
}


def texte(valeur) -> str:
    """Texte prêt pour un ``Paragraph`` : caractères remplacés, jeu de la police, échappé."""
    s = "" if valeur is None else str(valeur)
    for a, b in REMPLACEMENTS.items():
        s = s.replace(a, b)
    return escape(s.encode("cp1252", "replace").decode("cp1252"))


def _p(valeur, style="corps") -> Paragraph:
    return Paragraph(texte(valeur), STYLES[style])


def _hexa(couleur) -> str:
    return couleur.hexval().replace("0x", "#")


# ------------------------------------------------------------------ document

class Document:
    """Document A4 : en-tête et pied de page sur chaque page, éléments ajoutés à la suite."""

    def __init__(self, titre: str):
        self.titre = titre
        self.flux = BytesIO()
        self.elements = []
        self.genere = timezone.localtime()
        self.doc = BaseDocTemplate(self.flux, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=20 * mm,
                                   bottomMargin=16 * mm, title=titre, author="Stats réseau — OPT", creator="Stats réseau")
        cadre = Frame(self.doc.leftMargin, self.doc.bottomMargin, self.doc.width, self.doc.height, id="corps",
                      leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.doc.addPageTemplates([PageTemplate(id="page", frames=[cadre], onPage=self._decor)])
        self.largeur = self.doc.width

    def _decor(self, canvas, doc):
        largeur, hauteur = A4
        canvas.saveState()
        haut = hauteur - 11 * mm
        canvas.setFillColor(PRIMAIRE)
        canvas.roundRect(doc.leftMargin, haut - 1.2 * mm, 5.5 * mm, 5.5 * mm, 1.4 * mm, stroke=0, fill=1)
        canvas.setStrokeColor(colors.white)
        canvas.setLineWidth(1.1)
        canvas.setLineCap(1)
        for i, h in enumerate((1.2, 2.2, 3.2)):
            x = doc.leftMargin + (1.6 + 1.15 * i) * mm
            canvas.line(x, haut, x, haut + h * mm)
        canvas.setFillColor(TEXTE)
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.drawString(doc.leftMargin + 7.5 * mm, haut + .4 * mm, "Stats réseau")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(TEXTE_3)
        titre = texte(self.titre).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        canvas.drawRightString(largeur - doc.rightMargin, haut + .4 * mm, titre[:110])
        canvas.setStrokeColor(BORD)
        canvas.setLineWidth(.6)
        canvas.line(doc.leftMargin, haut - 3.5 * mm, largeur - doc.rightMargin, haut - 3.5 * mm)
        canvas.line(doc.leftMargin, 11 * mm, largeur - doc.rightMargin, 11 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(doc.leftMargin, 7 * mm, f"OPT — usage interne · généré le {self.genere:%d/%m/%Y à %H:%M}")
        canvas.drawRightString(largeur - doc.rightMargin, 7 * mm, f"Page {doc.page}")
        canvas.restoreState()

    def ajouter(self, *elements):
        self.elements.extend(elements)

    # ------------------------------------------------------------ blocs
    def entete(self, titre: str, sous_titre: str = "", infos: list[tuple[str, str]] = ()):
        self.ajouter(_p(titre, "titre"))
        if sous_titre:
            self.ajouter(Spacer(1, 2), _p(sous_titre, "sous_titre"))
        if infos:
            cellules = [[Paragraph(f"<font color='{_hexa(TEXTE_3)}' size='7'>{texte(cle.upper())}</font><br/>{texte(val)}",
                                   STYLES["cellule"]) for cle, val in infos[i:i + 3]] for i in range(0, len(infos), 3)]
            for ligne in cellules:
                ligne += [""] * (3 - len(ligne))
            t = Table(cellules, colWidths=[self.largeur / 3] * 3)
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FOND), ("BOX", (0, 0), (-1, -1), .6, BORD),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 8)]))
            self.ajouter(Spacer(1, 10), t)
        self.ajouter(Spacer(1, 6))

    def section(self, titre: str, techno: str | None = None):
        badge = ""
        if techno:
            court = "4G" if techno == "LTE" else "3G"
            couleur = _hexa(PRIMAIRE) if techno == "LTE" else "#b45309"
            badge = f"<font color='{couleur}'>{court}</font>  "
        # Titre jamais seul en bas de page : il reste avec le début de son contenu (cartes, graphiques).
        self.ajouter(CondPageBreak(95 * mm), Paragraph(badge + texte(titre), STYLES["h2"]))

    def intertitre(self, titre: str):
        self.ajouter(Paragraph(texte(titre.upper()), STYLES["h3"]))

    def paragraphe(self, valeur: str, style: str = "corps"):
        self.ajouter(_p(valeur, style))

    def cartes(self, cartes: list[dict], colonnes: int = 3):
        """Cartes KPI : libellé, grande valeur et unité, statut et seuils ; liseré coloré selon le statut."""
        if not cartes:
            return
        largeur = (self.largeur - (colonnes - 1) * 6) / colonnes
        cellules, styles = [], []
        for c in cartes:
            pied = []
            if c.get("statut") in LIBELLES_STATUT:
                trait, _, couleur = STATUTS[c["statut"]]
                pied.append(f"<font color='{_hexa(couleur)}'><b>{LIBELLES_STATUT[c['statut']]}</b></font>")
            if c.get("approx"):
                pied.append("valeur approximative")
            if c.get("seuils"):
                pied.append(texte(c["seuils"]))
            if c.get("detail"):
                pied.append(texte(c["detail"]))
            interieur = Table([
                [Paragraph(texte(c["libelle"]) + (f"  <font color='{_hexa(TEXTE_3)}'>{texte(c['techno'])}</font>"
                                                  if c.get("techno") else ""), STYLES["carte_libelle"])],
                [Paragraph(f"{texte(c['texte'])} <font size='8.5' color='{_hexa(TEXTE_3)}'>{texte(c['unite'])}</font>",
                           STYLES["carte_valeur"])],
                [Paragraph(" · ".join(pied) or "&nbsp;", STYLES["carte_pied"])],
            ], colWidths=[largeur - 2])
            trait = STATUTS.get(c.get("statut"), (BORD,))[0]
            interieur.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), .6, BORD), ("LINEABOVE", (0, 0), (-1, 0), 2.2, trait),
                ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, 0), 6), ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
                ("TOPPADDING", (0, 1), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -2), 1)]))
            cellules.append(interieur)
        lignes = [cellules[i:i + colonnes] for i in range(0, len(cellules), colonnes)]
        lignes[-1] += [""] * (colonnes - len(lignes[-1]))
        grille = Table(lignes, colWidths=[largeur + (6 if i < colonnes - 1 else 0) for i in range(colonnes)])
        styles += [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                   ("RIGHTPADDING", (-1, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                   ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        grille.setStyle(TableStyle(styles))
        self.ajouter(grille)

    def grille(self, elements: list, colonnes: int = 2):
        """Éléments (graphiques, petits tableaux) côte à côte."""
        if not elements:
            return
        largeur = self.largeur / colonnes
        lignes = [elements[i:i + colonnes] for i in range(0, len(elements), colonnes)]
        lignes[-1] += [""] * (colonnes - len(lignes[-1]))
        t = Table(lignes, colWidths=[largeur] * colonnes)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        self.ajouter(t)

    def tableau(self, entetes: list[str], lignes: list[list], statuts: list[list[str]] | None = None,
                largeurs: list[float] | None = None, droite: set[int] = frozenset(), largeur: float | None = None):
        """Tableau paginé (en-tête répété) ; cellules colorées selon ``statuts`` (« alerte », « critique »)."""
        largeur = largeur or self.largeur
        poids = largeurs or [1] * len(entetes)
        colonnes = [largeur * p / sum(poids) for p in poids]
        donnees = [[Paragraph(texte(e.upper()), STYLES["entete"]) for e in entetes]]
        for ligne in lignes:
            donnees.append([Paragraph(texte(v), STYLES["cellule_droite" if i in droite else "cellule"])
                            for i, v in enumerate(ligne)])
        style = [("BACKGROUND", (0, 0), (-1, 0), FOND), ("LINEBELOW", (0, 0), (-1, 0), .6, BORD),
                 ("LINEBELOW", (0, 1), (-1, -1), .4, BORD), ("BOX", (0, 0), (-1, -1), .6, BORD),
                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 6),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
        for i, ligne in enumerate(statuts or [], start=1):
            for j, s in enumerate(ligne):
                if s in ("alerte", "critique"):
                    style.append(("BACKGROUND", (j, i), (j, i), STATUTS[s][1]))
        t = Table(donnees, colWidths=colonnes, repeatRows=1)
        t.setStyle(TableStyle(style))
        return t

    def octets(self) -> bytes:
        if not self.elements:
            self.ajouter(_p("Aucun contenu."))
        self.doc.build(self.elements)
        return self.flux.getvalue()


# ------------------------------------------------------------------ graphiques

def _pas_rond(etendue: float) -> float:
    brut = etendue / 4 or 1
    p = 10 ** math.floor(math.log10(abs(brut)))
    r = brut / p
    return (1 if r <= 1 else 2 if r <= 2 else 2.5 if r <= 2.5 else 5 if r <= 5 else 10) * p


def courbe(titre: str, categories: list[str], series: list[dict], largeur: float, hauteur: float = 58 * mm,
           unite: str = "", zero: bool = False, seuils: dict | None = None) -> Drawing:
    """Courbes (une par série : nom, valeurs, couleur, pointille, epaisseur) et seuils en pointillés."""
    valeurs = [v for s in series for v in s["valeurs"] if v is not None]
    d = Drawing(largeur, hauteur)
    d.add(Rect(0, 0, largeur, hauteur, rx=6, ry=6, fillColor=colors.white, strokeColor=BORD, strokeWidth=.6))
    place = largeur * (.55 if seuils else .95) - 8  # titre tronqué : jamais sous la légende des seuils
    titre = texte(titre).replace("&amp;", "&")
    if len(titre) * 4.5 > place:
        titre = titre[:max(int(place / 4.5) - 1, 8)] + "…"
    d.add(String(8, hauteur - 13, titre, fontName="Helvetica-Bold", fontSize=8, fillColor=TEXTE))
    if not valeurs or not categories:
        d.add(String(8, hauteur / 2, "Aucune donnée", fontName="Helvetica", fontSize=8, fillColor=TEXTE_3))
        return d
    lignes = [dict(s) for s in series]
    bas, haut = min(valeurs), max(valeurs)
    ecart = max(haut - bas, abs(haut) * .05, 1e-9)
    seuils = {k: v for k, v in (seuils or {}).items() if v is not None and bas - 2 * ecart <= v <= haut + 2 * ecart}
    bas, haut = min([bas, *seuils.values()]), max([haut, *seuils.values()])
    if zero:
        bas = min(0, bas)
    pas = _pas_rond((haut - bas) or abs(haut) or 1)
    vmin, vmax = math.floor(bas / pas) * pas, math.ceil((haut + pas * .1) / pas) * pas
    if unite == "%":
        vmin, vmax = max(0, vmin), min(100, vmax)
    if vmax <= vmin:  # valeurs constantes (ex. disponibilité à 100 %)
        if unite == "%" and vmax >= 100:
            vmin = max(0, vmax - pas)
        else:
            vmax = vmin + pas
    x_legende = largeur - 8
    for nom, couleur in (("critique", STATUTS["critique"][0]), ("alerte", STATUTS["alerte"][0])):
        if nom in seuils:  # légende des seuils en haut à droite
            libelle = f"- - {nom} {nombre(seuils[nom], 2 if abs(seuils[nom]) < 10 else 0)}"
            d.add(String(x_legende, hauteur - 13, libelle, fontName="Helvetica", fontSize=6.2, fillColor=couleur,
                         textAnchor="end"))
            x_legende -= 3.2 * len(libelle) + 8
    for nom, couleur in (("alerte", STATUTS["alerte"][0]), ("critique", STATUTS["critique"][0])):
        if nom in seuils:
            lignes.append({"nom": nom, "valeurs": [seuils[nom]] * len(categories), "couleur": couleur, "pointille": True,
                           "epaisseur": .8})
    graphe = HorizontalLineChart()
    legende = len(series) > 1
    graphe.x, graphe.y = 34, 18 + (12 if legende else 0)
    graphe.width, graphe.height = largeur - 44, hauteur - graphe.y - 22
    graphe.data = [[None if v is None else float(v) for v in s["valeurs"]] for s in lignes]
    pas_etiquette = max(1, math.ceil(len(categories) / 8))
    graphe.categoryAxis.categoryNames = [c if i % pas_etiquette == 0 else "" for i, c in enumerate(categories)]
    graphe.categoryAxis.labels.fontName = graphe.valueAxis.labels.fontName = "Helvetica"
    graphe.categoryAxis.labels.fontSize = graphe.valueAxis.labels.fontSize = 6.2
    graphe.categoryAxis.labels.fillColor = graphe.valueAxis.labels.fillColor = TEXTE_3
    graphe.categoryAxis.strokeColor = BORD
    graphe.categoryAxis.visibleTicks = False
    graphe.valueAxis.strokeColor = colors.transparent
    graphe.valueAxis.visibleGrid = True
    graphe.valueAxis.gridStrokeColor = BORD
    graphe.valueAxis.gridStrokeWidth = .4
    graphe.valueAxis.valueMin, graphe.valueAxis.valueMax, graphe.valueAxis.valueStep = vmin, vmax, pas
    graphe.valueAxis.labelTextFormat = lambda v: nombre(v, 0 if pas >= 1 else 2 if pas >= .01 else 3)
    graphe.joinedLines = 1
    for i, s in enumerate(lignes):
        ligne = graphe.lines[i]
        ligne.strokeColor = s.get("couleur") or colors.HexColor(PALETTE[i % len(PALETTE)])
        ligne.strokeWidth = s.get("epaisseur", 1.6 if len(series) > 1 else 2)
        if s.get("pointille"):
            ligne.strokeDashArray = (3, 2)
    d.add(graphe)
    if legende:
        x = 34
        for i, s in enumerate(series[:8]):
            couleur = s.get("couleur") or colors.HexColor(PALETTE[i % len(PALETTE)])
            d.add(Rect(x, 6, 6, 6, fillColor=couleur, strokeColor=None, rx=1, ry=1))
            nom = texte(s["nom"])[:22].replace("&amp;", "&")
            d.add(String(x + 9, 6.5, nom, fontName="Helvetica", fontSize=6.2, fillColor=TEXTE_2))
            x += 16 + 3.3 * len(nom)
            if x > largeur - 40:
                break
    return d


def barres_parts(barres: list[dict], largeur: float) -> Table:
    """Répartition par cause (Pareto) : libellé, barre proportionnelle, part et points."""
    max_part = max((b["part"] for b in barres), default=1) or 1
    largeur_barre = largeur * .42
    lignes = []
    for b in barres:
        d = Drawing(largeur_barre, 8)
        d.add(Rect(0, 1, largeur_barre, 6, rx=3, ry=3, fillColor=FOND_PRIMAIRE, strokeColor=None))
        couleur = colors.HexColor("#98a2b3") if b.get("non_ventile") else PRIMAIRE
        d.add(Rect(0, 1, max(largeur_barre * b["part"] / max_part, 1), 6, rx=3, ry=3, fillColor=couleur, strokeColor=None))
        lignes.append([_p(b["libelle"], "cellule"), d,
                       Paragraph(f"<b>{texte(nombre(b['part'], 1))} %</b> · {texte(b['texte'])} pt", STYLES["cellule_droite"])])
    t = Table(lignes, colWidths=[largeur * .36, largeur_barre + 6, largeur * .22 - 6])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def _annexe(doc: Document, par_techno):
    lignes = []
    for res in par_techno:
        if res.cellules_sans_donnees:
            liste = res.cellules_sans_donnees[:MAX_CELLULES_ANNEXE]
            suite = f" … (+{len(res.cellules_sans_donnees) - len(liste)})" if len(liste) < len(res.cellules_sans_donnees) else ""
            lignes.append((res.techno, f"{len(res.cellules_sans_donnees)} cellule(s) sans aucune donnée : "
                           + ", ".join(liste) + suite))
    if lignes:
        doc.section("Annexe — cellules sans données")
        for techno, ligne in lignes:
            doc.paragraphe(f"{techno} — {ligne}", "petit")
            doc.ajouter(Spacer(1, 4))


# ------------------------------------------------------------------ requête KPI

def pdf_requete(resultat: Resultat, titre: str | None = None, sous_titre: str = "") -> bytes:
    req = resultat.requete
    titre = titre or "Statistiques KPI réseau"
    doc = Document(titre)
    infos = [(cle, val) for cle, val in parametres(resultat) if cle != "Technologies"]
    infos.append(("Indicateurs", f"{len(req.kpis)} KPI"))
    doc.entete(titre, sous_titre or f"Du {req.periode.debut:%d/%m/%Y} au {req.periode.fin:%d/%m/%Y}", infos)

    blocs = affichage.blocs(resultat)
    synthese = affichage.synthese(blocs)
    if synthese:
        doc.section("Synthèse sur la période")
        for theme in synthese:
            doc.intertitre(theme["titre"])
            doc.cartes(theme["cartes"])
    for a in affichage.avertissements(resultat):
        doc.paragraphe(f"Avertissement — {a}", "petit")

    demi = doc.largeur / 2 - 6
    for bloc in blocs:
        res = bloc["res"]
        if not bloc["lignes"]:
            continue
        doc.section(f"Détail {bloc['nom']} — {res.cellules_demandees} cellule{'s' if res.cellules_demandees > 1 else ''}",
                    res.techno)
        for cause in bloc["causes"]:
            doc.intertitre(f"Répartition par cause — {cause['parent'].libelle}")
            doc.paragraphe(f"Total {cause['total_texte']} {cause['parent'].unite} : part de chaque cause dans les "
                           "coupures (et points de taux).", "petit")
            doc.ajouter(Spacer(1, 4), barres_parts(cause["barres"], doc.largeur))
            if cause["negligeables"]:
                doc.paragraphe(f"Négligeables (< {cause['seuil_negligeable']} % des coupures) : "
                               f"{', '.join(cause['negligeables'])}.", "petit")
        if bloc["classement"]:
            doc.intertitre(f"Classement par {bloc['espace']}")
            tableaux = []
            for cl in bloc["classement"]:
                lignes = [[i, str(l["entite"]), l["texte"], LIBELLES_STATUT.get(l["statut"], "")]
                          for i, l in enumerate(cl["lignes"], start=1)]
                statuts = [["", "", l["statut"], l["statut"]] for l in cl["lignes"]]
                tableaux.append([
                    _p(f"{cl['titre']} — {cl['kpi'].libelle}", "cellule"), Spacer(1, 3),
                    doc.tableau(["#", "Entité", "Valeur", "Statut"], lignes, statuts, [.5, 3.2, 1.6, 1.1], {0, 2},
                                largeur=demi)])
            doc.grille(tableaux)
        g = bloc["graphiques"]
        if len(g["periodes"]) > 1 and g["kpis"]:
            doc.intertitre("Évolution")
            if g["tronque"]:
                doc.paragraphe(f"Courbes des {g['nombre']} entités les plus dégradées (ou les plus chargées) par KPI.",
                               "petit")
            doc.grille([courbe(f"{k['titre']} ({k['unite']})", g["periodes"], k["series"], demi, unite=k["unite"],
                               zero=k["zero"], seuils=k["seuils"]) for k in g["kpis"]])
    if any(b["lignes_total"] for b in blocs):
        doc.ajouter(Spacer(1, 8))
        doc.paragraphe("Taux calculés en ratio de sommes (Σ numérateurs / Σ dénominateurs) sur tout le lieu et toute la "
                       "période, jamais en moyenne de taux. Le détail complet (toutes les périodes et entités) est dans "
                       "l'export Excel.", "petit")
    else:
        doc.paragraphe("Aucune donnée sur cette période pour ce périmètre.")
    _annexe(doc, resultat.par_techno)
    return doc.octets()


# ------------------------------------------------------------------ événement

def pdf_evenement(analyse: Analyse) -> bytes:
    e, niveau = analyse.evenement, NIVEAUX[analyse.niveau]
    debut, fin = analyse.creneaux[0][0], analyse.creneaux[-1][1]
    periode = f"le {debut:%d/%m/%Y}" if debut.date() == fin.date() else f"du {debut:%d/%m/%Y} au {fin:%d/%m/%Y}"
    doc = Document(e.nom)
    nb = len(analyse.creneaux)
    doc.entete(e.nom, f"{e.type + ' · ' if e.type else ''}{nb} créneau{'x' if nb > 1 else ''} {periode}", [
        ("Référence", f"{analyse.semaines} semaines précédentes"),
        ("Analyse", f"par {niveau.lower()}"),
        ("Cellules", ", ".join(f"{r.nb_cellules} {r.techno}" for r in analyse.par_techno) or "aucune"),
    ])
    if e.description:
        doc.paragraphe(e.description)
    doc.paragraphe("Créneaux : " + " ; ".join(
        f"{d:%d/%m/%Y %H:%M} – {f:%H:%M}" + (f" (le {f:%d/%m})" if f.date() != d.date() else "")
        for d, f in analyse.creneaux), "petit")
    for a in analyse.avertissements:
        doc.paragraphe(f"Avertissement — {a}", "petit")

    demi = doc.largeur / 2 - 6
    for res in analyse.par_techno:
        doc.section(f"{res.techno} — {res.nb_cellules} cellule{'s' if res.nb_cellules > 1 else ''}", res.techno)
        cartes = []
        for s in res.synthese:
            k = s.kpi
            v, unite = affichage.formater(s.valeur, k.unite)
            statut = s.statut or ("ok" if s.valeur is not None else "")
            cartes.append({"libelle": k.libelle, "texte": v, "unite": unite, "statut": statut,
                           "approx": k.qualite == "approx",
                           "detail": f"réf. {nombre(s.reference)} · écart {pourcentage(s.ecart_pct)}"})
        doc.intertitre("Synthèse événement / référence")
        doc.cartes(cartes)
        if res.instants:
            doc.intertitre("Courbes horaires — événement (bleu), référence (ambre), min–max des semaines (gris)")
            gris = colors.HexColor("#98a2b3")
            doc.grille([courbe(f"{c.kpi.libelle} ({c.kpi.unite})", res.instants, [
                {"nom": "Événement", "valeurs": c.evenement, "couleur": PRIMAIRE, "epaisseur": 2},
                {"nom": "Référence", "valeurs": c.reference, "couleur": ACCENT, "pointille": True},
                {"nom": "Réf. min", "valeurs": c.ref_min, "couleur": gris, "epaisseur": .7},
                {"nom": "Réf. max", "valeurs": c.ref_max, "couleur": gris, "epaisseur": .7},
            ], demi, unite=c.kpi.unite) for c in res.courbes])

    doc.section(f"Anomalies détectées ({len(analyse.anomalies)})")
    if analyse.anomalies:
        anomalies = analyse.anomalies[:MAX_ANOMALIES]
        doc.ajouter(doc.tableau(["Gravité", "Techno", niveau, "Règle", "Détail"],
                                [[a.gravite.capitalize(), a.techno, a.entite, LIBELLES_REGLE.get(a.regle, a.regle), a.message]
                                 for a in anomalies],
                                [[a.gravite, "", "", "", ""] for a in anomalies], [1.1, .9, 1.8, 1.8, 6]))
        if len(analyse.anomalies) > len(anomalies):
            doc.paragraphe(f"{len(anomalies)} premières anomalies sur {len(analyse.anomalies)} (liste complète dans le "
                           "rapport Excel).", "petit")
    else:
        doc.paragraphe("Aucune anomalie.")
    if analyse.classement:
        doc.section(f"{niveau}s les plus dégradés")
        doc.ajouter(doc.tableau(["#", "Techno", niveau, "Critiques", "Alertes", "Concerne"],
                                [[i, c["techno"], c["entite"], c["critiques"], c["alertes"], ", ".join(c["kpis"])]
                                 for i, c in enumerate(analyse.classement, start=1)],
                                largeurs=[.5, .9, 2, 1, 1, 5.5], droite={0, 3, 4}))
    _annexe(doc, analyse.par_techno)
    return doc.octets()
