"""Configuration des graphiques et rapports : enregistrement, droits et résultat réel."""
import pytest
from django.contrib.auth.models import Permission, User
from django.http import QueryDict
from django.urls import reverse

from apps.kpi.catalogue import catalogue
from apps.kpi.composition import initialiser_bibliotheque, graphiques_configures, preparer_selection
from apps.kpi.forms import RequeteForm, champs_depuis_requete
from apps.kpi.models import Graphique, ModeleRapport
from apps.kpi.requete import RequeteKpi
from apps.rapports.models import RapportPlanifie

from .test_recherche_regles import ref_recherche  # noqa: F401
from .test_recherche_vues import admin, base_recherche  # noqa: F401

pytestmark = pytest.mark.django_db


def _post_graphe(obj, series):
    return {"titre": "Volume et débit personnalisés", "theme": "trafic",
            "series-TOTAL_FORMS": len(series), "series-INITIAL_FORMS": obj.series.count(),
            "series-MIN_NUM_FORMS": 1, "series-MAX_NUM_FORMS": 1000,
            **{f"series-{n}-{k}": v for n, s in enumerate(series) for k, v in s.items()}}


def _series(obj):
    return [{"id": s.pk, "graphique": obj.pk, "kpi": s.kpi, "type": s.type, "axe": s.axe, "ordre": s.ordre}
            for s in obj.series.all()]


def test_import_et_edition_graphique(admin):
    page = admin.get(reverse("admin:kpi_graphique_changelist"))
    assert page.status_code == 200
    assert Graphique.objects.count() == 101
    g = Graphique.objects.get(code="lte_volume_dl")
    url = reverse("admin:kpi_graphique_change", args=[g.pk])
    assert b"indicateurs-apercu" in admin.get(url).content
    series = _series(g)
    series[0].update(type="aire", ordre=2)
    series[1].update(ordre=1)
    assert admin.post(url, _post_graphe(g, series)).status_code == 302
    initialiser_bibliotheque()
    cfg = next(x for x in graphiques_configures().graphes if x.code == g.code)
    assert cfg.titre == "Volume et débit personnalisés"
    assert cfg.series[-1].type == "aire"
    assert cfg.kpis == ["lte_debit_cellule_dl", "lte_payload_dl"]
    assert Graphique.objects.count() == 101


@pytest.mark.parametrize("erreur", ["unites", "technos", "doublon", "vide"])
def test_series_invalides_ne_modifient_pas_le_graphique(admin, erreur):
    initialiser_bibliotheque()
    g = Graphique.objects.get(code="lte_volume_dl")
    series = _series(g)
    if erreur == "unites": series[1]["axe"] = "gauche"
    if erreur == "technos": series[1]["kpi"] = "wcdma_sms"
    if erreur == "doublon": series[1]["kpi"] = series[0]["kpi"]
    if erreur == "vide":
        for s in series: s["DELETE"] = "on"
    r = admin.post(reverse("admin:kpi_graphique_change", args=[g.pk]), _post_graphe(g, series))
    assert r.status_code == 200
    assert r.context["inline_admin_formsets"][0].formset.non_form_errors()
    g.refresh_from_db()
    assert g.titre == "Volume et débit cellule DL"


def test_rapport_selection_ordre_accueil_et_resultat(admin, base_recherche):
    initialiser_bibliotheque()
    r = ModeleRapport.objects.get(code="rapport_data")
    ModeleRapport.objects.exclude(pk=r.pk).update(ordre=10)
    selection = ["lte_prb", "lte_volume_dl"]
    url = reverse("admin:kpi_modelerapport_change", args=[r.pk])
    post = {"titre": "Ma data 4G", "description": "Charge et téléchargement", "ordre": 0,
            "accueil": "on", "graphes": selection, "kpis": []}
    assert admin.post(url, post).status_code == 302
    r.refresh_from_db()
    assert r.graphes == selection
    home = admin.get("/")
    assert home.context["rapports_types"][0]["titre"] == "Ma data 4G"
    page = admin.get("/", {"q": "Nouméa", "intention": r.code, "periode": "semaine_derniere"})
    assert page.status_code == 200
    req = page.context["requete"]
    assert req.graphes == selection
    assert set(req.kpis) == {"lte_prb_dl_util", "lte_prb_ul_util", "lte_payload_dl", "lte_debit_cellule_dl"}
    assert "Ma data 4G : Nouméa" in page.content.decode()
    blocs = page.context["blocs"]
    assert len(blocs) == 1
    assert [g["code"] for t in blocs[0]["graphes_themes"]["themes"] for g in t["graphes"]] == selection
    assert not blocs[0]["graphiques"]["kpis"]  # pas de courbes individuelles dupliquées
    post.pop("accueil")
    assert admin.post(url, post).status_code == 302
    assert r.code not in [r["code"] for r in admin.get("/").context["rapports_types"]]
    assert admin.get("/", {"q": "", "intention": r.code, "periode": "7j"}).context["requete"].graphes == selection


