"""KPI détaillés et graphiques thématiques repris des outils Excel « LTE_SQL_Access » (4G) et
« WCDMA_SQL_Access » (3G) : config/kpi_catalogue.yaml, section kpis_detailles ; config/graphes.yaml."""

import json
import re
from functools import lru_cache

import pandas as pd
import pytest
from django.conf import settings

from apps.kpi.catalogue import DefinitionKpi, catalogue_yaml, charger_catalogue, kpis_principaux
from apps.kpi.graphes import charger_graphes, graphes
from apps.kpi.moteur import agreger
from apps.kpi.recherche import affichage
from apps.kpi.recherche.vocabulaire import vocabulaire
from apps.kpi.service import ResultatTechno

from .test_recherche_vues import _html, admin, base_recherche  # noqa: F401  (fixtures)
from apps.kpi.recherche.regles import interpreter

from .test_recherche_regles import J, ctx, ref_recherche  # noqa: F401


@lru_cache
def _csv(nom):
    return pd.read_csv(settings.BASE_DIR / f"{nom}.csv", sep=";")


def _cat():
    return catalogue_yaml()


# ------------------------------------------------------------------ catalogue et graphiques


def test_kpi_detailles_hors_analyse_par_defaut():
    cat = _cat()
    detailles = [c for c, k in cat.items() if not k.principal]
    assert sum(cat[c].techno == "LTE" for c in detailles) > 100 and sum(cat[c].techno == "WCDMA" for c in detailles) > 100
    assert not set(detailles) & set(kpis_principaux(cat))
    assert cat["lte_payload_dl"].principal and not cat["lte_sinr_pusch"].principal


def test_chaque_kpi_detaille_est_dans_un_graphique():
    traces = {c for g in graphes().graphes for c in g.kpis}
    assert [c for c, k in _cat().items() if not k.principal and c not in traces] == []


def test_graphiques_par_theme():
    g = graphes()
    assert list(g.themes) == ["trafic", "accessibilite", "integrite", "retainability", "mobilite"]
    assert sum(x.techno == "LTE" for x in g.graphes) == 56 and sum(x.techno == "WCDMA" for x in g.graphes) == 45
    # Construction de l'Excel : tentatives en barres (axe principal), taux en courbe (axe secondaire).
    rrc = next(x for x in g.graphes if x.code == "lte_rrc")
    assert [(s.kpi, s.type, s.axe) for s in rrc.series] == [
        ("lte_rrc_tentatives", "barres", "gauche"), ("lte_rrc_setup_sr", "ligne", "droite")]
    motifs = next(x for x in g.graphes if x.code == "lte_motifs_rrc")
    assert {s.type for s in motifs.series} == {"barres_empilees"}
    # 3G : « Surface » de l'Excel en aire (tentatives RRC voix derrière les tentatives d'appel).
    voix = next(x for x in g.graphes if x.code == "wcdma_acces_voix")
    assert [(s.kpi, s.type, s.axe) for s in voix.series] == [
        ("wcdma_rrc_cs_tentatives", "aire", "gauche"), ("wcdma_tentatives_voix", "barres", "gauche"),
        ("wcdma_cssr_cs", "ligne", "droite"), ("wcdma_nas_cs_sr", "ligne", "droite")]


