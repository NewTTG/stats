"""Génération PowerPoint (python-pptx), charte bleu marine / ambre (brief §8).

Si ``settings.PPTX_MODELE`` désigne un fichier .pptx existant, ses dispositions
(« Titre » / « Title Slide », « Titre seul » / « Title Only ») et son thème sont
utilisés ; sinon la charte est dessinée par le code.
"""

import math
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu, Inches, Pt

MARINE = RGBColor(0x14, 0x28, 0x4B)
AMBRE = RGBColor(0xF0, 0xA5, 0x00)
GRIS = RGBColor(0x8A, 0x94, 0xA6)
BLANC = RGBColor(0xFF, 0xFF, 0xFF)
FOND_STATUT = {"alerte": RGBColor(0xFF, 0xF1, 0xCC), "critique": RGBColor(0xF8, 0xD0, 0xCC)}
COULEURS_SERIES = ["14284B", "F0A500", "2E86AB", "C0392B", "27AE60", "8E44AD", "7F8C8D", "D35400"]
LIGNES_PAR_TABLEAU = 14


def nombre(v, decimales=2) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:,.{decimales}f}".replace(",", " ").replace(".", ",")


def pourcentage(v) -> str:
    return "—" if v is None else f"{v:+.1f} %".replace(".", ",").replace("-", "−")


