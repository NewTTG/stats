import pytest

from apps.referentiel.nommage import decoder_lte, decoder_wcdma, nom_site_normalise, sites_wcdma_4_secteurs


@pytest.mark.parametrize("nom,attendu", [
    ("DZUe2", ("DZU", 1, 2)),
    ("DZUe12", ("DZU", 2, 2)),
    ("116e23", ("116", 3, 3)),
    ("KKTe3", ("KKT", 1, 3)),
    ("NDIe4", ("NDI", 1, 4)),
    ("NDIe14", ("NDI", 2, 4)),
])
def test_decoder_lte(nom, attendu):
    c = decoder_lte(nom)
    assert (c.prefixe, c.porteuse, c.secteur) == attendu


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
    assert decoder_wcdma("116028Z") is None


@pytest.mark.parametrize("nom,attendu", [
    ("TIARIbb", "TIARI"), ("KARIKATEe", "KARIKATE"), ("POINT_116", "POINT_116"),
])
def test_nom_site_normalise(nom, attendu):
    assert nom_site_normalise(nom) == attendu
