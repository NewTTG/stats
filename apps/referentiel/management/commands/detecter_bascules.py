"""Date de passage de 3 à 4 secteurs des sites, d'après l'historique journalier de la base KPI.

Sites concernés : ceux dont des cellules changent de secteur à la bascule (``secteur_avant``).
Date retenue : premier jour de données d'une cellule propre à la disposition en 4 secteurs
(4G : e4, e14… ; 3G : M). Si le site n'a pas de données plus anciennes, il est en
4 secteurs depuis le début de l'historique : aucune date n'est nécessaire.
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.kpi.source import lire, moteur_kpi
from apps.referentiel.models import Cellule, Site

DEBUT_HISTORIQUE = date(2000, 1, 1)


def premiers_jours(engine, techno: str, cellules: list[str]) -> dict[str, date]:
    df = lire(engine, techno, "jour", [], DEBUT_HISTORIQUE, date.today(), cellules)
    return {c: t.date() for c, t in df.groupby("cellule")["horodatage"].min().items()}


def detecter(engine) -> dict[str, date | None]:
    """Code site -> date de passage à 4 secteurs (None : 4 secteurs sur tout l'historique)."""
    sites = Site.objects.filter(secteurs__cellules__secteur_avant__isnull=False).distinct()
    resultat = {}
    for site in sites:
        cellules = Cellule.objects.filter(secteur__site=site)
        nouvelles = cellules.filter(Q(techno="LTE", secteur_avant__isnull=False)
                                    | Q(techno="WCDMA", nom__endswith="M"))
        premiers = {}
        for techno in ("LTE", "WCDMA"):
            noms = list(cellules.filter(techno=techno).values_list("nom", flat=True))
            premiers |= premiers_jours(engine, techno, noms)
        apparitions = [premiers[n] for n in nouvelles.values_list("nom", flat=True) if n in premiers]
        if not apparitions:
            continue
        bascule = min(apparitions)
        resultat[site.code_site] = bascule if min(premiers.values()) < bascule else None
    return resultat


class Command(BaseCommand):
    help = "Détecte, dans la base KPI, la date de passage de 3 à 4 secteurs des sites concernés."

    def add_arguments(self, parser):
        parser.add_argument("--enregistrer", action="store_true",
                            help="enregistre les dates trouvées (sinon : affichage seulement)")
        parser.add_argument("--remplacer", action="store_true",
                            help="remplace aussi les dates déjà renseignées dans l'administration")

    def handle(self, enregistrer, remplacer, **options):
        for code_site, bascule in sorted(detecter(moteur_kpi()).items()):
            site = Site.objects.get(code_site=code_site)
            texte = f"{bascule:%d/%m/%Y}" if bascule else "4 secteurs sur tout l'historique"
            actuelle = site.bascule_4_secteurs
            if enregistrer and (actuelle is None or remplacer) and bascule != actuelle:
                site.bascule_4_secteurs = bascule
                site.save(update_fields=["bascule_4_secteurs"])
                texte += " (enregistrée)"
            elif actuelle and actuelle != bascule:
                texte += f" (date renseignée conservée : {actuelle:%d/%m/%Y})"
            self.stdout.write(f"{code_site} : {texte}")
        if not enregistrer:
            self.stdout.write("Rien n'est enregistré sans --enregistrer.")