def test_selection_sur_mesure_exacte_et_techno(admin, base_recherche):
    r = admin.get("/", {"q": "Nouméa", "periode": "semaine_derniere", "graphes": ["lte_volume_dl"]})
    assert r.status_code == 200
    assert r.context["requete"].graphes == ["lte_volume_dl"]
    assert len(r.context["blocs"]) == 1
    assert [g["code"] for t in r.context["blocs"][0]["graphes_themes"]["themes"] for g in t["graphes"]] == ["lte_volume_dl"]
    r = admin.get("/", {"q": "", "intention": "rapport_detail_trafic", "techno": "WCDMA", "periode": "7j"})
    assert r.context["requete"].techno == ["WCDMA"]


def test_selection_conservee_formulaire_et_rapport_enregistre(admin, base_recherche):
    r = admin.get("/", {"q": "", "periode": "7j", "graphes": ["lte_prb", "lte_volume_dl"]})
    req = r.context["requete"]
    data = QueryDict(mutable=True)
    for k, v in champs_depuis_requete(req).items(): data.setlist(k, v if isinstance(v, list) else [v])
    f = RequeteForm(data)
    assert f.is_valid(), f.errors
    assert RequeteKpi(**f.vers_requete()).graphes == req.graphes
    data.update({"titre": "Data composée", "format": "xlsx", "periode": "7j", "frequence": "aucune",
                 "jour_semaine": 0, "heure": 8})
    reponse = admin.post("/rapports/enregistrer/", dict(data.lists()))
    assert reponse.status_code == 302, reponse.context["form"].errors
    assert RapportPlanifie.objects.get().requete["graphes"] == req.graphes


def test_aucun_graphique_explicitement(admin, base_recherche):
    r = admin.get("/", {"q": "", "periode": "7j", "graphiques_personnalises": "1", "kpis": ["wcdma_sms"]})
    req = r.context["requete"]
    assert req.graphes == []
    assert not r.context["blocs"][0]["graphes_themes"]
    champs = champs_depuis_requete(req)
    assert champs["graphiques_personnalises"] == "1" and champs["graphes"] == []


def test_choix_vide_ou_inconnu_signale(admin):
    assert admin.get("/", {"q": "", "periode": "7j", "graphes": "inconnu"}).status_code == 400
    assert admin.get("/", {"q": "", "periode": "7j", "graphiques_personnalises": "1"}).status_code == 400


def test_filtrage_droits_ne_divulgue_pas_un_graphique_partiel():
    cat = catalogue()
    get = QueryDict("graphes=lte_volume_dl", mutable=True)
    with pytest.raises(ValueError, match="pas accessible"):
        preparer_selection(get, {"lte_payload_dl": cat["lte_payload_dl"]})


def test_editeurs_reserves_aux_droits_administration(client):
    u = User.objects.create_user("lecture", is_staff=True)
    u.user_permissions.add(Permission.objects.get(codename="view_graphique"))
    client.force_login(u)
    initialiser_bibliotheque()
    g = Graphique.objects.get(code="lte_volume_dl")
    url = reverse("admin:kpi_graphique_change", args=[g.pk])
    assert client.get(url).status_code == 200
    assert client.post(url, _post_graphe(g, _series(g))).status_code == 403
    assert client.get(reverse("admin:kpi_modelerapport_changelist")).status_code == 403


def test_rapport_vide_refuse(admin):
    initialiser_bibliotheque()
    r = ModeleRapport.objects.first()
    reponse = admin.post(reverse("admin:kpi_modelerapport_change", args=[r.pk]),
                         {"titre": r.titre, "ordre": 0, "graphes": [], "kpis": []})
    assert reponse.status_code == 200
    assert reponse.context["adminform"].form.non_field_errors()


def test_volumes_sur_un_meme_axe_partagent_la_meme_echelle():
    import pandas as pd
    from apps.kpi.graphes import DefinitionGraphe, Graphes
    from apps.kpi.recherche.affichage import graphes_themes
    from apps.kpi.service import ResultatTechno

    cat = catalogue()
    codes = ["lte_payload_dl", "lte_payload_ul"]
    index = pd.MultiIndex.from_tuples([(pd.Timestamp("2026-10-01"), "site")], names=["periode", "entite"])
    table = pd.DataFrame({codes[0]: [20000.], codes[1]: [200.]}, index=index)
    res = ResultatTechno("LTE", [cat[c] for c in codes], table, 1,
                        synthese=pd.DataFrame({codes[0]: [20000.], codes[1]: [200.]}, index=["site"]),
                        synthese_globale={codes[0]: 20000., codes[1]: 200.})
    lib = Graphes(themes={"trafic": "Trafic"}, graphes=[DefinitionGraphe(
        code="volumes", titre="Volumes", theme="trafic", techno="LTE",
        series=[{"kpi": c, "type": "barres", "axe": "gauche"} for c in codes])])
    donnees = graphes_themes(res, "jour", bibliotheque=lib)
    assert [s["unite"] for s in donnees["themes"][0]["graphes"][0]["series"]] == ["Go", "Go"]
    assert donnees["valeurs"][codes[0]] == [[20.]]
    assert donnees["valeurs"][codes[1]] == [[0.2]]
