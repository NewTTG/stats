"""Pages Réseau de l'application (/reseau/) : sites, secteurs et cellules du référentiel, consultés,
déclarés et modifiés hors de l'administration. Les sites mobiles (remorques) y sont signalés ;
leur position pendant un événement se déclare dans l'événement."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_safe

from apps.comptes.models import JournalAudit

from . import acces
from .edition import CellulesFormSet, SecteursFormSet, SiteForm, enregistrer, initial, valider
from .models import Cellule, Site, est_omni

FILTRES = {"tous": "Tous les sites", "mobiles": "Sites mobiles", "manuels": "Déclarés dans l'application"}


def _exiger(condition):
    if not condition:
        raise PermissionDenied


@login_required
@require_safe
def liste(request):
    _exiger(acces.peut_consulter(request.user))
    recherche = request.GET.get("recherche", "").strip()[:100]
    filtre = request.GET.get("filtre", "tous")
    if filtre not in FILTRES:
        filtre = "tous"
    sites = Site.objects.annotate(
        nb_secteurs_ref=Count("secteurs", distinct=True),
        nb_lte=Count("secteurs__cellules", filter=Q(secteurs__cellules__techno="LTE"), distinct=True),
        nb_wcdma=Count("secteurs__cellules", filter=Q(secteurs__cellules__techno="WCDMA"), distinct=True))
    if recherche:
        sites = sites.filter(Q(code_site__icontains=recherche) | Q(nom__icontains=recherche)
                             | Q(trigramme__iexact=recherche) | Q(commune__icontains=recherche)
                             | Q(secteurs__cellules__nom__iexact=recherche)).distinct()
    if filtre == "mobiles":
        sites = sites.filter(mobile=True)
    elif filtre == "manuels":
        sites = sites.filter(manuel=True)
    page = Paginator(sites.order_by("-mobile", "code_site"), 50).get_page(request.GET.get("page"))
    return render(request, "referentiel/liste.html", {
        "page": page, "recherche": recherche, "filtre": filtre, "filtres": FILTRES,
        "nb_mobiles": Site.objects.filter(mobile=True).count(),
        "peut_declarer": acces.peut_declarer(request.user),
    })


@login_required
@require_safe
def fiche(request, code):
    _exiger(acces.peut_consulter(request.user))
    site = get_object_or_404(Site, code_site=code)
    secteurs = list(site.secteurs.order_by("numero"))
    par_secteur = {}
    for c in Cellule.objects.filter(secteur__site=site).order_by("techno", "porteuse", "nom"):
        par_secteur.setdefault(c.secteur_id, []).append(c)
    lignes = [{"secteur": s, "omni": est_omni(s.azimut, len(secteurs)), "cellules": par_secteur.get(s.pk, [])}
              for s in secteurs]
    zone = None
    if site.latitude is not None and site.longitude is not None and secteurs:
        zone = {"sites": [{"code": site.code_site, "nom": site.nom, "lat": site.latitude, "lon": site.longitude,
                           "mobile": site.mobile, "nb_secteurs": len(secteurs), "secteurs": [
                               {"code": s.code, "numero": s.numero, "azimut": s.azimut, "etat": "choisi",
                                "cellules": str(len(par_secteur.get(s.pk, [])))} for s in secteurs]}]}
    return render(request, "referentiel/fiche.html", {
        "site": site, "lignes": lignes, "zone": zone, "evenements": _evenements(request.user, site),
        "carte_tuiles": settings.CARTE_TUILES_URL, "carte_attribution": settings.CARTE_TUILES_ATTRIBUTION,
        "peut_modifier": acces.peut_modifier(request.user),
        "peut_supprimer": acces.peut_supprimer(request.user, site),
    })


def _evenements(user, site):
    """Événements visibles qui couvrent le site (déployé, entier ou en partie)."""
    from apps.evenements.acces import evenements_visibles

    codes_secteurs = set(site.secteurs.values_list("code", flat=True))
    noms = set(Cellule.objects.filter(secteur__site=site).values_list("nom", flat=True))
    resultat = []
    for e in evenements_visibles(user).only("pk", "nom", "type", "sites", "secteurs", "cellules", "deploiements"):
        if site.code_site in (e.deploiements or {}):
            resultat.append((e, "déployé"))
        elif site.code_site in e.sites or codes_secteurs & set(e.secteurs) or noms & set(e.cellules):
            resultat.append((e, "inclus"))
    return resultat


@login_required
def edition(request, code=None):
    """Déclaration (``code`` vide) ou modification d'un site, de ses secteurs et de ses cellules."""
    if code is None:
        _exiger(acces.peut_declarer(request.user))
        site = Site()
        secteurs_init, cellules_init = [{"numero": 1, "azimut": None}], []
    else:
        _exiger(acces.peut_modifier(request.user))
        site = get_object_or_404(Site, code_site=code)
        secteurs_init, cellules_init = initial(site)
    donnees = request.POST if request.method == "POST" else None
    site_form = SiteForm(donnees, instance=site)
    secteurs = SecteursFormSet(donnees, initial=None if donnees else secteurs_init, prefix="secteurs")
    cellules = CellulesFormSet(donnees, initial=None if donnees else cellules_init, prefix="cellules", site=site)
    if donnees is not None and valider(site_form, secteurs, cellules):
        site = enregistrer(site_form, secteurs, cellules)
        JournalAudit.objects.create(utilisateur=request.user,
                                    action="declaration_site" if code is None else "modification_site",
                                    requete={"site": site.code_site, "mobile": site.mobile,
                                             "secteurs": sorted(secteurs.numeros()),
                                             "cellules": [c["nom"] for c in cellules.lignes()]})
        messages.success(request, f"Site {site.nom} ({site.code_site}) enregistré.")
        return redirect("reseau:fiche", site.code_site)
    return render(request, "referentiel/edition.html", {
        "site": site, "site_form": site_form, "secteurs": secteurs, "cellules": cellules,
        "erreurs": donnees is not None,
    })


@login_required
@require_POST
def supprimer(request, code):
    site = get_object_or_404(Site, code_site=code)
    _exiger(acces.peut_supprimer(request.user, site))
    noms = list(Cellule.objects.filter(secteur__site=site).values_list("nom", flat=True))
    Cellule.objects.filter(secteur__site=site).update(secteur=None, secteur_avant=None)
    JournalAudit.objects.create(utilisateur=request.user, action="suppression_site",
                                requete={"site": site.code_site, "cellules": noms})
    site.delete()
    messages.success(request, f"Site {site.nom} ({code}) supprimé ; ses cellules restent connues, non rattachées.")
    return redirect("reseau:liste")
