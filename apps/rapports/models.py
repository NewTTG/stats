"""Rapports générés en tâche de fond (django-q2) et rapports enregistrés, éventuellement planifiés."""

from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


class RapportPlanifie(models.Model):
    """Requête KPI enregistrée : période relative (« semaine dernière »…), relancée à la demande
    ou automatiquement (chaque jour, chaque semaine, le 1er du mois)."""

    PERIODES = [("hier", "Hier"), ("7j", "7 derniers jours"), ("semaine_derniere", "Semaine dernière"),
                ("30j", "30 derniers jours"), ("mois_dernier", "Mois dernier"), ("mois_courant", "Ce mois-ci")]
    FREQUENCES = [("aucune", "Sur demande"), ("quotidienne", "Chaque jour"), ("hebdomadaire", "Chaque semaine"),
                  ("mensuelle", "Chaque mois (le 1er)")]
    FORMATS = [("pptx", "PowerPoint"), ("xlsx", "Excel")]

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                    related_name="rapports_planifies")
    titre = models.CharField(max_length=150)
    requete = models.JSONField(help_text="RequeteKpi ; sa période est recalculée à chaque lancement.")
    periode = models.CharField("période", max_length=20, choices=PERIODES, default="7j")
    format = models.CharField(max_length=8, choices=FORMATS, default="pptx")
    frequence = models.CharField("fréquence", max_length=16, choices=FREQUENCES, default="aucune")
    jour_semaine = models.PositiveSmallIntegerField(
        "jour", default=0, choices=list(enumerate(j.capitalize() for j in JOURS)))
    heure = models.PositiveSmallIntegerField(default=7, choices=[(h, f"{h} h") for h in range(24)])
    actif = models.BooleanField(default=True)
    prochain_lancement = models.DateTimeField("prochain lancement", null=True, blank=True)
    dernier_lancement = models.DateTimeField("dernier lancement", null=True, blank=True)
    cree_le = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        ordering = ["titre"]
        verbose_name = "rapport enregistré"
        verbose_name_plural = "rapports enregistrés"

    def __str__(self):
        return self.titre

    @property
    def planifie(self) -> bool:
        return self.frequence != "aucune"

    @property
    def description_frequence(self) -> str:
        if self.frequence == "quotidienne":
            return f"Chaque jour à {self.heure} h"
        if self.frequence == "hebdomadaire":
            return f"Chaque {JOURS[self.jour_semaine]} à {self.heure} h"
        if self.frequence == "mensuelle":
            return f"Le 1er du mois à {self.heure} h"
        return "Sur demande"

    def suivant(self, apres: datetime) -> datetime | None:
        """Premier lancement prévu strictement après ``apres`` (heure de Nouméa)."""
        if self.frequence == "aucune":
            return None
        local = timezone.localtime(apres)
        jour = local.date()
        for _ in range(400):
            if self._jour_prevu(jour):
                instant = timezone.make_aware(datetime.combine(jour, time(self.heure)))
                if instant > apres:
                    return instant
            jour += timedelta(days=1)
        return None

    def _jour_prevu(self, jour: date) -> bool:
        if self.frequence == "hebdomadaire":
            return jour.weekday() == self.jour_semaine
        if self.frequence == "mensuelle":
            return jour.day == 1
        return True

    def lien_ecran(self) -> str | None:
        """Affichage à l'écran (page des statistiques), sur la période relative ; None si la requête
        enregistrée est illisible."""
        r = self.requete if isinstance(self.requete, dict) else {}
        try:
            params = {"q": "", "kpis": [str(c) for c in r["kpis"]], "periode": self.periode,
                      "perimetre_type": r["perimetre"]["type"],
                      "perimetre_valeurs": ", ".join(r["perimetre"].get("valeurs") or [])}
        except (KeyError, TypeError, AttributeError):
            return None
        for cle in ("granularite_temps", "granularite_espace", "fenetre_horaire"):
            if isinstance(r.get(cle), str):
                params[cle] = r[cle]
        return reverse("kpi:requete") + "?" + urlencode(params, doseq=True)

    def planifier(self, maintenant: datetime | None = None):
        """Recalcule ``prochain_lancement`` (vide si inactif ou sur demande)."""
        self.prochain_lancement = self.suivant(maintenant or timezone.now()) if self.actif else None


class Rapport(models.Model):
    NATURES = [("requete", "Requête KPI"), ("evenement", "Événement")]
    FORMATS = [("pptx", "PowerPoint"), ("xlsx", "Excel")]
    STATUTS = [("en_attente", "En attente"), ("en_cours", "En cours"), ("termine", "Terminé"), ("erreur", "Erreur")]

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rapports")
    titre = models.CharField(max_length=200)
    nature = models.CharField(max_length=16, choices=NATURES)
    format = models.CharField(max_length=8, choices=FORMATS)
    parametres = models.JSONField(default=dict)
    statut = models.CharField(max_length=16, choices=STATUTS, default="en_attente")
    fichier = models.FileField(upload_to="rapports/%Y/%m/", blank=True)
    message = models.TextField(blank=True)
    planification = models.ForeignKey(RapportPlanifie, null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name="rapports", verbose_name="rapport enregistré")
    cree_le = models.DateTimeField("créé le", auto_now_add=True)
    termine_le = models.DateTimeField("terminé le", null=True, blank=True)

    class Meta:
        ordering = ["-cree_le"]
        verbose_name = "rapport généré"
        verbose_name_plural = "rapports générés"

    def __str__(self):
        return self.titre

    @property
    def en_cours(self) -> bool:
        return self.statut in ("en_attente", "en_cours")
