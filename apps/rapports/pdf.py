"""Rapports PDF autonomes : texte sélectionnable, tableaux paginés, courbes vectorielles."""

import math
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

import reportlab
from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, TableStyle, KeepTogether
from django.utils import timezone

from apps.kpi.export_excel import parametres
from apps.kpi.recherche.affichage import valeur
from apps.kpi.source import est_demo
from .powerpoint import nombre, pourcentage

VERT = colors.HexColor('#22644d')
PALETTE = ['#22644d', '#648aab', '#b19258', '#8a6ea8', '#519894', '#ba7070', '#698459', '#977c66', '#4f77bd', '#a1628a', '#858d64', '#687d87']
FONT_DIR = Path(reportlab.__file__).parent / 'fonts'
for nom, fichier in [('Stats', 'Vera.ttf'), ('StatsBold', 'VeraBd.ttf')]:
    if nom not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(nom, str(FONT_DIR / fichier)))
pdfmetrics.registerFontFamily('Stats', normal='Stats', bold='StatsBold', italic='Stats', boldItalic='StatsBold')
STYLES = {
    'titre': ParagraphStyle('titre', fontName='StatsBold', fontSize=24, leading=30, textColor=VERT, spaceAfter=16),
    'section': ParagraphStyle('section', fontName='StatsBold', fontSize=14, leading=19, textColor=VERT, spaceBefore=16, spaceAfter=10, keepWithNext=True),
    'texte': ParagraphStyle('texte', fontName='Stats', fontSize=9, leading=14, spaceAfter=7, textColor=colors.HexColor('#405a4e'), splitLongWords=True),
    'cellule': ParagraphStyle('cellule', fontName='Stats', fontSize=8, leading=11, splitLongWords=True),
    'entete': ParagraphStyle('entete', fontName='StatsBold', fontSize=8, leading=11, textColor=colors.white),
}


def p(texte, style='texte'):
    return Paragraph(escape(str(texte)), STYLES[style])


def tableau(titres, lignes, poids):
    largeur = A4[0] - 84
    data = [[p(c, 'entete') for c in titres]] + [[p(c, 'cellule') for c in ligne] for ligne in lignes]
    t = LongTable(data, colWidths=[largeur * w / sum(poids) for w in poids], repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), VERT), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f5f1')]),
        ('LINEBELOW', (0, 0), (-1, -1), .3, colors.HexColor('#dce7df')),
    ]))
    return t


