"""Bibliothèque modifiable des graphiques et modèles de rapports.

Le YAML reste la référence importée. Les réglages persistés sont relus à chaque
demande : aucun redémarrage ni cache de présentation à invalider.
"""
from django.db import transaction

from .catalogue import catalogue
from .graphes import DefinitionGraphe, Graphes, graphes
from .models import Graphique, ModeleRapport, SerieGraphique


def rapports_defaut():
    from .recherche.vocabulaire import vocabulaire

    defs = graphes()
    rapports = []
    for i in vocabulaire().rapports:
        codes = list(dict.fromkeys(c for t in i.technos_defaut for c in i.kpis.get(t, [])))
        graphiques = [g for g in defs.graphes if set(g.kpis) <= set(codes)]
        couverts = {c for g in graphiques for c in g.kpis}
        rapports.append(ModeleRapport(code=i.code, titre=i.rapport.titre, description=i.rapport.description,
                                     icone=i.rapport.icone, ordre=len(rapports),
                                     graphes=[g.code for g in graphiques],
                                     kpis=[c for c in codes if c not in couverts]))
    appels = vocabulaire().intentions.get("appels")
    if appels and not any(r.code == "appels" for r in rapports):
        rapports.append(ModeleRapport(code="appels", titre="Appels et voix", ordre=len(rapports), accueil=False,
                                     description="Appels voix 3G et repli voix depuis la 4G (CSFB).",
                                     kpis=[c for t in appels.technos_defaut for c in appels.kpis.get(t, [])]))
    return rapports


@transaction.atomic
def initialiser_bibliotheque():
    """Import idempotent, réservé à l'administration ; ne remplace aucune saisie."""
    existants = set(Graphique.objects.values_list("code", flat=True))
    for n, g in enumerate(graphes().graphes):
        if g.code in existants:
            continue
        objet, cree = Graphique.objects.get_or_create(code=g.code, defaults={
            "titre": g.titre, "theme": g.theme, "ordre": n})
        if cree:
            SerieGraphique.objects.bulk_create([
                SerieGraphique(graphique=objet, kpi=s.kpi, type=s.type, axe=s.axe, ordre=j)
                for j, s in enumerate(g.series)])
    existants = set(ModeleRapport.objects.values_list("code", flat=True))
    for r in rapports_defaut():
        if r.code in existants:
            continue
        ModeleRapport.objects.get_or_create(code=r.code, defaults={
            f: getattr(r, f) for f in ("titre", "description", "icone", "ordre", "accueil", "graphes", "kpis")})


def graphiques_configures(cat=None):
    cat = catalogue() if cat is None else cat
    defs = graphes()
    # Avant la première ouverture de l'éditeur, utiliser les définitions livrées.
    objets = list(Graphique.objects.prefetch_related("series"))
    if not objets:
        return defs
    resultat = []
    for obj in objets:
        series = list(obj.series.all())
        if not series or any(s.kpi not in cat for s in series):
            continue  # colonne retirée ou indicateur devenu indisponible
        technos = {cat[s.kpi].techno for s in series}
        if len(technos) != 1:
            continue
        resultat.append(DefinitionGraphe(code=obj.code, titre=obj.titre, theme=obj.theme,
                                        techno=technos.pop(), series=[{
                                            "kpi": s.kpi, "type": s.type, "axe": s.axe} for s in series]))
    return Graphes(themes=defs.themes, graphes=resultat)


def modeles_rapports():
    return list(ModeleRapport.objects.all()) or rapports_defaut()


def catalogue_graphique(cat):
    """Ne proposer que les graphiques dont toutes les séries sont autorisées."""
    return [g for g in graphiques_configures().graphes if set(g.kpis) <= set(cat)]


def contenu_rapport(rapport, cat, definitions=None):
    defs = definitions if definitions is not None else catalogue_graphique(cat)
    par_code = {g.code: g for g in defs}
    selection = [c for c in rapport.graphes if c in par_code]
    kpis = list(dict.fromkeys([c for c in rapport.kpis if c in cat] +
                             [c for g in selection for c in par_code[g].kpis]))
    return selection, kpis


def preparer_selection(get, cat):
    """Résout le choix de graphiques en KPI, avant l'interprétation habituelle.

    None signifie l'affichage historique automatique ; [] signifie un choix
    explicite sans graphique composé. Les droits restent vérifiés par le moteur.
    """
    selection = None
    defs = catalogue_graphique(cat)
    if set(get.getlist("graphes")) - {g.code for g in defs}:
        raise ValueError("Un graphique demandé est inconnu ou n’est pas accessible dans votre périmètre.")
    technos = set(get.getlist("techno")) & {"LTE", "WCDMA"}
    if technos:
        defs = [g for g in defs if g.techno in technos]
        cat = {c: k for c, k in cat.items() if k.techno in technos}
    par_code = {g.code: g for g in defs}
    if get.get("graphiques_personnalises") == "1" or get.getlist("graphes"):
        selection = list(dict.fromkeys(c for c in get.getlist("graphes") if c in par_code))
        kpis = list(dict.fromkeys([c for c in get.getlist("kpis") if c in cat] +
                                 [c for g in selection for c in par_code[g].kpis]))
        get.setlist("kpis", kpis)
        if not kpis:
            raise ValueError("Choisissez au moins un graphique ou un indicateur pour les technologies demandées.")
    elif not get.getlist("kpis"):
        intentions = get.getlist("intention")
        rapports = [r for r in modeles_rapports() if r.code in intentions]
        if rapports:
            selection, kpis = [], []
            for r in rapports:
                gs, ks = contenu_rapport(r, cat, defs)
                selection += gs
                kpis += ks
            selection = list(dict.fromkeys(selection))
            get.setlist("kpis", list(dict.fromkeys(kpis)))
            if not kpis:
                raise ValueError("Ce rapport ne contient aucun indicateur accessible pour les technologies demandées.")
    if selection is not None:
        get.setlist("graphes", selection)
        get["graphiques_personnalises"] = "1"
    return selection
