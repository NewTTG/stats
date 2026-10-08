"""Résolution des lieux cités dans une demande, limitée au périmètre de l'utilisateur.

Sources : référentiel (communes, régions, sites, trigrammes, secteurs, cellules) et
événements. Un utilisateur restreint ne se voit proposer que les lieux où il a au
moins une cellule autorisée : aucune suggestion ni résolution ne révèle un site ou une
cellule hors de son périmètre (l'intersection serveur de ``service.executer`` reste
la garantie finale).

Un lieu cité mais hors périmètre (ou inconnu) n'est jamais calculé en silence sur le
périmètre de l'utilisateur : il produit une ambiguïté « hors périmètre », dont la
question est la même que le lieu existe ailleurs ou non (rien n'est révélé). Pour un
utilisateur restreint, cette détection ne s'appuie que sur des sources publiques (les
communes, les régions / provinces) et sur la forme des mots (code de site « AAA999 »,
trigramme en capitales, mot placé après « à », « au »…) : un nom de site ou un mot
d'événement hors périmètre est traité exactement comme un mot inconnu (pas d'oracle).
"""

import difflib
import re
from collections import defaultdict

from apps.comptes.acces import cellules_autorisees
from apps.evenements.models import Evenement
from apps.referentiel.models import Cellule, Secteur, Site

from .interpretation import GLOBAL, Ambiguite, Lieu
from .texte import MOTS_VIDES, Correspondeur, Texte, cle, normaliser
from .vocabulaire import vocabulaire

# Mots d'événements trop génériques pour désigner seuls un événement.
_MOTS_GENERIQUES_EVENEMENT = {"fete", "foire", "concert", "salon", "parc", "espace", "show", "royal", "nationale",
                              "manifestation", "municipal", "regate", "paques", "jour", "journee", "village"}
_SUFFIXE_NOM = re.compile(r"^(.*[A-Z0-9_])(bbs|bb|e|s)$")
# Mots génériques qui, seuls, appellent la question « quel événement ? » (« la foire »).
_GENERIQUES_QUESTION = {"foire", "foires", "fete", "fetes", "concert", "concerts", "salon", "regate", "manifestation",
                        "paques"}
# Mots précédant souvent un lieu : un mot inconnu qui les suit est probablement un lieu.
_AVANT_LIEU = {"a", "au", "aux", "sur", "vers", "chez", "pres", "commune", "site"}
# Un mot capitalisé en milieu de phrase n'est un lieu probable qu'après ces prépositions
# (ou s'il ressemble à un lieu connu) : « Urgent », « Tendance », « Cordialement » ne le sont pas.
_AVANT_LIEU_MAJUSCULE = _AVANT_LIEU | {"de", "du", "d", "des", "pour", "en"}
_AVANT_REGION = {"province", "provinces", "region", "regions"}
_ARTICLES = {"la", "le", "les", "l"}
# Correspondance approchée : noms de 5 lettres au moins (« marché » n'est pas « Maré »).
LONGUEUR_MIN_APPROCHE = 5
# Mots reliant un mot générique d'événement à une commune (« foire de Bourail »).
_LIAISONS = {"de", "du", "d", "des", "a", "au"}
# Mot ressemblant à un code de site, de secteur ou de cellule (« PIM123 », « KON5521 »,
# « 145363 ») : jamais ignoré en silence.
_CODE = re.compile(r"^(?=(?:[a-z]*\d){2})(?=.*[a-z])[a-z0-9]{5,}$|^\d{5,}$")
_HEURE = re.compile(r"^\d{1,2}h\d{0,2}$")
SEUIL_APPROCHE = 0.8  # communes et événements
SEUIL_APPROCHE_SITES = 0.85  # noms de sites (plus nombreux, plus proches entre eux)
CANDIDATS_APPROCHES = 6


