"""Normalisation du texte saisi et recherche d'expressions (plus longue d'abord)."""

import re
import unicodedata
from collections.abc import Iterable

# Mots vides : ignorés à l'intérieur d'une expression et jamais signalés comme incompris.
MOTS_VIDES = frozenset("""
le la les l de des du d a au aux en et ou sur pour dans un une sa son ses mon ma mes ce cet cette ces qui que quoi
y il elle on nous vous je j m me moi te tu t s se est sont etait ete sur avec chez par entre vers depuis jusqu
jusque the of in at to and or what is are c ca n ne pas plus tout tous toute toutes quel quelle quels quelles
leur leurs lors pendant dont comme ainsi alors donc mais si tres bien
""".split())


def sans_accents(texte: str) -> str:
    texte = texte.replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae").replace("Æ", "AE")
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def normaliser(texte: str) -> str:
    """Minuscules, sans accents ; apostrophes, tirets entre lettres et ponctuation -> espaces.

    Conserve « / », « : » et « - » entre chiffres (dates, heures : 14/09, 18h-22h).
    """
    t = sans_accents(texte).lower()
    t = re.sub(r"[’'`´ʼ‘]", " ", t)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", t)
    t = t.replace("_", " ")
    t = re.sub(r"[^a-z0-9/:\- ]+", " ", t)
    t = re.sub(r"(?<![0-9h])-|-(?![0-9])", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def cle(expression: str) -> tuple[str, ...]:
    """Clé de recherche d'une expression : ses mots normalisés, sans les mots vides."""
    mots = normaliser(expression).split()
    pleins = tuple(m for m in mots if m not in MOTS_VIDES)
    return pleins or tuple(mots)


class Texte:
    """Texte normalisé découpé en mots ; chaque mot reconnu est « consommé »."""

    def __init__(self, brut: str):
        self.brut = brut or ""
        self.mots: list[str] = []
        self.origines: list[str] = []  # mot tel que saisi, pour l'affichage
        for origine in self.brut.split():
            for mot in normaliser(origine).split():
                self.mots.append(mot)
                self.origines.append(origine.strip(" ,;.!?()[]\"«»"))
        self.chaine = " ".join(self.mots)
        self._debuts = []
        position = 0
        for mot in self.mots:
            self._debuts.append(position)
            position += len(mot) + 1
        self.consomme = [False] * len(self.mots)

    # -- motifs (expressions régulières sur la chaîne normalisée)
    def _indices(self, debut: int, fin: int) -> list[int]:
        return [i for i, d in enumerate(self._debuts) if d < fin and d + len(self.mots[i]) > debut]

    def chercher(self, motif: re.Pattern) -> Iterable[re.Match]:
        """Correspondances (mots entiers) dont aucun mot n'est déjà consommé ; consomme les mots."""
        for m in list(motif.finditer(self.chaine)):
            if m.end() == m.start():
                continue
            indices = self._indices(m.start(), m.end())
            if not indices or any(self.consomme[i] for i in indices):
                continue
            if self._debuts[indices[0]] != m.start() or self._debuts[indices[-1]] + len(self.mots[indices[-1]]) != m.end():
                continue  # pas sur des frontières de mots
            for i in indices:
                self.consomme[i] = True
            yield m

    def consommer(self, indices: Iterable[int]):
        for i in indices:
            self.consomme[i] = True

    def libres(self) -> list[int]:
        return [i for i, c in enumerate(self.consomme) if not c]

    def non_compris(self) -> list[str]:
        """Mots saisis non reconnus (forme d'origine, sans doublon), hors mots vides."""
        vus = []
        for i in self.libres():
            if self.mots[i] in MOTS_VIDES:
                continue
            origine = self.origines[i]
            if origine and origine not in vus:
                vus.append(origine)
        return vus


class Correspondeur:
    """Dictionnaire d'expressions -> valeurs ; trouve les plus longues dans un ``Texte``.

    Les mots vides du texte sont sautés à l'intérieur d'une expression : « l'île des
    pins » et « ile pins » ont la même clé.
    """

    def __init__(self):
        self.entrees: dict[tuple[str, ...], list] = {}
        self.longueur_max = 1

    def ajouter(self, expression: str, valeur):
        k = cle(expression)
        if not k:
            return
        valeurs = self.entrees.setdefault(k, [])
        if valeur not in valeurs:
            valeurs.append(valeur)
        self.longueur_max = max(self.longueur_max, len(k))

    def __contains__(self, expression: str) -> bool:
        return cle(expression) in self.entrees

    def trouver(self, texte: Texte, consommer: bool = True, filtre=None) -> list[tuple[list[int], list]]:
        """Liste de (indices des mots, valeurs) de gauche à droite, plus longue expression d'abord."""
        trouves = []
        libres = texte.libres()
        i = 0
        while i < len(libres):
            debut = libres[i]
            if texte.mots[debut] in MOTS_VIDES and (texte.mots[debut],) not in self.entrees:
                i += 1
                continue
            # Mots pleins consécutifs (mots vides sautés, au plus deux d'affilée).
            sequence, indices, vides = [], [], 0
            for j in libres[i:]:
                if indices and j != indices[-1] + 1 + vides:
                    break
                mot = texte.mots[j]
                if mot in MOTS_VIDES and indices:
                    vides += 1
                    if vides > 2:
                        break
                    continue
                sequence.append(mot)
                indices.append(j)
                vides = 0
                if len(sequence) >= self.longueur_max:
                    break
            retenu = None
            for n in range(len(sequence), 0, -1):
                valeurs = self.entrees.get(tuple(sequence[:n]))
                if valeurs and (filtre is None or filtre(tuple(sequence[:n]), indices[:n])):
                    retenu = (list(range(indices[0], indices[n - 1] + 1)), valeurs)
                    break
            if retenu:
                trouves.append(retenu)
                if consommer:
                    texte.consommer(retenu[0])
                dernier = retenu[0][-1]
                while i < len(libres) and libres[i] <= dernier:
                    i += 1
            else:
                i += 1
        return trouves
