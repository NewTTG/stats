"""Résolution des lieux cités dans une demande, limitée au périmètre de l'utilisateur.

Sources : référentiel (communes, régions, sites, trigrammes, secteurs, cellules) et
événements. Un utilisateur restreint ne se voit proposer que les lieux où il a au
moins une cellule autorisée : aucune suggestion ni résolution ne révèle un site ou une
cellule hors de son périmètre (l'intersection serveur de ``service.executer`` reste
la garantie finale).
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
SEUIL_APPROCHE = 0.8
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
        for r in self.voc.regions:
            communes = sorted(set().union(*(communes_par_region.get(x, set()) for x in r["regions"])))
            if communes:
                lieu = Lieu("commune", tuple(communes), r["libelle"],
                            detail=", ".join(self.voc.libelle_commune(c) for c in communes))
                for mot in r["mots"]:
                    self.regions.ajouter(mot, lieu)

        # Noms de sites (et noms RBS 3G / ERBS), sans suffixe bb / e ; 4 caractères au moins.
        self.noms_sites = Correspondeur()
        for s in self.sites.values():
            lieu = self._lieu_site(s)
            for nom in {s.nom, s.nom_wcdma, s.nom_lte} - {""}:
                variantes = {nom}
                m = _SUFFIXE_NOM.match(nom)
                if m:
                    variantes.add(m[1])
                for v in variantes:
                    k = cle(v)
                    if len("".join(k)) >= 4 and k not in self.communes.entrees:
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

        # Noms (normalisés) pour la correspondance approchée : communes, sites, événements visibles.
        self.approches = defaultdict(list)
        for correspondeur in (self.communes, self.noms_sites, self.evenements):
            for k, lieux in correspondeur.entrees.items():
                nom = " ".join(k)
                if len(nom) >= 4:
                    for lieu in lieux:
                        if lieu not in self.approches[nom]:
                            self.approches[nom].append(lieu)
        for mot, lieux in self.mots_evenements.items():
            self.approches[mot] += [lieu for lieu in lieux if lieu not in self.approches[mot]]

    def _lieu_site(self, s: Site) -> Lieu:
        return Lieu("site", (s.code_site,), f"{s.nom} ({s.code_site})", detail=self.voc.libelle_commune(s.commune))

    # ------------------------------------------------------------ résolution
    def evenements_complets(self, texte: Texte) -> list:
        """Noms d'événements complets (à chercher avant les dates : « Manifestation du 13/04 »)."""
        return self.evenements.trouver(texte)

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

        for indices, candidats in self.regions.trouver(texte):
            ajouter(indices, candidats)
        for indices, candidats in self.communes.trouver(texte):
            ajouter(indices, candidats)
        if self.restreint:
            for indices, candidats in self.toutes_communes.trouver(texte):
                notes.append(f"« {' '.join(texte.origines[i] for i in indices)} » est hors de votre périmètre : ignoré.")
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

        # Trigrammes (3 caractères) ; mots courants seulement s'ils sont écrits en majuscules.
        for i in texte.libres():
            mot = texte.mots[i]
            if len(mot) != 3 or mot in MOTS_VIDES or mot not in self.sites_par_trigramme:
                continue
            if mot in self.voc.pas_trigrammes and texte.origines[i] != texte.origines[i].upper():
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

    def approcher(self, texte: Texte) -> list[Ambiguite]:
        """Lieux mal orthographiés ou génériques parmi les mots restants (4 lettres au moins).

        « Nouméaa », « Koumak », « Pita » -> candidats proches (communes, sites, événements
        visibles) ; « foire » seul -> les foires ; un mot inconnu placé comme un lieu
        (« à Zorglub ») -> question sans candidat. Jamais de repli silencieux sur tout le réseau.
        """
        ambiguites = []
        libres = texte.libres()
        for n, i in enumerate(libres):
            mot = texte.mots[i]
            if texte.consomme[i] or len(mot) < 4 or not mot.isalpha() or mot in MOTS_VIDES:
                continue
            origine = texte.origines[i]
            evenements = self.mots_generiques.get(mot) if mot in _GENERIQUES_QUESTION else None
            if evenements:
                texte.consommer([i])
                ambiguites.append(Ambiguite(origine, sorted(set(evenements), key=lambda e: e.libelle)[:12]))
                continue
            essais = [([i], mot)]
            suivant = libres[n + 1] if n + 1 < len(libres) else None
            if suivant == i + 1 and texte.mots[suivant].isalpha():
                essais.insert(0, ([i, suivant], f"{mot} {texte.mots[suivant]}"))
            trouve = None
            for indices, essai in essais:
                proches = difflib.get_close_matches(essai, list(self.approches), n=CANDIDATS_APPROCHES,
                                                    cutoff=SEUIL_APPROCHE)
                if proches:
                    trouve = indices, proches
                    break
            if trouve:
                indices, proches = trouve
                candidats = list(dict.fromkeys(lieu for nom in proches for lieu in self.approches[nom]))
                texte.consommer(indices)
                mots = " ".join(dict.fromkeys(texte.origines[j] for j in indices))
                ambiguites.append(Ambiguite(mots, candidats[:CANDIDATS_APPROCHES], non_reconnu=True))
            elif self._ressemble_a_un_lieu(texte, i):
                texte.consommer([i])
                ambiguites.append(Ambiguite(origine, [], non_reconnu=True))
        return ambiguites

    @staticmethod
    def _ressemble_a_un_lieu(texte: Texte, i: int) -> bool:
        origine = texte.origines[i]
        precede = i > 0 and texte.mots[i - 1] in _AVANT_LIEU
        majuscule = i > 0 and origine[:1].isupper()
        return precede or majuscule

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