class ResolveurLieux:
    def __init__(self, user=None):
        self.voc = vocabulaire()
        autorisees = None
        if user is not None:
            par_techno = [cellules_autorisees(user, t) for t in ("LTE", "WCDMA")]
            if any(a is not None for a in par_techno):
                autorisees = set().union(*(a or set() for a in par_techno))
        self.restreint = autorisees is not None
        self._charger(autorisees)

    # ------------------------------------------------------------ chargement
    def _charger(self, autorisees: set[str] | None):
        cellules = Cellule.objects.all()
        sites = Site.objects.all()
        secteurs = Secteur.objects.select_related("site")
        if autorisees is not None:
            cellules = cellules.filter(nom__in=autorisees)
            sites = sites.filter(secteurs__cellules__nom__in=autorisees).distinct()
            secteurs = secteurs.filter(cellules__nom__in=autorisees).distinct()
        self.sites = {s.code_site: s for s in sites}
        self.codes_sites = {code.lower(): s for code, s in self.sites.items()}
        self.cellules_par_site = defaultdict(set)
        self.cellules_par_secteur = defaultdict(set)
        self.cellules_noms = {}
        for nom, secteur, site in cellules.values_list("nom", "secteur__code", "secteur__site__code_site"):
            self.cellules_noms[nom.lower()] = nom
            if site:
                self.cellules_par_site[site].add(nom)
                self.cellules_par_secteur[secteur].add(nom)
        self.secteurs = {s.code.lower(): s for s in secteurs}

        self.communes_visibles = sorted({s.commune for s in self.sites.values() if s.commune})
        self.sites_par_commune = defaultdict(list)
        self.sites_par_trigramme = defaultdict(list)
        for s in self.sites.values():
            self.sites_par_commune[s.commune].append(s.code_site)
            if s.trigramme:
                self.sites_par_trigramme[s.trigramme.lower()].append(s)

        # Communes : nom normalisé + variantes du vocabulaire.
        self.communes = Correspondeur()
        self.toutes_communes = Correspondeur()  # pour signaler une commune hors périmètre
        for nom in set(self.voc.communes) | set(self.communes_visibles):
            variantes = [nom, *(self.voc.communes.get(nom, {}).get("variantes") or [])]
            lieu = Lieu("commune", (nom,), self.voc.libelle_commune(nom))
            for v in variantes:
                self.toutes_communes.ajouter(v, lieu)
                if nom in self.communes_visibles:
                    self.communes.ajouter(v, lieu)

        # Régions / provinces -> communes correspondantes (visibles).
        communes_par_region = defaultdict(set)
        for s in self.sites.values():
            communes_par_region[s.region].add(s.commune)
        self.regions = Correspondeur()
        self.regions_hors = Correspondeur()  # régions sans commune visible (source publique)
        for r in self.voc.regions:
            communes = sorted(set().union(*(communes_par_region.get(x, set()) for x in r["regions"])))
            if communes:
                lieu = Lieu("commune", tuple(communes), r["libelle"],
                            detail=", ".join(self.voc.libelle_commune(c) for c in communes))
                for mot in r["mots"]:
                    self.regions.ajouter(mot, lieu)
            elif autorisees is not None:
                for mot in r["mots"]:
                    self.regions_hors.ajouter(mot, True)

        # Noms de sites (et noms RBS 3G / ERBS), sans suffixe bb / e ; 4 caractères au moins.
        # Un nom de commune (« KONE », « POUEMBOUT ») désigne toujours la commune ; un nom
        # suffixé dont la base est une commune visible (« KONEe ») est ambigu : commune ou site.
        self.noms_sites = Correspondeur()
        for s in sorted(self.sites.values(), key=lambda x: x.code_site):
            lieu = self._lieu_site(s)
            for nom in sorted({s.nom, s.nom_wcdma, s.nom_lte} - {""}):
                m = _SUFFIXE_NOM.match(nom)
                for v in (nom, m[1]) if m else (nom,):
                    k = cle(v)
                    if len("".join(k)) < 4 or k in self.toutes_communes.entrees:
                        continue
                    base = cle(m[1]) if m and v == nom else None
                    for commune in self.communes.entrees.get(base, []) if base else []:
                        self.noms_sites.ajouter(v, commune)
                    self.noms_sites.ajouter(v, lieu)

        # Événements : nom complet, et mots distinctifs (« carnaval », « diginova »).
        self.evenements = Correspondeur()
        self.mots_evenements = defaultdict(list)
        self.mots_generiques = defaultdict(list)  # « foire », « fête » : seulement avec une commune
        mots_communes = {m for k in self.toutes_communes.entrees for m in k}
        secteurs_visibles = {s.code for s in self.secteurs.values()}
        for e in Evenement.objects.all():
            if autorisees is not None and not (set(e.cellules) & autorisees or set(e.sites) & set(self.sites)
                                               or set(e.secteurs) & secteurs_visibles):
                continue
            lieu = Lieu("evenement", (e.nom,), e.nom, detail=e.type)
            self.evenements.ajouter(e.nom, lieu)
            for mot in cle(e.nom):
                if mot in _MOTS_GENERIQUES_EVENEMENT:
                    self.mots_generiques[mot].append(lieu)
                elif len(mot) >= 5 and mot not in mots_communes and lieu not in self.mots_evenements[mot]:
                    self.mots_evenements[mot].append(lieu)

        # Noms (normalisés) pour la correspondance approchée, visibles seulement : d'abord
        # communes et événements, puis noms de sites (seuil plus strict).
        self.approches = defaultdict(list)  # communes, événements
        self.approches_sites = defaultdict(list)
        for correspondeur, cible in ((self.communes, self.approches), (self.evenements, self.approches),
                                     (self.noms_sites, self.approches_sites)):
            for k, lieux in correspondeur.entrees.items():
                nom = " ".join(k)
                if len(nom.replace(" ", "")) >= LONGUEUR_MIN_APPROCHE:
                    for lieu in lieux:
                        if lieu not in cible[nom]:
                            cible[nom].append(lieu)
        for mot, lieux in self.mots_evenements.items():
            if len(mot) >= LONGUEUR_MIN_APPROCHE:
                self.approches[mot] += [lieu for lieu in lieux if lieu not in self.approches[mot]]

        # Utilisateur restreint : communes hors périmètre (publiques) pour la correspondance
        # approchée (« Koumak », « Pita ») -> question « hors périmètre ». Jamais de nom de
        # site ni d'événement hors périmètre (ce serait un oracle d'existence).
        self.approches_publiques: set[str] = set()
        if autorisees is not None:
            self.approches_publiques = {" ".join(k) for k in self.toutes_communes.entrees
                                        if len("".join(k)) >= LONGUEUR_MIN_APPROCHE
                                        and k not in self.communes.entrees}

    def _lieu_site(self, s: Site) -> Lieu:
        return Lieu("site", (s.code_site,), f"{s.nom} ({s.code_site})", detail=self.voc.libelle_commune(s.commune))

    # ------------------------------------------------------------ résolution
    def evenements_complets(self, texte: Texte) -> list:
        """Noms d'événements complets visibles (à chercher avant les dates : « Manifestation du
        13/04 ») : liste de (indices, candidats)."""
        return self.evenements.trouver(texte)

    @staticmethod
    def lieux_evenements(texte: Texte, trouves: list) -> tuple[list[Lieu], list[Ambiguite]]:
        """Résultat de ``evenements_complets`` -> (lieux sûrs, ambiguïtés)."""
        lieux, ambiguites = [], []
        for indices, candidats in trouves:
            mots = " ".join(dict.fromkeys(texte.origines[i] for i in indices))
            if not candidats:
                ambiguites.append(Ambiguite(mots, [], hors_perimetre=True))
            elif len(candidats) == 1:
                lieux.append(candidats[0])
            else:
                ambiguites.append(Ambiguite(mots, list(candidats)))
        return lieux, ambiguites

    def resoudre(self, texte: Texte) -> tuple[list[Lieu], list[Ambiguite], list[str]]:
        """Lieux non ambigus, ambiguïtés, notes (mots reconnus consommés dans ``texte``)."""
        lieux: list[Lieu] = []
        ambiguites: list[Ambiguite] = []
        notes: list[str] = []

        def ajouter(indices, candidats):
            mots = " ".join(texte.origines[i] for i in indices)
            uniques = list(dict.fromkeys(candidats))
            if len(uniques) == 1:
                if uniques[0] not in lieux:
                    lieux.append(uniques[0])
            else:
                ambiguites.append(Ambiguite(mots, uniques))

        def hors_perimetre(indices):
            texte.consommer(indices)
            mots = " ".join(dict.fromkeys(texte.origines[j] for j in indices))
            ambiguites.append(Ambiguite(mots, [], hors_perimetre=True))

        for indices, candidats in self.regions.trouver(texte):
            ajouter(indices, candidats)
        if self.restreint:  # « Province Sud » sans commune visible : source publique
            for indices, _candidats in self.regions_hors.trouver(texte):
                hors_perimetre(self._avec_province(texte, indices))
        for indices, candidats in self.communes.trouver(texte):
            ajouter(indices, candidats)
        if self.restreint:  # commune hors périmètre : question, jamais de calcul en silence
            for indices, candidats in self.toutes_communes.trouver(texte):
                hors_perimetre(self._avec_generique(texte, self._avec_article(texte, indices, candidats)))
        for indices, candidats in self.noms_sites.trouver(texte):
            ajouter(indices, candidats)

        # Mots d'événements : distinctifs (« carnaval »), ou génériques (« foire ») avec la
        # commune de l'événement citée (« la foire … à Koumac ») ; la commune départage.
        communes = {v for lieu in lieux if lieu.type == "commune" for v in lieu.valeurs}

        def dans_commune(evenement: Lieu) -> bool:
            return any(set(cle(co)) <= set(cle(evenement.libelle)) for co in communes)

        for i in texte.libres():
            mot = texte.mots[i]
            candidats = self.mots_evenements.get(mot) or []
            precis = [c for c in (candidats or self.mots_generiques.get(mot, [])) if dans_commune(c)]
            if not candidats and not precis:
                continue
            texte.consommer([i])
            if precis:
                noms = [set(cle(c.libelle)) for c in precis]
                lieux[:] = [lieu for lieu in lieux if not (
                    lieu.type == "commune" and any(set(cle(v)) <= n for v in lieu.valeurs for n in noms))]
                candidats = precis
            ajouter([i], candidats)

        # Codes exacts : site, secteur, cellule.
        for i in texte.libres():
            mot = texte.mots[i]
            site = self.codes_sites.get(mot)
            if site:
                ajouter([i], [self._lieu_site(site)])
            elif mot in self.secteurs:
                s = self.secteurs[mot]
                ajouter([i], [Lieu("secteur", (s.code,), f"Secteur {s.code}",
                                   detail=self.voc.libelle_commune(s.site.commune))])
            elif mot in self.cellules_noms:
                ajouter([i], [Lieu("cellule", (self.cellules_noms[mot],), f"Cellule {self.cellules_noms[mot]}")])
            else:
                continue
            texte.consommer([i])

        # Termes techniques (« HSDPA », « PRB », « RNC ») : jamais un lieu.
        texte.consommer(i for i in texte.libres() if self.voc.est_terme_technique(texte.mots[i]))

        # Trigrammes (3 caractères) ; mots courants seulement s'ils sont écrits en majuscules.
        for i in texte.libres():
            mot = texte.mots[i]
            if not self._trigramme_possible(texte, i) or mot not in self.sites_par_trigramme:
                continue
            texte.consommer([i])
            sites = sorted(self.sites_par_trigramme[mot], key=lambda s: s.code_site)
            if len(sites) == 1:
                ajouter([i], [self._lieu_site(sites[0])])
            else:
                trig = sites[0].trigramme
                tous = Lieu("trigramme", (trig,), f"Tous les sites {trig} ({len(sites)})",
                            detail=", ".join(s.code_site for s in sites))
                ajouter([i], [*(self._lieu_site(s) for s in sites), tous])

        ambiguites += self.approcher(texte)
        return lieux, ambiguites, notes

    def _trigramme_possible(self, texte: Texte, i: int) -> bool:
        mot = texte.mots[i]
        if len(mot) != 3 or not mot.isalpha() or mot in MOTS_VIDES:
            return False
        return mot not in self.voc.pas_trigrammes or texte.origines[i] == texte.origines[i].upper()

    @staticmethod
    def _avec_province(texte: Texte, indices: list[int]) -> list[int]:
        """« Province Sud » : le mot « province » (mot neutre déjà lu) fait partie du lieu cité."""
        j = indices[0] - 1
        return [j, *indices] if j >= 0 and texte.mots[j] in _AVANT_REGION else list(indices)

    @staticmethod
    def _avec_article(texte: Texte, indices: list[int], candidats: list[Lieu]) -> list[int]:
        """« La Foa » : l'article du nom (mot vide, hors de la clé) fait partie du lieu cité."""
        debut = indices[0]
        for lieu in candidats:
            mots = normaliser(lieu.valeurs[0]).split()
            k = next((n for n, m in enumerate(mots) if m not in MOTS_VIDES), 0)
            if k and debut >= k and texte.mots[debut - k:debut] == mots[:k] and not any(
                    texte.consomme[j] for j in range(debut - k, debut)):
                return list(range(debut - k, indices[-1] + 1))
        return list(indices)

    @staticmethod
    def _avec_generique(texte: Texte, indices: list[int]) -> list[int]:
        """« foire de Bourail » : le mot générique d'événement précédant la commune la suit."""
        j = indices[0] - 1
        if j >= 0 and not texte.consomme[j] and texte.mots[j] in _LIAISONS:
            j -= 1
        if j >= 0 and not texte.consomme[j] and texte.mots[j] in _MOTS_GENERIQUES_EVENEMENT | _GENERIQUES_QUESTION:
            return list(range(j, indices[-1] + 1))
        return list(indices)

    def _code(self, mot: str) -> bool:
        """Mot en forme de code de site / secteur / cellule (« PIM123 »), hors heures et sigles."""
        if not _CODE.match(mot) or _HEURE.match(mot):
            return False
        prefixe = re.match(r"[a-z]*", mot)[0]
        return not (prefixe and prefixe in self.voc.mots)  # « top10 », « lte1800 »

    def approcher(self, texte: Texte) -> list[Ambiguite]:
        """Lieux mal orthographiés, inconnus ou génériques parmi les mots restants.

        « Nouméaa », « Koumak », « Pita » -> candidats proches (communes et événements
        visibles, puis noms de sites avec un seuil plus strict) ; « foire » seul -> les
        foires ; un mot inconnu placé comme un lieu (« à Zorglub », « PIM999 », « XYZ » en
        majuscules) -> question sans candidat. Jamais de repli silencieux sur tout le réseau.
        """
        ambiguites = []
        libres = texte.libres()
        for n, i in enumerate(libres):
            mot = texte.mots[i]
            if texte.consomme[i] or mot in MOTS_VIDES or self.voc.est_terme_technique(mot):
                continue
            courant = mot in self.voc.mots_courants  # jamais rapproché d'un nom de lieu
            origine = texte.origines[i]
            if self._code(mot):
                texte.consommer([i])
                ambiguites.append(Ambiguite(origine, [], non_reconnu=True))
                continue
            if len(mot) < 4 or not mot.isalpha():
                court_place = len(mot) == 3 and mot.isalpha() and self._ressemble_a_un_lieu(texte, i)
                if self._sigle_inconnu(texte, i) or court_place:  # « CHT », « à Pic Martin »
                    indices = self._groupe(texte, i)
                    texte.consommer(indices)
                    ambiguites.append(Ambiguite(" ".join(texte.origines[j] for j in indices), [], non_reconnu=True))
                continue
            evenements = self.mots_generiques.get(mot) if mot in _GENERIQUES_QUESTION else None
            if evenements:
                texte.consommer([i])
                ambiguites.append(Ambiguite(origine, sorted(set(evenements), key=lambda e: e.libelle)[:12]))
                continue
            essais = [([i], mot)]
            suivant = libres[n + 1] if n + 1 < len(libres) else None
            if (suivant == i + 1 and texte.mots[suivant].isalpha() and not texte.consomme[suivant]
                    and texte.mots[suivant] not in self.voc.mots_courants):
                essais.insert(0, ([i, suivant], f"{mot} {texte.mots[suivant]}"))
            trouve = None
            for noms, seuil in () if courant else ((self.approches, SEUIL_APPROCHE),
                                                   (self.approches_sites, SEUIL_APPROCHE_SITES)):
                for indices, essai in essais:
                    proches = difflib.get_close_matches(essai, list(noms), n=CANDIDATS_APPROCHES, cutoff=seuil)
                    if proches:
                        trouve = indices, [lieu for nom in proches for lieu in noms[nom]]
                        break
                if trouve:
                    break
            if trouve:
                indices, candidats = trouve
                texte.consommer(indices)
                mots = " ".join(dict.fromkeys(texte.origines[j] for j in indices))
                candidats = list(dict.fromkeys(candidats))[:CANDIDATS_APPROCHES]
                ambiguites.append(Ambiguite(mots, candidats, non_reconnu=True))
            elif not courant and self.approches_publiques and difflib.get_close_matches(
                    mot, list(self.approches_publiques), n=1, cutoff=SEUIL_APPROCHE):
                texte.consommer([i])  # proche d'une commune hors périmètre (publique) : même question
                ambiguites.append(Ambiguite(origine, [], hors_perimetre=True))
            elif self._ressemble_a_un_lieu(texte, i) and not (courant and not origine[:1].isupper()):
                indices = self._groupe(texte, i)
                texte.consommer(indices)
                ambiguites.append(Ambiguite(" ".join(texte.origines[j] for j in indices), [], non_reconnu=True))
        return ambiguites

    @staticmethod
    def _majuscules_significatives(texte: Texte) -> bool:
        """Une demande tout en majuscules ne dit rien des noms propres."""
        return any(c.islower() for c in texte.brut)

    def _sigle_inconnu(self, texte: Texte, i: int) -> bool:
        origine, mot = texte.origines[i], texte.mots[i]
        return (len(mot) == 3 and mot.isalpha() and mot not in MOTS_VIDES and origine.isupper()
                and self._majuscules_significatives(texte))

    def _groupe(self, texte: Texte, i: int) -> list[int]:
        """Mot inconnu et mots suivants écrits comme lui en capitales (« PIC MARTINE »)."""
        indices = [i]
        j = i + 1
        while (j < len(texte.mots) and not texte.consomme[j] and texte.mots[j].isalpha()
               and texte.mots[j] not in MOTS_VIDES and not self.voc.est_terme_technique(texte.mots[j])
               and texte.origines[j][:1].isupper() and self._majuscules_significatives(texte)):
            indices.append(j)
            j += 1
        return indices

    def _ressemble_a_un_lieu(self, texte: Texte, i: int) -> bool:
        """Mot placé comme un lieu : après « à », « au », « sur »… ; capitalisé, après une
        préposition de lieu (« de », « du », « pour », « en » en plus). Jamais d'après
        l'existence du mot dans le référentiel."""
        j = i - 1
        while j > 0 and texte.mots[j] in _ARTICLES:  # « sur la Grande Terre », « à l'Île… »
            j -= 1
        if j < 0:
            return False
        precedent = texte.mots[j]
        majuscule = texte.origines[i][:1].isupper() and self._majuscules_significatives(texte)
        return precedent in _AVANT_LIEU or (majuscule and precedent in _AVANT_LIEU_MAJUSCULE)

    # ------------------------------------------------------------ combinaison
    def combiner(self, lieux: list[Lieu]) -> Lieu:
        """Un seul périmètre pour plusieurs lieux (types homogènes, sinon sites ou cellules)."""
        lieux = [lieu for lieu in lieux if lieu.type != "global"]
        if not lieux:
            return GLOBAL
        if len(lieux) == 1:
            return lieux[0]
        libelle = " + ".join(lieu.libelle for lieu in lieux)
        types = {lieu.type for lieu in lieux}
        if len(types) == 1:
            valeurs = tuple(dict.fromkeys(v for lieu in lieux for v in lieu.valeurs))
            return Lieu(lieux[0].type, valeurs, libelle)
        if types <= {"commune", "site", "trigramme"}:
            return Lieu("site", tuple(dict.fromkeys(c for lieu in lieux for c in self._sites_de(lieu))), libelle)
        return Lieu("cellule", tuple(sorted({c for lieu in lieux for c in self._cellules_de(lieu)})), libelle)

    def _sites_de(self, lieu: Lieu) -> list[str]:
        if lieu.type == "commune":
            return [s for c in lieu.valeurs for s in sorted(self.sites_par_commune.get(c, []))]
        if lieu.type == "trigramme":
            return [s.code_site for t in lieu.valeurs for s in self.sites_par_trigramme.get(t.lower(), [])]
        return list(lieu.valeurs)

    def _cellules_de(self, lieu: Lieu) -> set[str]:
        if lieu.type in ("commune", "trigramme", "site"):
            return {c for s in self._sites_de(lieu) for c in self.cellules_par_site.get(s, ())}
        if lieu.type == "secteur":
            return {c for s in lieu.valeurs for c in self.cellules_par_secteur.get(s, ())}
        if lieu.type == "evenement":
            evenements = Evenement.objects.filter(nom__in=lieu.valeurs)
            noms = {c for e in evenements for t in ("LTE", "WCDMA") for c in e.noms_cellules(t)}
            return noms & set(self.cellules_noms.values())
        return set(lieu.valeurs)

    # ------------------------------------------------------------ suggestions
    def suggestions(self, debut: str = "", limite: int = 12) -> list[dict]:
        """Lieux dont le nom commence par (ou contient) ``debut`` : communes, sites, événements."""
        q = normaliser(debut)
        resultats = []

        def correspond(texte):
            n = normaliser(texte)
            return not q or n.startswith(q) or f" {q}" in f" {n}"

        for c in self.communes_visibles:
            if correspond(c) or correspond(self.voc.libelle_commune(c)):
                resultats.append({"type": "commune", "valeur": c, "libelle": self.voc.libelle_commune(c)})
        for lieu in sorted({e for vs in self.evenements.entrees.values() for e in vs}, key=lambda e: e.libelle):
            if correspond(lieu.libelle):
                resultats.append({"type": "evenement", "valeur": lieu.valeurs[0], "libelle": lieu.libelle})
        if q:
            for s in self.sites.values():
                if correspond(s.nom) or s.code_site.lower().startswith(q) or s.trigramme.lower() == q:
                    resultats.append({"type": "site", "valeur": s.code_site, "libelle": f"{s.nom} ({s.code_site})"})
        return resultats[:limite]