def test_graphique_invalide_refuse(tmp_path):
    chemin = tmp_path / "graphes.yaml"
    chemin.write_text("themes: {t: T}\ngraphes:\n  - {code: x, titre: X, theme: t, series: [{kpi: inconnu, type: barres}]}\n",
                      encoding="utf-8")
    with pytest.raises(ValueError, match="KPI inconnus"):
        charger_graphes(chemin, _cat())
    chemin.write_text("themes: {t: T}\ngraphes:\n  - {code: x, titre: X, theme: t, series: "
                      "[{kpi: lte_payload_dl, type: barres}, {kpi: wcdma_sms, type: ligne}]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="plusieurs technos"):
        charger_graphes(chemin, _cat())


def test_rapports_detailles_par_theme():
    voc = vocabulaire()
    for code, theme in (("rapport_detail_trafic", "trafic"), ("rapport_detail_mobilite", "mobilite"),
                        ("rapport_detail_coupures", "retainability")):
        intention = voc.intentions[code]
        assert intention.rapport and intention.technos_defaut == ["LTE", "WCDMA"]
        assert intention.kpis == {t: graphes().kpis_du_theme(theme, t) for t in ("LTE", "WCDMA")}
    # Débit et qualité radio : 4G seulement (pas de graphique 3G dans ce thème).
    assert voc.intentions["rapport_detail_integrite"].kpis.keys() == {"LTE"}
    # Les causes de coupure viennent des graphiques (donc du catalogue), pas du vocabulaire.
    assert "lte_drop_radio" in voc.intentions["rapport_detail_coupures"].kpis["LTE"]
    assert "wcdma_drop_sho" in voc.intentions["rapport_detail_coupures"].kpis["WCDMA"]


@pytest.mark.django_db
@pytest.mark.parametrize("texte, techno, kpis", [
    ("RSSI à Nouméa hier", ["WCDMA"], ["wcdma_rssi"]),
    ("soft handover à Koné hier", ["WCDMA"], ["wcdma_sho_sr", "wcdma_active_set"]),
    ("HO IRAT à Nouméa hier", ["WCDMA"], ["wcdma_irat_voix_sr", "wcdma_irat_voix_lb_sr"]),
    ("taux de blocage 3G à Païta hier", ["WCDMA"], ["wcdma_rrc_cs_blocage", "wcdma_rab_cs_blocage",
                                                    "wcdma_rrc_ps_blocage", "wcdma_rab_ps_blocage"]),
    ("paging 3G à Nouméa hier", ["WCDMA"], ["wcdma_paging", "wcdma_paging_echec"]),
    ("mobilité détaillée 3G à Nouméa hier", ["WCDMA"], None),
])
def test_recherche_kpi_3g_detailles(ctx, texte, techno, kpis):  # noqa: F811
    i = interpreter(texte, J, ctx)
    assert i.params["techno"] == techno and not i.notes, texte
    attendu = kpis or graphes().kpis_du_theme("mobilite", "WCDMA")
    assert i.params["kpis"] == attendu, texte


# ------------------------------------------------------------------ moyenne simultanée


def test_moyenne_simultanee_somme_des_cellules_puis_moyenne_sur_le_temps():
    k = DefinitionKpi(code="moy", libelle="m", techno="LTE", unite="u", categorie="trafic", numerateur="n",
                      agregation="moyenne_simultanee", sens="haut_est_mieux")
    pic = k.model_copy(update={"code": "pic", "agregation": "pic"})
    t1, t2 = pd.Timestamp("2026-10-01 10:00"), pd.Timestamp("2026-10-01 11:00")
    df = pd.DataFrame({"cellule": ["a", "b", "a", "b"], "horodatage": [t1, t1, t2, t2], "n": [10.0, 20.0, 2.0, 4.0],
                       "site": ["S", "S", "S", "S"]})
    res = agreger(df, [k, pic], par=[]).iloc[0]
    assert res["moy"] == pytest.approx((30 + 6) / 2) and res["pic"] == 30
    par_site = agreger(df, [k], par=["site"])
    assert par_site.loc["S", "moy"] == pytest.approx(18)
    assert k.additif and k.simultane and not k.pic and k.formule == "moy_t Σ n"
    with pytest.raises(ValueError, match="moyenne_simultanee"):
        DefinitionKpi(**{**k.model_dump(exclude={"composants"}), "denominateur": "1"})


# ------------------------------------------------------------------ formules vérifiées sur les extraits


@pytest.mark.parametrize("fichier", ["lte_cell_hour", "lte_cell_day"])
def test_formules_detaillees_sur_les_extraits(fichier):
    df = _csv(fichier)
    cat = _cat()
    codes = ["lte_rrc_echec", "lte_rrc_setup_sr", "lte_part_payload_dl_ca", "lte_ho_inter_sr",
             "lte_ho_inter_prep_sr", "lte_ho_inter_exe_sr", "lte_rrc_part_urgence", "lte_rrc_part_prioritaire",
             "lte_rrc_part_signalisation", "lte_rrc_part_data", "lte_rrc_part_entrant", "lte_mod_dl_256qam",
             "lte_mod_dl_64qam", "lte_mod_dl_16qam", "lte_mod_dl_qpsk", "lte_ca_deconf_normale",
             "lte_ca_deconf_changement", "lte_ca_deconf_couverture"]
    r = agreger(df, [cat[c] for c in codes], par=[]).iloc[0]
    # Échec RRC = 100 − succès (RrcSetupFailRate_p = 100 − RrcSetupSuccRate_p, ligne à ligne).
    assert r["lte_rrc_echec"] + r["lte_rrc_setup_sr"] == pytest.approx(100)
    # Les parts se complètent à 100 % (motifs RRC, modulation DL, fins d'agrégation).
    # (quelques cellules horaires publient des parts nulles malgré des connexions réussies).
    for groupe in (codes[6:11], codes[11:15], codes[15:18]):
        assert sum(r[c] for c in groupe) == pytest.approx(100, abs=0.5), groupe
    # HO = préparation × exécution, aussi en ratio de sommes.
    assert r["lte_ho_inter_sr"] == pytest.approx(r["lte_ho_inter_prep_sr"] * r["lte_ho_inter_exe_sr"] / 100, rel=2e-3)
    # Part du volume DL en CA : égale au ratio publié sur chaque ligne.
    ligne = df[df.PayloadDl_mB > 1].iloc[[0]]
    assert agreger(ligne, [cat["lte_part_payload_dl_ca"]], par=[]).iloc[0]["lte_part_payload_dl_ca"] == \
        pytest.approx(ligne.PayloadDlDrbCa_p.iloc[0], abs=0.1)


@pytest.mark.parametrize("fichier", ["wcdma_cell_hour", "wcdma_cell_day"])
def test_formules_detaillees_3g_sur_les_extraits(fichier):
    df = _csv(fichier)
    cat = _cat()
    causes = [k for k in cat.values() if k.decomposition_de == "wcdma_rrc_echec"]
    assert len(causes) == 7
    codes = ["wcdma_rrc_echec", "wcdma_rrc_sig_sr", "wcdma_active_set_1", "wcdma_active_set_2", "wcdma_active_set_3",
             "wcdma_trafic_voix_best", "wcdma_trafic_voix_amr_sm", "wcdma_trafic_voix_amr_mm"]
    r = agreger(df, [cat[c] for c in codes] + causes, par=[]).iloc[0]
    # Les sept causes publiées somment l'échec RRC voix + data + signalisation en horaire ; en
    # journalier, quelques cellules ont des échecs sans cause (affichés « non ventilé »).
    total = sum(r[k.code] for k in causes)
    if fichier == "wcdma_cell_hour":
        assert total == pytest.approx(r["wcdma_rrc_echec"], abs=0.02)
    else:
        assert total <= r["wcdma_rrc_echec"]
    assert r["wcdma_active_set_1"] + r["wcdma_active_set_2"] + r["wcdma_active_set_3"] == pytest.approx(100, abs=1)
    assert r["wcdma_trafic_voix_amr_sm"] + r["wcdma_trafic_voix_amr_mm"] == pytest.approx(r["wcdma_trafic_voix_best"])
    # Signalisation et CSFB : ratios publiés égaux aux compteurs, ligne à ligne en horaire (le
    # journalier publie parfois une autre valeur sur une cellule : les compteurs font foi).
    if fichier != "wcdma_cell_hour":
        return
    ligne = df[df.RrcSigAtt > 0].iloc[[0]]
    assert agreger(ligne, [cat["wcdma_rrc_sig_sr"]], par=[]).iloc[0]["wcdma_rrc_sig_sr"] == \
        pytest.approx(ligne.RrcSuccessSig_p.iloc[0], abs=0.01)
    ligne = df[df.RabEstAttCsFb > 0].iloc[[0]]
    assert agreger(ligne, [cat["wcdma_cssr_csfb"]], par=[]).iloc[0]["wcdma_cssr_csfb"] == \
        pytest.approx(ligne.CssrSpCsfb_p.iloc[0], abs=0.01)


@pytest.mark.parametrize("fichier", ["lte_cell_hour", "lte_cell_day"])
def test_causes_echec_rrc_presque_totales(fichier):
    """Causes publiées ≈ taux d'échec (le reste, faible, est affiché « non ventilé »)."""
    cat = _cat()
    causes = [k for k in cat.values() if k.decomposition_de == "lte_rrc_echec"]
    assert len(causes) == 4
    r = agreger(_csv(fichier), [cat["lte_rrc_echec"], *causes], par=[]).iloc[0]
    assert sum(r[k.code] for k in causes) <= r["lte_rrc_echec"] + 1e-6


@pytest.mark.parametrize("techno, fichier", [("LTE", "lte_cell_day"), ("WCDMA", "wcdma_cell_day")])
def test_tous_les_kpi_detailles_se_calculent_sur_les_extraits(techno, fichier):
    cat = charger_catalogue(settings.KPI_CATALOGUE_PATH)
    kpis = [k for k in cat.values() if not k.principal and k.techno == techno]
    df = pd.concat([_csv(fichier), pd.to_datetime(_csv(fichier)["DateDay"]).rename("horodatage")], axis=1)
    r = agreger(df, kpis, par=[]).iloc[0]
    vides = [k.code for k in kpis if pd.isna(r[k.code])]
    assert vides == []


# ------------------------------------------------------------------ affichage


def _resultat(codes, entites=("Global",)):
    cat = _cat()
    kpis = [cat[c] for c in codes]
    periodes = pd.to_datetime(["2026-10-01", "2026-10-02"])
    index = pd.MultiIndex.from_product([periodes, list(entites)], names=["periode", "entite"])
    table = pd.DataFrame({c: [float(i + 1) for i in range(len(index))] for c in codes}, index=index)
    synthese = pd.DataFrame({c: [5.0] * len(entites) for c in codes}, index=pd.Index(list(entites), name="entite"))
    return ResultatTechno(techno="LTE", kpis=kpis, table=table, cellules_demandees=3, synthese=synthese,
                          synthese_globale={c: 5.0 for c in codes})


def test_graphes_themes_et_kpi_detailles_sans_carte():
    res = _resultat(["lte_rrc_tentatives", "lte_rrc_setup_sr", "lte_sinr_pusch"], entites=("A", "B"))
    donnees = affichage.graphes_themes(res, "jour")
    assert [t["code"] for t in donnees["themes"]] == ["accessibilite"]
    graphe = donnees["themes"][0]["graphes"][0]
    assert graphe["titre"] == "Établissement RRC"
    assert [(s["kpi"], s["type"], s["axe"], s["unite"]) for s in graphe["series"]] == [
        ("lte_rrc_tentatives", "barres", "gauche", "tentatives"), ("lte_rrc_setup_sr", "ligne", "droite", "%")]
    assert donnees["entites"] == ["A", "B"] and donnees["periodes"] == ["01/10", "02/10"]
    assert donnees["valeurs"]["lte_rrc_tentatives"] == [[1.0, 3.0], [2.0, 4.0]]
    assert donnees["syntheses"]["lte_rrc_setup_sr"][0] == "5,00\u202f%"
    # Tentatives RRC (détaillé, tracé) : ni carte ni courbe ; succès RRC (principal) et SINR (non tracé) : gardés.
    exclus = affichage.kpis_en_graphes(res)
    assert exclus == {"lte_rrc_tentatives"}
    assert [c["kpi"].code for c in affichage.cartes(res, exclus=exclus)] == ["lte_rrc_setup_sr", "lte_sinr_pusch"]
    assert affichage.graphes_themes(_resultat(["lte_sinr_pusch"]), "jour") is None


@pytest.mark.django_db
def test_rapport_detaille_affiche_les_graphiques(admin, base_recherche):  # noqa: F811
    html = _html(admin.get("/", {"q": "Nouméa", "intention": "rapport_detail_mobilite", "periode": "semaine_derniere"}))
    assert "<h1>Mobilité détaillée : Nouméa</h1>" in html
    # Un bloc par techno, chacun avec ses graphiques.
    assert 'data-graphes-themes="graphes-themes-WCDMA"' in html
    wcdma = json.loads(re.search(r'<script id="graphes-themes-WCDMA" type="application/json">(.*?)</script>',
                                 html, re.S)[1])
    assert "Soft handovers" in [g["titre"] for t in wcdma["themes"] for g in t["graphes"]]
    assert "Graphiques par thème" in html and 'data-graphes-themes="graphes-themes-LTE"' in html
    donnees = json.loads(re.search(r'<script id="graphes-themes-LTE" type="application/json">(.*?)</script>',
                                   html, re.S)[1])
    assert [t["titre"] for t in donnees["themes"]] == ["Mobilité"]
    assert len(donnees["themes"][0]["graphes"]) == sum(g.techno == "LTE" for g in graphes().du_theme("mobilite"))
    assert any(v is not None for serie in donnees["valeurs"]["lte_ho_intra_sr"] for v in serie)
    # Les KPI détaillés n'ont pas de carte ; le taux de succès HO intra-fréquence (principal), si.
    assert "<span>Taux de succès HO intra-fréquence</span>" in html
    assert "<span>Préparations de HO inter-fréquence</span>" not in html
