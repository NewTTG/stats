import pytest

from apps.referentiel.nommage import decoder_lte, decoder_wcdma, nom_site_normalise


@pytest.mark.parametrize("nom,attendu", [
    ("DZUe2", ("DZU", 0, 2)),
    ("DZUe12", ("DZU", 1, 2)),
    ("116e23", ("116", 2, 3)),
    ("KKTe3", ("KKT", 0, 3)),
])
def test_decoder_lte(nom, attendu):
    c = decoder_lte(nom)
    assert (c.prefixe, c.porteuse, c.secteur) == attendu


@pytest.mark.parametrize("nom,attendu", [
    ("116028B", ("116028", 1, 2)),
    ("ZPA142K", ("ZPA142", 3, 2)),
    ("BAN139D", ("BAN139", 2, 1)),
])
def test_decoder_wcdma(nom, attendu):
    c = decoder_wcdma(nom)
    assert (c.prefixe, c.porteuse, c.secteur) == attendu


def test_noms_invalides():
    assert decoder_lte("ZIZ179C") is None
    assert decoder_wcdma("116028Z") is None


@pytest.mark.parametrize("nom,attendu", [
    ("TIARIbb", "TIARI"), ("KARIKATEe", "KARIKATE"), ("POINT_116", "POINT_116"),
])
def test_nom_site_normalise(nom, attendu):
    assert nom_site_normalise(nom) == attendu
