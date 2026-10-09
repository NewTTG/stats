import pytest

from apps.referentiel.nommage import (decoder_lte, decoder_wcdma, nom_site_normalise, secteur_equivalent,
                                      sites_wcdma_4_secteurs)


@pytest.mark.parametrize("nom,attendu", [
    ("DZUe2", ("DZU", 1, 2)),
    ("DZUe12", ("DZU", 2, 2)),
    ("116e23", ("116", 3, 3)),
    ("KKTe3", ("KKT", 1, 3)),
    # site à 3 secteurs : e4 = e1, e5 = e2, e6 = e3 (couche supplémentaire ou site déporté)
    ("NDIe4", ("NDI", 1, 1)),
    ("NDIe14", ("NDI", 2, 1)),
    ("RAVe6", ("RAV", 1, 3)),
    ("TENe25", ("TEN", 3, 2)),
    ("BPHe17", ("BPH", 2, 1)),
])
def test_decoder_lte(nom, attendu):
    c = decoder_lte(nom)
    assert (c.prefixe, c.porteuse, c.secteur) == attendu


def test_decoder_lte_4_secteurs():
    assert decoder_lte("LEBe4", quatre_secteurs=True).secteur == 4
    assert decoder_lte("LEBe14", quatre_secteurs=True).secteur == 4


def test_secteur_aiguade():
    """Secteur 1 d'Aiguade = AIG101A, AIG101D, AIGe1, AIGe11, AIGe21."""
    lte = [decoder_lte(n) for n in ("AIGe1", "AIGe11", "AIGe21")]
    wcdma = [decoder_wcdma(n) for n in ("AIG101A", "AIG101D")]
    assert {c.secteur for c in lte + wcdma} == {1}
    assert decoder_wcdma("AIG101B").secteur == 2 and decoder_lte("AIGe3").secteur == 3


@pytest.mark.parametrize("numero,quatre,attendu", [
    (1, False, 1), (3, False, 3), (4, False, 1), (5, False, 2), (6, False, 3), (9, False, 3),
    (4, True, 4), (2, True, 2),
])
def test_secteur_equivalent(numero, quatre, attendu):
    assert secteur_equivalent(numero, quatre) == attendu


@pytest.mark.parametrize("nom,attendu", [
    ("116028B", ("116028", 1, 2)),
    ("BAN139D", ("BAN139", 2, 1)),
    ("ZPA142H", ("ZPA142", 3, 2)),
    ("ZPA142K", ("ZPA142", 4, 2)),
    ("ZPA142L", ("ZPA142", 4, 3)),
])
def test_decoder_wcdma(nom, attendu):
    c = decoder_wcdma(nom)
    assert (c.prefixe, c.porteuse, c.secteur) == attendu


@pytest.mark.parametrize("nom,attendu", [
    ("DTS009A", (1, 1)), ("DTS009D", (1, 4)), ("DTS009J", (2, 1)), ("DTS009M", (2, 4)),
])
def test_decoder_wcdma_4_secteurs(nom, attendu):
    c = decoder_wcdma(nom, quatre_secteurs=True)
    assert (c.porteuse, c.secteur) == attendu


def test_sites_wcdma_4_secteurs():
    assert sites_wcdma_4_secteurs(["DTS009A", "DTS009M", "116028B"]) == {"DTS009"}
    assert decoder_wcdma("DTS009E", quatre_secteurs=True) is None


def test_noms_invalides():
    assert decoder_lte("ZIZ179C") is None
    assert decoder_lte("ZIZe10") is None
    assert decoder_wcdma("116028Z") is None


@pytest.mark.parametrize("nom,attendu", [
    ("TIARIbb", "TIARI"), ("KARIKATEe", "KARIKATE"), ("POINT_116", "POINT_116"),
])
def test_nom_site_normalise(nom, attendu):
    assert nom_site_normalise(nom) == attendu