def courbe(periodes, series):
    """Courbes avec ruptures pour données manquantes ; légende jusqu'à 12 séries."""
    series = series[:12]
    largeur = A4[0] - 84
    bas = 48 + 13 * math.ceil(len(series) / 2)
    haut = bas + 170
    d = Drawing(largeur, haut + 16)
    gauche, droite = 55, largeur - 8
    valeurs = [valeur(v) for s in series for v in s['valeurs']]
    valeurs = [v for v in valeurs if v is not None and math.isfinite(v)]
    if not valeurs:
        d.add(String(gauche, 150, 'Aucune donnée disponible', fontName='Stats', fontSize=10))
        return d
    lo, hi = min(0, min(valeurs)), max(valeurs)
    if hi == lo:
        hi = lo + 1
    hi += (hi - lo) * .08
    def x(n):
        return gauche + (droite - gauche) * n / max(1, len(periodes) - 1)
    def y(v):
        return bas + (haut - bas) * (v - lo) / (hi - lo)
    for n in range(5):
        v = lo + (hi - lo) * n / 4
        d.add(Line(gauche, y(v), droite, y(v), strokeColor=colors.HexColor('#e4ece5'), strokeWidth=.5))
        d.add(String(gauche - 7, y(v) - 3, nombre(v), fontName='Stats', fontSize=7, textAnchor='end'))
    if periodes:
        indices = sorted({round(n * (len(periodes) - 1) / 4) for n in range(5)})
        for n in indices:
            d.add(String(x(n), bas - 14, str(periodes[n]), fontName='Stats', fontSize=6.5, textAnchor='middle'))
    for i, serie in enumerate(series):
        couleur = colors.HexColor(PALETTE[i])
        points = []
        def tracer():
            if len(points) >= 4:
                d.add(PolyLine(list(points), strokeColor=couleur, strokeWidth=1.6))
            elif points:
                from reportlab.graphics.shapes import Circle
                d.add(Circle(points[0], points[1], 2, fillColor=couleur, strokeColor=couleur))
        for n, v in enumerate(serie['valeurs']):
            v = valeur(v)
            if v is None or not math.isfinite(v):
                tracer()
                points = []
            else:
                points.extend([x(n), y(v)])
        tracer()
        lx, ly = 12 + (i % 2) * largeur / 2, bas - 35 - (i // 2) * 13
        d.add(Line(lx, ly, lx + 14, ly, strokeColor=couleur, strokeWidth=2))
        d.add(String(lx + 20, ly - 3, str(serie['nom'])[:40], fontName='Stats', fontSize=7))
    return d


def _document(titre, elements):
    sortie = BytesIO()
    doc = SimpleDocTemplate(sortie, pagesize=A4, rightMargin=42, leftMargin=42,
                           topMargin=65, bottomMargin=48, title=titre, author='Stats réseau · OPT')
    genere = timezone.localtime().strftime('%d/%m/%Y %H:%M')
    def page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(VERT)
        canvas.setFont('StatsBold', 11)
        canvas.drawString(42, A4[1] - 32, 'Stats. / Intelligence réseau')
        canvas.setStrokeColor(colors.HexColor('#dce7df'))
        canvas.line(42, 35, A4[0] - 42, 35)
        canvas.setFont('Stats', 7)
        canvas.setFillColor(colors.HexColor('#6b8173'))
        canvas.drawString(42, 22, f'OPT · Usage interne · {genere} (Nouméa)')
        canvas.drawRightString(A4[0] - 42, 22, f'Page {doc.page}')
        canvas.restoreState()
    intro = [p(titre, 'titre')]
    if est_demo():
        intro.append(p('Données de démonstration (synthétiques) : valeurs fictives, sans lien avec le réseau réel.'))
    doc.build(intro + elements, onFirstPage=page, onLaterPages=page)
    return sortie.getvalue()


def _annexe(resultats):
    elements = [p('Annexe : cellules sans données', 'section')]
    for res in resultats:
        elements.append(p(f'{res.techno} : {len(res.cellules_sans_donnees)} cellule(s) sans données.'))
        # Paragraphes courts : la pagination fonctionne aussi pour de grands périmètres.
        for i in range(0, len(res.cellules_sans_donnees), 30):
            elements.append(p(', '.join(res.cellules_sans_donnees[i:i + 30])))
    return elements


def pdf_requete(resultat):
    from apps.kpi.views import donnees_graphiques
    elements = [p(f'{cle} : {v}') for cle, v in parametres(resultat)]
    for a in resultat.avertissements:
        elements.append(p(f'Avertissement : {a}'))
    for res in resultat.par_techno:
        elements.append(p(f'{res.techno} : Synthèse sur la période', 'section'))
        lignes = []
        for k in res.kpis:
            v = valeur(res.synthese_globale.get(k.code))
            lignes.append([k.libelle + (' ≈' if k.qualite == 'approx' else ''), nombre(v), k.unite,
                           k.statut(v).capitalize() or ('Sans données' if v is None else 'OK')])
        elements.append(tableau(['Indicateur', 'Valeur', 'Unité', 'Statut'], lignes, [6, 2, 1.5, 2]))
        for k in res.kpis:
            if k.note:
                elements.append(p(f'{k.libelle} : {k.note}'))
        graphes = donnees_graphiques(res, resultat.requete.granularite_temps)
        for g in graphes['kpis']:
            elements.append(KeepTogether([p(f"{res.techno} : {g['titre']}", 'section'), courbe(graphes['periodes'], g['series'])]))
        if graphes['tronque']:
            elements.append(p('Les graphiques sont limités aux 12 premières entités.'))
        if res.synthese is not None and not res.synthese.empty and len(res.synthese) > 1:
            for k in res.kpis:
                elements.append(p(f'{k.libelle} : détail par entité', 'section'))
                elements.append(tableau(['Entité', 'Valeur', 'Unité'],
                    [[e, nombre(v), k.unite] for e, v in res.synthese[k.code].items()], [6, 2, 2]))
    elements += _annexe(resultat.par_techno)
    return _document('Statistiques KPI réseau', elements)


def pdf_evenement(analyse):
    elements = [p(f'Analyse par {analyse.niveau} · Référence : {analyse.reference_libelle or str(analyse.semaines) + " semaines précédentes"}.')]
    for debut, fin in analyse.creneaux:
        debut = timezone.localtime(debut) if timezone.is_aware(debut) else debut
        fin = timezone.localtime(fin) if timezone.is_aware(fin) else fin
        elements.append(p(f'Créneau : {debut:%d/%m/%Y %H:%M} → {fin:%d/%m/%Y %H:%M}'))
    for a in analyse.avertissements:
        elements.append(p(f'Avertissement : {a}'))
    for res in analyse.par_techno:
        elements.append(p(f'{res.techno} : Synthèse événement / référence', 'section'))
        elements.append(tableau(['Indicateur', 'Événement', 'Référence', 'Unité', 'Écart', 'Statut'],
            [[s.kpi.libelle + (' ≈' if s.kpi.qualite == 'approx' else ''), nombre(s.valeur), nombre(s.reference), s.kpi.unite,
              pourcentage(s.ecart_pct), s.statut.capitalize() or ('Sans données' if s.valeur is None else 'OK')]
             for s in res.synthese], [5, 1.6, 1.6, 1, 1.5, 1.5]))
        for c in res.courbes:
            elements.append(KeepTogether([p(f'{res.techno} : {c.kpi.libelle} ({c.kpi.unite})', 'section'),
                courbe(res.instants, [{'nom': 'Événement', 'valeurs': c.evenement},
                                     {'nom': 'Référence', 'valeurs': c.reference},
                                     {'nom': 'Réf. min', 'valeurs': c.ref_min}, {'nom': 'Réf. max', 'valeurs': c.ref_max}])]))
    elements.append(p(f'Anomalies détectées ({len(analyse.anomalies)})', 'section'))
    if analyse.anomalies:
        elements.append(tableau(['Gravité', 'Techno', 'Entité', 'Règle', 'Détail'],
            [[a.gravite, a.techno, a.entite, a.regle, a.message] for a in analyse.anomalies], [1.5, 1, 2, 2, 5]))
    else:
        elements.append(p('Aucune anomalie.'))
    if analyse.classement:
        elements.append(p('Entités les plus dégradées', 'section'))
        elements.append(tableau(['Entité', 'Techno', 'Critiques', 'Alertes'],
            [[c['entite'], c['techno'], c['critiques'], c['alertes']] for c in analyse.classement], [5, 2, 2, 2]))
    elements += _annexe(analyse.par_techno)
    return _document(analyse.evenement.nom, elements)