class Deck:
    def __init__(self):
        modele = getattr(settings, "PPTX_MODELE", None)
        self.avec_modele = bool(modele) and Path(modele).exists()
        self.prs = Presentation(modele) if self.avec_modele else Presentation()
        if self.avec_modele:
            for sld in list(self.prs.slides._sldIdLst):  # on ne garde que les dispositions
                self.prs.part.drop_rel(sld.rId)
                self.prs.slides._sldIdLst.remove(sld)
        else:
            self.prs.slide_width, self.prs.slide_height = Inches(13.333), Inches(7.5)
        self.largeur, self.hauteur = self.prs.slide_width, self.prs.slide_height
        self.marge = Inches(0.5)
        self.haut_contenu = Inches(1.35)

    # --------------------------------------------------------------- dispositions
    def _disposition(self, noms: tuple[str, ...]):
        for layout in self.prs.slide_layouts:
            if layout.name.lower() in noms:
                return layout
        return None

    def _diapo(self, titre: str):
        layout = self._disposition(("titre seul", "title only")) if self.avec_modele else None
        if layout is not None:
            slide = self.prs.slides.add_slide(layout)
            if slide.shapes.title is not None:
                slide.shapes.title.text = titre
                return slide
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6 if len(self.prs.slide_layouts) > 6 else -1])
        bandeau = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, self.largeur, Inches(1.0))
        bandeau.fill.solid()
        bandeau.fill.fore_color.rgb = MARINE
        bandeau.line.fill.background()
        filet = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(1.0), self.largeur, Inches(0.06))
        filet.fill.solid()
        filet.fill.fore_color.rgb = AMBRE
        filet.line.fill.background()
        self._texte(slide, titre, self.marge, Inches(0.2), self.largeur - 2 * self.marge, Inches(0.65),
                    taille=26, couleur=BLANC, gras=True)
        return slide

    def _texte(self, slide, texte, x, y, l, h, taille=14, couleur=MARINE, gras=False):
        boite = slide.shapes.add_textbox(x, y, l, h)
        tf = boite.text_frame
        tf.word_wrap = True
        for i, ligne in enumerate(texte.split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = ligne
            p.font.size, p.font.bold, p.font.color.rgb = Pt(taille), gras, couleur
        return boite

    # --------------------------------------------------------------- diapositives
    def titre(self, titre: str, lignes: list[str]):
        lignes = [*lignes, f"Généré le {timezone.localtime():%d/%m/%Y à %H:%M}"]
        layout = self._disposition(("titre", "title slide", "diapositive de titre")) if self.avec_modele else None
        if layout is not None:
            slide = self.prs.slides.add_slide(layout)
            slide.shapes.title.text = titre
            sous_titres = [p for p in slide.placeholders if p.placeholder_format.idx == 1]
            if sous_titres:
                sous_titres[0].text = "\n".join(lignes)
            return
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        fond = slide.background.fill
        fond.solid()
        fond.fore_color.rgb = MARINE
        self._texte(slide, titre, Inches(0.8), Inches(2.2), self.largeur - Inches(1.6), Inches(1.4),
                    taille=40, couleur=AMBRE, gras=True)
        self._texte(slide, "\n".join(lignes), Inches(0.8), Inches(3.8), self.largeur - Inches(1.6), Inches(2.5),
                    taille=18, couleur=BLANC)

    def tableau(self, titre: str, entetes: list[str], lignes: list[list], statuts: list[list[str]] | None = None,
                largeurs: list[float] | None = None):
        """Tableau paginé ; ``statuts`` colore chaque cellule (alerte / critique)."""
        if not lignes:
            slide = self._diapo(titre)
            self._texte(slide, "Aucune ligne.", self.marge, self.haut_contenu, Inches(6), Inches(0.5))
            return
        pages = [lignes[i:i + LIGNES_PAR_TABLEAU] for i in range(0, len(lignes), LIGNES_PAR_TABLEAU)]
        for n, page in enumerate(pages):
            slide = self._diapo(titre + (f" ({n + 1}/{len(pages)})" if len(pages) > 1 else ""))
            largeur = self.largeur - 2 * self.marge
            forme = slide.shapes.add_table(len(page) + 1, len(entetes), self.marge, self.haut_contenu,
                                           largeur, Inches(0.4) * (len(page) + 1))
            table = forme.table
            if largeurs:
                total = sum(largeurs)
                for j, l in enumerate(largeurs):
                    table.columns[j].width = Emu(int(largeur * l / total))
            for j, e in enumerate(entetes):
                c = table.cell(0, j)
                c.text = e
                c.fill.solid()
                c.fill.fore_color.rgb = MARINE
                para = c.text_frame.paragraphs[0]
                para.font.size, para.font.bold, para.font.color.rgb = Pt(12), True, BLANC
            for i, ligne in enumerate(page, start=1):
                for j, v in enumerate(ligne):
                    c = table.cell(i, j)
                    c.text = str(v)
                    c.text_frame.paragraphs[0].font.size = Pt(11)
                    statut = statuts[n * LIGNES_PAR_TABLEAU + i - 1][j] if statuts else ""
                    c.fill.solid()
                    c.fill.fore_color.rgb = FOND_STATUT.get(statut, BLANC)

    def graphique(self, titre: str, categories: list[str], series: list[dict], commentaire: str = ""):
        """``series`` : dicts {nom, valeurs, couleur?, pointille?}."""
        slide = self._diapo(titre)
        donnees = CategoryChartData()
        donnees.categories = categories
        for s in series:
            donnees.add_series(s["nom"], [None if v is None or (isinstance(v, float) and math.isnan(v)) else v
                                          for v in s["valeurs"]])
        hauteur = self.hauteur - self.haut_contenu - Inches(1.3 if commentaire else 0.5)
        graphe = slide.shapes.add_chart(XL_CHART_TYPE.LINE, self.marge, self.haut_contenu,
                                        self.largeur - 2 * self.marge, hauteur, donnees).chart
        graphe.has_legend = True
        graphe.legend.position = XL_LEGEND_POSITION.BOTTOM
        graphe.legend.include_in_layout = False
        graphe.legend.font.size = Pt(11)
        graphe.category_axis.tick_labels.font.size = Pt(10)
        graphe.value_axis.tick_labels.font.size = Pt(10)
        for i, (s, serie) in enumerate(zip(series, graphe.series)):
            serie.smooth = False
            ligne = serie.format.line
            ligne.color.rgb = RGBColor.from_string(s.get("couleur") or COULEURS_SERIES[i % len(COULEURS_SERIES)])
            ligne.width = Pt(1.25 if s.get("pointille") else 2.25)
            if s.get("pointille"):
                ligne.dash_style = MSO_LINE_DASH_STYLE.DASH
        if commentaire:
            self._texte(slide, commentaire, self.marge, self.hauteur - Inches(1.1),
                        self.largeur - 2 * self.marge, Inches(0.8), taille=14)

    def texte(self, titre: str, paragraphes: list[str]):
        slide = self._diapo(titre)
        self._texte(slide, "\n".join(paragraphes), self.marge, self.haut_contenu,
                    self.largeur - 2 * self.marge, self.hauteur - self.haut_contenu - self.marge, taille=12)

    def octets(self) -> bytes:
        flux = BytesIO()
        self.prs.save(flux)
        return flux.getvalue()
