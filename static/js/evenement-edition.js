"use strict";
// Édition d'un événement : zone couverte (recherche, carte des secteurs), KPI.
//
// La sélection est rangée comme dans le modèle : sites entiers, secteurs, cellules isolées (champs
// cachés « sites », « secteurs », « cellules »). Retirer un secteur d'un site entier, ou une cellule
// d'un secteur entier, décompose la sélection ; choisir toutes les parties d'un ensemble le regroupe.
//
// Sites mobiles (remorques) : absents de la carte de sélection, ajoutés depuis la liste ou la recherche.
// Leur position, leurs secteurs (azimut) et leurs cellules se déclarent pour l'événement (champ caché
// « deploiements », JSON) ; une fois positionnés, ils sont dessinés à cet endroit.
// Un seul secteur à l'azimut 0 : antenne omnidirectionnelle, dessinée en cercle complet.

(() => {
  const formulaire = document.getElementById("evenement_form");
  if (!formulaire) return;
  let modifie = false;
  const marquerModifie = () => { modifie = true; };
  formulaire.addEventListener("input", marquerModifie);
  formulaire.addEventListener("submit", () => { modifie = false; });
  window.addEventListener("beforeunload", (event) => {
    if (modifie) event.preventDefault();
  });

  // ------------------------------------------------------------------ outils
  const el = (balise, attributs = {}, ...enfants) => {
    const noeud = document.createElement(balise);
    for (const [cle, valeur] of Object.entries(attributs)) {
      if (valeur === false || valeur == null) continue;
      if (cle === "class") noeud.className = valeur;
      else if (cle === "text") noeud.textContent = valeur;
      else noeud.setAttribute(cle, valeur === true ? "" : valeur);
    }
    for (const enfant of enfants) if (enfant != null) noeud.append(enfant);
    return noeud;
  };
  const normaliser = (texte) => (texte || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[_\s-]+/g, " ").toUpperCase().trim();
  const pluriel = (n, mot, motPluriel = `${mot}s`) => `${n.toLocaleString("fr-FR")} ${n > 1 ? motPluriel : mot}`;
  const TECHNO = { LTE: "4G", WCDMA: "3G" };

  document.querySelectorAll("form[data-confirmer]").forEach((f) => f.addEventListener("submit", (event) => {
    if (!window.confirm(f.dataset.confirmer)) event.preventDefault();
    else modifie = false;
  }));

  // ------------------------------------------------------------------ zone couverte
  const zone = document.getElementById("ev-zone");
  if (zone) initialiserZone(zone);

  function initialiserZone(zone) {
    const champs = Object.fromEntries(["sites", "secteurs", "cellules", "deploiements"].map(
      (nom) => [nom, formulaire.querySelector(`input[name="${nom}"]`)]));
    const lire = (champ) => (champ.value || "").split(/[\s,;]+/).filter(Boolean);
    const lireJson = (champ) => {
      try {
        const valeur = JSON.parse(champ.value || "{}");
        return valeur && typeof valeur === "object" && !Array.isArray(valeur) ? valeur : {};
      } catch (e) {
        return {};
      }
    };
    const etat = { sites: new Set(lire(champs.sites)), secteurs: new Set(lire(champs.secteurs)),
                   cellules: new Set(lire(champs.cellules)), deploiements: lireJson(champs.deploiements) };
    const recherche = zone.querySelector("#ev-recherche");
    const suggestions = zone.querySelector("#ev-suggestions");
    const panneau = zone.querySelector("[data-selection]");
    const total = zone.querySelector("[data-total]");
    const cadreCarte = zone.querySelector("[data-carte]");
    const ouverts = new Set();  // sites dont le détail est déplié dans la liste
    const replies = new Set();  // remorques dont le détail est replié (dépliées par défaut)
    let ordre = [];             // sites de la sélection, le plus récent d'abord
    let sites = new Map(), secteurs = new Map(), cellules = new Map();
    const mobiles = new Map();  // sites mobiles du référentiel, hors carte
    let carte = null;
    let pointage = null;        // remorque dont on pointe la position sur la carte
    const marqueurs = new Map(), marqueursMobiles = new Map();

    fetch(zone.dataset.reseau, { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((reseau) => {
        indexer(reseau);
        convertirMobiles();
        ordre = sitesTouches();
        if (ordre.length <= 3) ordre.forEach((code) => ouverts.add(code));
        recherche.disabled = false;
        rendreSelection();
        initialiserCarte();
      })
      .catch(() => {
        panneau.replaceChildren(el("p", { class: "ev-vide erreur",
          text: "Référentiel indisponible : rechargez la page. La sélection enregistrée reste inchangée." }));
      });

    function indexer(reseau) {
      for (const s of reseau.sites) {
        if (s.mobile) {
          mobiles.set(s.code, { ...s, cle: normaliser(`${s.code} ${s.trigramme} ${s.nom} ${s.commune}`) });
          continue;
        }
        const site = { ...s, cle: normaliser(`${s.code} ${s.trigramme} ${s.nom} ${s.commune}`), nbCellules: 0 };
        site.secteurs = s.secteurs.map((sec) => ({ ...sec, site, cellules: [] }));
        for (const sec of site.secteurs) {
          sec.cellules = s.secteurs.find((x) => x.code === sec.code).cellules.map(([nom, techno]) => {
            const cellule = { nom, techno, secteur: sec, site };
            cellules.set(nom, cellule);
            return cellule;
          });
          site.nbCellules += sec.cellules.length;
          secteurs.set(sec.code, sec);
        }
        sites.set(site.code, site);
      }
      for (const [nom, techno] of reseau.libres) cellules.set(nom, { nom, techno, secteur: null, site: null });
    }

    // ---------------------------------------------------------------- état de la sélection
    const siteDe = (code) => sites.get(code) || secteurs.get(code)?.site || cellules.get(code)?.site || null;

    function sitesTouches() {
      const codes = [];
      for (const ensemble of [etat.sites, etat.secteurs, etat.cellules]) {
        for (const code of ensemble) {
          const site = siteDe(code);
          if (site && !codes.includes(site.code)) codes.push(site.code);
        }
      }
      return codes;
    }

    const celluleIncluse = (c) => etat.cellules.has(c.nom) || (c.secteur && (etat.secteurs.has(c.secteur.code)
      || etat.sites.has(c.site.code)));

    function etatSecteur(sec) {
      if (etat.sites.has(sec.site.code) || etat.secteurs.has(sec.code)) return "choisi";
      const n = sec.cellules.filter((c) => etat.cellules.has(c.nom)).length;
      return n === 0 ? "libre" : n === sec.cellules.length ? "choisi" : "partiel";
    }

    function etatSite(site) {
      if (etat.sites.has(site.code)) return "choisi";
      const etats = new Set(site.secteurs.map(etatSecteur));
      return etats.size === 1 ? [...etats][0] : "partiel";
    }

    function regrouper(site) {
      // Toutes les cellules d'un secteur -> le secteur ; tous les secteurs d'un site -> le site entier.
      for (const sec of site.secteurs) {
        if (!etat.secteurs.has(sec.code) && sec.cellules.length && sec.cellules.every((c) => etat.cellules.has(c.nom))) {
          sec.cellules.forEach((c) => etat.cellules.delete(c.nom));
          etat.secteurs.add(sec.code);
        }
      }
      if (!etat.sites.has(site.code) && site.secteurs.every((sec) => etat.secteurs.has(sec.code))) {
        site.secteurs.forEach((sec) => etat.secteurs.delete(sec.code));
        etat.sites.add(site.code);
      }
    }

    function viderSite(site) {
      etat.sites.delete(site.code);
      for (const sec of site.secteurs) {
        etat.secteurs.delete(sec.code);
        sec.cellules.forEach((c) => etat.cellules.delete(c.nom));
      }
    }

    function choisirSite(site) {
      viderSite(site);
      etat.sites.add(site.code);
    }

    function basculerSite(site) {
      if (etatSite(site) === "choisi") viderSite(site);
      else choisirSite(site);
      apresChangement(site);
    }

    function basculerSecteur(sec) {
      const site = sec.site;
      if (etat.sites.has(site.code)) {  // site entier : on garde les autres secteurs
        etat.sites.delete(site.code);
        site.secteurs.filter((s) => s !== sec).forEach((s) => etat.secteurs.add(s.code));
      } else if (etatSecteur(sec) === "choisi") {
        etat.secteurs.delete(sec.code);
        sec.cellules.forEach((c) => etat.cellules.delete(c.nom));
      } else {
        sec.cellules.forEach((c) => etat.cellules.delete(c.nom));
        etat.secteurs.add(sec.code);
      }
      regrouper(site);
      apresChangement(site);
    }

    function basculerCellule(cellule) {
      const { secteur: sec, site } = cellule;
      if (!sec) {  // cellule non rattachée à un site
        if (etat.cellules.has(cellule.nom)) etat.cellules.delete(cellule.nom);
        else etat.cellules.add(cellule.nom);
        apresChangement(null);
        return;
      }
      if (etat.sites.has(site.code)) {
        etat.sites.delete(site.code);
        site.secteurs.filter((s) => s !== sec).forEach((s) => etat.secteurs.add(s.code));
        etat.secteurs.add(sec.code);
      }
      if (etat.secteurs.has(sec.code)) {
        etat.secteurs.delete(sec.code);
        sec.cellules.filter((c) => c !== cellule).forEach((c) => etat.cellules.add(c.nom));
      } else if (etat.cellules.has(cellule.nom)) {
        etat.cellules.delete(cellule.nom);
      } else {
        etat.cellules.add(cellule.nom);
        regrouper(site);
      }
      apresChangement(site);
    }

    function retirerCode(code) {
      etat.sites.delete(code); etat.secteurs.delete(code); etat.cellules.delete(code);
      apresChangement(null);
    }

    function apresChangement(site) {
      champs.sites.value = [...etat.sites].join(",");
      champs.secteurs.value = [...etat.secteurs].join(",");
      champs.cellules.value = [...etat.cellules].join(",");
      marquerModifie();
      const touches = sitesTouches();
      if (site && touches.includes(site.code)) ordre = [site.code, ...ordre.filter((c) => c !== site.code)];
      ordre = [...ordre.filter((c) => touches.includes(c)), ...touches.filter((c) => !ordre.includes(c))];
      rendreSelection();
      if (site) dessinerSite(site);
    }

    // ---------------------------------------------------------------- sites mobiles
    function ecrireDeploiements() {
      champs.deploiements.value = Object.keys(etat.deploiements).length ? JSON.stringify(etat.deploiements) : "";
    }

    function deploiementParDefaut(site, retenue = () => true) {
      // Disposition du référentiel (azimuts, cellules) comme point de départ ; position à déclarer.
      const secteursSite = site.secteurs.length ? site.secteurs : [{ numero: 1, azimut: null, cellules: [] }];
      return { lat: null, lon: null, secteurs: secteursSite.map((sec) => ({
        numero: sec.numero, azimut: sec.azimut ?? null,
        cellules: sec.cellules.filter(([nom]) => retenue(nom)).map(([nom, techno]) => [nom, techno]),
      })) };
    }

    function convertirMobiles() {
      // Sélection enregistrée avant la déclaration des remorques : convertie en déploiement.
      let change = false;
      for (const site of mobiles.values()) {
        const codesSecteurs = new Set(site.secteurs.map((sec) => sec.code));
        const noms = site.secteurs.flatMap((sec) => sec.cellules.map(([nom]) => nom));
        const entier = etat.sites.has(site.code);
        const parSecteur = new Set(site.secteurs.filter((sec) => etat.secteurs.has(sec.code))
          .flatMap((sec) => sec.cellules.map(([nom]) => nom)));
        const retenue = (nom) => entier || parSecteur.has(nom) || etat.cellules.has(nom);
        if (!noms.some(retenue) && !entier) continue;
        if (!etat.deploiements[site.code]) etat.deploiements[site.code] = deploiementParDefaut(site, retenue);
        etat.sites.delete(site.code);
        codesSecteurs.forEach((code) => etat.secteurs.delete(code));
        noms.forEach((nom) => etat.cellules.delete(nom));
        change = true;
      }
      if (change) {
        champs.sites.value = [...etat.sites].join(",");
        champs.secteurs.value = [...etat.secteurs].join(",");
        champs.cellules.value = [...etat.cellules].join(",");
        ecrireDeploiements();
      }
    }

    function deployer(site) {
      if (!etat.deploiements[site.code]) etat.deploiements[site.code] = deploiementParDefaut(site);
      replies.delete(`mobile:${site.code}`);
      apresChangementMobile(site.code);
    }

    function retirerDeploiement(code) {
      delete etat.deploiements[code];
      if (pointage === code) arreterPointage();
      apresChangementMobile(code);
    }

    function apresChangementMobile(code, rendre = true) {
      ecrireDeploiements();
      marquerModifie();
      if (rendre) rendreSelection(); else rendreTotal();
      dessinerMobile(code);
    }

    const nomMobile = (code) => mobiles.get(code)?.nom || code;
    const cellulesDeployees = (dep) => dep.secteurs.flatMap((sec) => sec.cellules);
    const omni = (azimut, nb) => nb === 1 && azimut === 0;
    const libelleAzimut = (azimut, nb) => (azimut == null ? "azimut inconnu"
      : omni(azimut, nb) ? "omni (360°)" : `${azimut}°`);

    function nombreSaisi(texte) {
      const t = String(texte ?? "").trim().replace(",", ".");
      return t === "" || Number.isNaN(Number(t)) ? null : Number(t);
    }

    // ---------------------------------------------------------------- liste de la sélection
    function boussole(azimut, numero, nb) {
      // Petit secteur orienté (azimut réel, ou réparti régulièrement s'il est inconnu) ; omni : disque.
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", "0 0 20 20");
      svg.setAttribute("class", `ev-boussole${azimut == null ? " estime" : ""}`);
      svg.setAttribute("aria-hidden", "true");
      svg.innerHTML = `<circle cx="10" cy="10" r="8.5"/><path d="${cheminSecteur(10, 10, 8.5, angle(azimut, numero, nb), omni(azimut, nb))}"/>`;
      return svg;
    }

    function rendreSelection() {
      const enfants = [];
      const inconnus = [...etat.sites, ...etat.secteurs, ...etat.cellules].filter((code) => !siteDe(code) && !cellules.has(code));
      const libres = [...etat.cellules].filter((nom) => cellules.has(nom) && !cellules.get(nom).secteur);
      for (const code of Object.keys(etat.deploiements)) enfants.push(carteMobile(code));
      for (const code of ordre) enfants.push(carteSite(sites.get(code)));
      if (libres.length) {
        enfants.push(el("div", { class: "ev-groupe-libre" },
          el("p", { class: "ev-groupe-titre", text: "Cellules sans site connu" }),
          el("div", { class: "ev-cellules" }, ...libres.map((nom) => boutonCellule(cellules.get(nom), true)))));
      }
      if (inconnus.length) {
        enfants.push(el("div", { class: "ev-inconnus", role: "note" },
          el("p", { text: "Absents du référentiel actuel, ignorés par l'analyse :" }),
          el("div", { class: "ev-cellules" }, ...inconnus.map((code) => el("button", {
            type: "button", class: "ev-puce inconnue", "data-retirer-code": code, title: "Retirer",
          }, code, el("span", { "aria-hidden": "true", text: " ×" }))))));
      }
      if (!enfants.length) {
        enfants.push(el("div", { class: "ev-vide" },
          el("strong", { text: "Aucun site sélectionné." }),
          el("span", { text: "Recherchez un site ci-dessus, ou cliquez sur un site de la carte." })));
      }
      const disponibles = [...mobiles.values()].filter((m) => !etat.deploiements[m.code]);
      if (disponibles.length) {
        enfants.push(el("div", { class: "ev-mobiles-dispo" },
          el("p", { class: "ev-groupe-titre", text: "Sites mobiles (remorques), hors carte" }),
          el("div", { class: "ev-cellules" }, ...disponibles.map((m) => el("button", {
            type: "button", class: "ev-puce ev-puce-mobile", "data-deployer": m.code,
            title: `Ajouter ${m.nom} et déclarer sa position, ses secteurs et ses cellules`,
          }, `+ ${m.nom}`, el("small", { text: m.code }))))));
      }
      const focus = document.activeElement;
      const cleFocus = panneau.contains(focus) ? focus.dataset.focus : null;
      panneau.replaceChildren(...enfants);
      if (cleFocus) panneau.querySelector(`[data-focus="${CSS.escape(cleFocus)}"]`)?.focus();
      rendreTotal();
    }

    function carteMobile(code) {
      const dep = etat.deploiements[code];
      const site = mobiles.get(code);
      const cle = `mobile:${code}`;
      const nb = dep.secteurs.length;
      const declarees = cellulesDeployees(dep);
      const place = dep.lat != null && dep.lon != null;
      const details = el("details", { class: "ev-site ev-mobile etat-choisi", "data-mobile": code });
      details.open = !replies.has(cle);
      details.addEventListener("toggle", () => {
        if (details.open) replies.delete(cle); else replies.add(cle);
      });
      // Cellules proposées : celles du référentiel, puis celles déclarées en plus.
      const connues = new Map();
      for (const sec of site?.secteurs || []) for (const [nom, techno] of sec.cellules) connues.set(nom, techno);
      for (const [nom, techno] of declarees) if (!connues.has(nom)) connues.set(nom, techno);
      const secteurDe = new Map();
      for (const sec of dep.secteurs) for (const [nom] of sec.cellules) secteurDe.set(nom, sec.numero);
      const n = (x) => `${code}:${x}`;
      details.append(
        el("summary", {},
          el("span", { class: "ev-site-nom" }, el("strong", { text: nomMobile(code) }),
            el("small", { text: `${code} · site mobile${site ? "" : " (absent du référentiel)"}` })),
          el("span", { class: "ev-etiquette etat-choisi", text: `${pluriel(nb, "secteur")}, ${pluriel(declarees.length, "cellule")}` }),
          el("button", { type: "button", class: "ev-icone", "data-retirer-mobile": code,
                         "aria-label": `Retirer ${nomMobile(code)}`, title: "Retirer la remorque", text: "×" })),
        el("div", { class: "ev-site-corps" },
          el("fieldset", { class: "ev-mobile-bloc" },
            el("legend", { text: "Position pendant l'événement" }),
            el("div", { class: "ev-mobile-position" },
              el("label", {}, el("span", { text: "Latitude" }),
                el("input", { type: "text", inputmode: "decimal", value: dep.lat ?? "", placeholder: "-22.2758",
                              "data-dep-lat": code, "data-focus": n("lat"), autocomplete: "off" })),
              el("label", {}, el("span", { text: "Longitude" }),
                el("input", { type: "text", inputmode: "decimal", value: dep.lon ?? "", placeholder: "166.4580",
                              "data-dep-lon": code, "data-focus": n("lon"), autocomplete: "off" })),
              el("button", { type: "button", class: `bouton secondaire petit${pointage === code ? " actif" : ""}`,
                             "data-dep-pointer": code, "aria-pressed": String(pointage === code),
                             text: pointage === code ? "Cliquez sur la carte…" : "Pointer sur la carte" })),
            el("p", { class: `ev-mobile-etat${place ? "" : " a-faire"}`, "data-dep-etat": code,
                      text: place ? "Positionnée : dessinée sur la carte avec ses secteurs."
                        : "Position à déclarer : sans elle, la remorque n'apparaît pas sur les cartes (l'analyse reste possible)." })),
          el("fieldset", { class: "ev-mobile-bloc" },
            el("legend", { text: "Secteurs" }),
            el("ul", { class: "ev-mobile-secteurs" }, ...dep.secteurs.map((sec) => el("li", {},
              boussole(sec.azimut, sec.numero, nb),
              el("span", { class: "ev-mobile-num", text: `Secteur ${sec.numero}` }),
              el("label", {}, el("span", { class: "sr-only", text: `Azimut du secteur ${sec.numero}` }),
                el("input", { type: "number", min: 0, max: 359, step: 1, value: sec.azimut ?? "", placeholder: "azimut",
                              "data-dep-azimut": code, "data-numero": sec.numero, "data-focus": n(`az${sec.numero}`) }),
                el("span", { "aria-hidden": "true", text: "°" })),
              el("small", { class: "ev-mobile-omni", "data-dep-libelle": `${code}:${sec.numero}`,
                            text: omni(sec.azimut, nb) ? "omni (360°)" : sec.azimut == null ? "azimut inconnu" : "" }),
              nb > 1 ? el("button", { type: "button", class: "ev-icone", "data-dep-retirer-secteur": code,
                                      "data-numero": sec.numero, title: `Retirer le secteur ${sec.numero}`,
                                      "aria-label": `Retirer le secteur ${sec.numero}`, text: "×" }) : null))),
            el("p", { class: "aide" }, "Un seul secteur à 0° : antenne omni (360°). ",
              dep.secteurs.length < 9 ? el("button", { type: "button", class: "ev-lien", "data-dep-ajouter-secteur": code,
                                                       text: "+ Ajouter un secteur" }) : null)),
          el("fieldset", { class: "ev-mobile-bloc" },
            el("legend", { text: "Cellules" }),
            connues.size ? el("ul", { class: "ev-mobile-cellules" }, ...[...connues].map(([nom, techno]) => el("li", {},
              el("span", { class: "ev-mobile-cellule" }, el("strong", { text: nom }), el("small", { text: TECHNO[techno] || techno })),
              el("select", { "data-dep-cellule": code, "data-nom": nom, "data-techno": techno, "data-focus": n(`c${techno}${nom}`),
                             "aria-label": `Secteur de ${nom}` },
                el("option", { value: "", text: "Non utilisée", selected: !secteurDe.has(nom) }),
                ...dep.secteurs.map((sec) => el("option", { value: sec.numero, text: `Secteur ${sec.numero}`,
                                                            selected: secteurDe.get(nom) === sec.numero }))))))
              : el("p", { class: "aide", text: "Aucune cellule connue pour ce site : ajoutez-les ci-dessous." }),
            el("div", { class: "ev-mobile-ajout" },
              el("label", {}, el("span", { class: "sr-only", text: "Nom de la cellule à ajouter" }),
                el("input", { type: "text", placeholder: "Autre cellule (ex. 1RMe3)", maxlength: 32, autocomplete: "off",
                              spellcheck: "false", "data-dep-nouvelle": code, "data-focus": n("nouvelle") })),
              el("label", {}, el("span", { class: "sr-only", text: "Technologie" }),
                el("select", { "data-dep-nouvelle-techno": code },
                  el("option", { value: "LTE", text: "4G" }), el("option", { value: "WCDMA", text: "3G" }))),
              el("button", { type: "button", class: "bouton secondaire petit", "data-dep-ajouter-cellule": code, text: "Ajouter" })))));
      return details;
    }

    function carteSite(site) {
      const etatGlobal = etatSite(site);
      const details = el("details", { class: `ev-site etat-${etatGlobal}`, "data-site": site.code });
      details.open = ouverts.has(site.code);
      details.addEventListener("toggle", () => {
        if (details.open) ouverts.add(site.code); else ouverts.delete(site.code);
      });
      const choisis = site.secteurs.filter((s) => etatSecteur(s) !== "libre").length;
      const resume = etat.sites.has(site.code) ? "Site entier"
        : `${choisis}/${site.secteurs.length} secteur${site.secteurs.length > 1 ? "s" : ""}`;
      details.append(
        el("summary", {},
          el("span", { class: "ev-site-nom" }, el("strong", { text: site.nom }),
            el("small", { text: `${site.code} · ${site.commune}` })),
          el("span", { class: `ev-etiquette etat-${etatGlobal}`, text: resume }),
          el("button", { type: "button", class: "ev-icone", "data-retirer-site": site.code,
                         "aria-label": `Retirer ${site.nom}`, title: "Retirer le site", text: "×" })),
        el("div", { class: "ev-site-corps" },
          el("div", { class: "ev-site-outils" },
            el("label", { class: "ev-interrupteur" },
              el("input", { type: "checkbox", "data-site-entier": site.code, checked: etat.sites.has(site.code) }),
              " Site entier"),
            site.lat != null ? el("button", { type: "button", class: "ev-lien", "data-centrer": site.code, text: "Voir sur la carte" }) : null),
          el("ul", { class: "ev-secteurs" }, ...site.secteurs.map((sec) => {
            const e = etatSecteur(sec);
            return el("li", { class: `ev-secteur etat-${e}` },
              el("button", { type: "button", class: "ev-secteur-bouton", "data-secteur": sec.code, "aria-pressed": String(e === "choisi"),
                             title: e === "choisi" ? "Retirer ce secteur" : "Ajouter tout le secteur" },
                boussole(sec.azimut, sec.numero, site.secteurs.length),
                el("span", { text: `Secteur ${sec.numero}` }),
                el("small", { text: libelleAzimut(sec.azimut, site.secteurs.length) })),
              el("div", { class: "ev-cellules" }, ...sec.cellules.map((c) => boutonCellule(c))));
          }))));
      return details;
    }

    function boutonCellule(cellule, libre = false) {
      const incluse = celluleIncluse(cellule);
      return el("button", { type: "button", class: `ev-puce${incluse ? " incluse" : ""}`, "data-cellule": cellule.nom,
                            "aria-pressed": String(incluse), title: libre ? "Retirer" : (incluse ? "Retirer cette cellule" : "Ajouter cette cellule") },
        cellule.nom, el("small", { text: TECHNO[cellule.techno] || cellule.techno }));
    }

    function rendreTotal() {
      const incluses = [...cellules.values()].filter(celluleIncluse);
      const deps = Object.values(etat.deploiements);
      for (const dep of deps) for (const [nom, techno] of cellulesDeployees(dep)) incluses.push({ nom, techno });
      const lte = incluses.filter((c) => c.techno === "LTE").length;
      const parties = [];
      if (deps.length) parties.push(pluriel(deps.length, "site mobile", "sites mobiles"));
      if (etat.sites.size) parties.push(pluriel(etat.sites.size, "site entier", "sites entiers"));
      if (etat.secteurs.size) parties.push(pluriel(etat.secteurs.size, "secteur"));
      const isolees = [...etat.cellules].filter((n) => cellules.has(n)).length;
      if (isolees) parties.push(pluriel(isolees, "cellule isolée", "cellules isolées"));
      total.replaceChildren(
        el("strong", { text: pluriel(incluses.length, "cellule") }),
        el("span", { text: incluses.length ? ` · ${lte} 4G · ${incluses.length - lte} 3G` : "" }),
        parties.length ? el("small", { text: parties.join(", ") }) : "");
    }

    // Saisies des remorques : mises à jour sans redessiner la liste (le curseur reste en place).
    panneau.addEventListener("input", (event) => {
      const cible = event.target;
      const code = cible.dataset.depLat || cible.dataset.depLon || cible.dataset.depAzimut;
      const dep = code && etat.deploiements[code];
      if (!dep) return;
      if (cible.dataset.depAzimut) {
        const sec = dep.secteurs.find((s) => s.numero === Number(cible.dataset.numero));
        const valeur = nombreSaisi(cible.value);
        sec.azimut = valeur == null ? null : Math.round(valeur);  // hors 0-359 : refusé à l'enregistrement
        const libelle = panneau.querySelector(`[data-dep-libelle="${CSS.escape(`${code}:${sec.numero}`)}"]`);
        if (libelle) libelle.textContent = omni(sec.azimut, dep.secteurs.length) ? "omni (360°)" : sec.azimut == null ? "azimut inconnu" : "";
        const ancienne = cible.closest("li")?.querySelector(".ev-boussole");
        ancienne?.replaceWith(boussole(sec.azimut, sec.numero, dep.secteurs.length));
      } else {
        dep[cible.dataset.depLat ? "lat" : "lon"] = nombreSaisi(cible.value);
        const etatPosition = panneau.querySelector(`[data-dep-etat="${CSS.escape(code)}"]`);
        const place = dep.lat != null && dep.lon != null;
        if (etatPosition) {
          etatPosition.classList.toggle("a-faire", !place);
          etatPosition.textContent = place ? "Positionnée : dessinée sur la carte avec ses secteurs."
            : "Position à déclarer : sans elle, la remorque n'apparaît pas sur les cartes (l'analyse reste possible).";
        }
      }
      apresChangementMobile(code, false);
    });

    panneau.addEventListener("change", (event) => {
      const cible = event.target;
      const code = cible.dataset.depCellule;
      const dep = code && etat.deploiements[code];
      if (!dep) return;
      const paire = [cible.dataset.nom, cible.dataset.techno];
      for (const sec of dep.secteurs) sec.cellules = sec.cellules.filter(([nom, t]) => !(nom === paire[0] && t === paire[1]));
      const sec = dep.secteurs.find((s) => s.numero === Number(cible.value));
      if (sec) sec.cellules.push(paire);
      apresChangementMobile(code);
    });

    panneau.addEventListener("keydown", (event) => {
      const cible = event.target;
      if (event.key !== "Enter" || cible.tagName !== "INPUT" || !panneau.contains(cible) || cible.type === "checkbox") return;
      event.preventDefault();  // jamais d'envoi du formulaire depuis une saisie de remorque
      if (cible.dataset.depNouvelle) ajouterCelluleMobile(cible.dataset.depNouvelle);
    });

    function ajouterCelluleMobile(code) {
      const dep = etat.deploiements[code];
      const champ = panneau.querySelector(`[data-dep-nouvelle="${CSS.escape(code)}"]`);
      const techno = panneau.querySelector(`[data-dep-nouvelle-techno="${CSS.escape(code)}"]`)?.value || "LTE";
      const nom = (champ?.value || "").trim();
      if (!dep || !nom) return;
      const deja = Object.values(etat.deploiements).some((d) => cellulesDeployees(d).some(([n, t]) => n === nom && t === techno));
      if (!deja) dep.secteurs[0].cellules.push([nom, techno]);
      apresChangementMobile(code);
      panneau.querySelector(`[data-dep-nouvelle="${CSS.escape(code)}"]`)?.focus();
    }

    panneau.addEventListener("click", (event) => {
      const cible = event.target.closest("button, input[data-site-entier]");
      if (!cible) return;
      const d = cible.dataset;
      if (d.deployer) {
        deployer(mobiles.get(d.deployer));
        return;
      }
      if (d.retirerMobile) {
        event.preventDefault();
        retirerDeploiement(d.retirerMobile);
        return;
      }
      if (d.depPointer) {
        if (pointage === d.depPointer) arreterPointage(); else commencerPointage(d.depPointer);
        return;
      }
      if (d.depAjouterSecteur) {
        const dep = etat.deploiements[d.depAjouterSecteur];
        const numero = [1, 2, 3, 4, 5, 6, 7, 8, 9].find((x) => !dep.secteurs.some((s) => s.numero === x));
        if (numero) dep.secteurs.push({ numero, azimut: null, cellules: [] });
        dep.secteurs.sort((a, b) => a.numero - b.numero);
        apresChangementMobile(d.depAjouterSecteur);
        return;
      }
      if (d.depRetirerSecteur) {
        const dep = etat.deploiements[d.depRetirerSecteur];
        dep.secteurs = dep.secteurs.filter((s) => s.numero !== Number(d.numero));
        apresChangementMobile(d.depRetirerSecteur);
        return;
      }
      if (d.depAjouterCellule) {
        ajouterCelluleMobile(d.depAjouterCellule);
        return;
      }
      if (cible.dataset.retirerSite) {
        event.preventDefault();
        viderSite(sites.get(cible.dataset.retirerSite));
        apresChangement(sites.get(cible.dataset.retirerSite));
      } else if (cible.dataset.siteEntier) {
        const site = sites.get(cible.dataset.siteEntier);
        if (cible.checked) choisirSite(site); else viderSite(site);
        apresChangement(site);
      } else if (cible.dataset.secteur) {
        basculerSecteur(secteurs.get(cible.dataset.secteur));
      } else if (cible.dataset.cellule) {
        basculerCellule(cellules.get(cible.dataset.cellule));
      } else if (cible.dataset.retirerCode) {
        retirerCode(cible.dataset.retirerCode);
      } else if (cible.dataset.centrer) {
        centrerSur(sites.get(cible.dataset.centrer));
      }
    });

    // ---------------------------------------------------------------- recherche
    let resultats = [], actif = -1;

    function chercher(texte) {
      const q = normaliser(texte);
      if (q.length < 2) return [];
      const trouves = [];
      for (const site of sites.values()) {
        let rang = -1;
        if (site.code.startsWith(q) || site.trigramme === q) rang = 0;
        else if (normaliser(site.nom).startsWith(q)) rang = 1;
        else if (site.cle.includes(q)) rang = 2;
        if (rang >= 0) trouves.push({ type: "site", objet: site, rang });
      }
      for (const m of mobiles.values()) {
        if (m.code.startsWith(q) || m.trigramme === q || normaliser(m.nom).startsWith(q) || m.cle.includes(q)) {
          trouves.push({ type: "mobile", objet: m, rang: -1 });
        }
      }
      trouves.sort((a, b) => a.rang - b.rang || a.objet.code.localeCompare(b.objet.code));
      const liste = trouves.slice(0, 8);
      if (q.length >= 4) {
        let n = 0;
        for (const sec of secteurs.values()) {
          if (sec.code.startsWith(q) && n++ < 4) liste.push({ type: "secteur", objet: sec });
        }
      }
      if (q.length >= 3) {
        let n = 0;
        for (const c of cellules.values()) {
          if (normaliser(c.nom).startsWith(q) && n++ < 6) liste.push({ type: "cellule", objet: c });
        }
      }
      return liste;
    }

    function libelleResultat({ type, objet }) {
      if (type === "mobile") {
        return [el("span", { class: "ev-sugg-type mobile", text: "Mobile" }),
          el("span", { class: "ev-sugg-texte" }, el("strong", { text: objet.nom }),
            el("small", { text: `${objet.code} · remorque : position et secteurs à déclarer` })),
          el("span", { class: "ev-sugg-action", text: etat.deploiements[objet.code] ? "Déjà sélectionnée" : "Ajouter la remorque" })];
      }
      if (type === "site") {
        const e = etatSite(objet);
        return [el("span", { class: "ev-sugg-type", text: "Site" }),
          el("span", { class: "ev-sugg-texte" }, el("strong", { text: objet.nom }),
            el("small", { text: `${objet.code} · ${objet.commune} · ${pluriel(objet.secteurs.length, "secteur")}, ${pluriel(objet.nbCellules, "cellule")}` })),
          el("span", { class: "ev-sugg-action", text: e === "choisi" ? "Déjà sélectionné" : "Ajouter le site entier" })];
      }
      if (type === "secteur") {
        return [el("span", { class: "ev-sugg-type", text: "Secteur" }),
          el("span", { class: "ev-sugg-texte" }, el("strong", { text: objet.code }),
            el("small", { text: `${objet.site.nom} · secteur ${objet.numero}${objet.azimut == null ? "" : ` · ${libelleAzimut(objet.azimut, objet.site.secteurs.length)}`}` })),
          el("span", { class: "ev-sugg-action", text: etatSecteur(objet) === "choisi" ? "Déjà sélectionné" : "Ajouter le secteur" })];
      }
      return [el("span", { class: "ev-sugg-type", text: TECHNO[objet.techno] }),
        el("span", { class: "ev-sugg-texte" }, el("strong", { text: objet.nom }),
          el("small", { text: objet.secteur ? `${objet.site.nom} · secteur ${objet.secteur.numero}` : "Cellule sans site connu" })),
        el("span", { class: "ev-sugg-action", text: celluleIncluse(objet) ? "Déjà sélectionnée" : "Ajouter la cellule" })];
    }

    function afficherSuggestions() {
      resultats = chercher(recherche.value);
      actif = resultats.length ? 0 : -1;
      if (!resultats.length) {
        suggestions.replaceChildren(...(normaliser(recherche.value).length >= 2
          ? [el("li", { class: "ev-sugg-vide", text: "Aucun site, secteur ou cellule ne correspond." })] : []));
      } else {
        suggestions.replaceChildren(...resultats.map((r, i) => el("li", {
          id: `ev-sugg-${i}`, role: "option", class: "ev-sugg", "data-index": i, "aria-selected": String(i === actif),
        }, ...libelleResultat(r))));
      }
      const visible = suggestions.children.length > 0;
      suggestions.hidden = !visible;
      recherche.setAttribute("aria-expanded", String(visible));
      recherche.setAttribute("aria-activedescendant", actif >= 0 ? `ev-sugg-${actif}` : "");
    }

    function fermerSuggestions() {
      suggestions.hidden = true;
      recherche.setAttribute("aria-expanded", "false");
    }

    function choisirResultat(index) {
      const r = resultats[index];
      if (!r) return;
      if (r.type === "mobile") {
        deployer(r.objet);
      } else if (r.type === "site") {
        if (etatSite(r.objet) !== "choisi") choisirSite(r.objet);
        ouverts.add(r.objet.code);
        apresChangement(r.objet);
        centrerSur(r.objet);
      } else if (r.type === "secteur") {
        if (etatSecteur(r.objet) !== "choisi") basculerSecteur(r.objet);
        ouverts.add(r.objet.site.code);
        rendreSelection();
        centrerSur(r.objet.site);
      } else {
        if (!celluleIncluse(r.objet)) basculerCellule(r.objet);
        if (r.objet.site) { ouverts.add(r.objet.site.code); rendreSelection(); centrerSur(r.objet.site); }
      }
      recherche.value = "";
      fermerSuggestions();
      recherche.focus();
    }

    recherche.addEventListener("input", afficherSuggestions);
    recherche.addEventListener("focus", () => { if (recherche.value) afficherSuggestions(); });
    recherche.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();  // jamais d'envoi du formulaire depuis la recherche
        if (!suggestions.hidden && actif >= 0) choisirResultat(actif);
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!resultats.length) return;
        event.preventDefault();
        actif = (actif + (event.key === "ArrowDown" ? 1 : -1) + resultats.length) % resultats.length;
        for (const li of suggestions.children) li.setAttribute("aria-selected", String(Number(li.dataset.index) === actif));
        suggestions.children[actif]?.scrollIntoView({ block: "nearest" });
        recherche.setAttribute("aria-activedescendant", `ev-sugg-${actif}`);
      } else if (event.key === "Escape") {
        fermerSuggestions();
      }
    });
    suggestions.addEventListener("mousedown", (event) => {
      const li = event.target.closest("[data-index]");
      if (!li) return;
      event.preventDefault();
      choisirResultat(Number(li.dataset.index));
    });
    recherche.addEventListener("blur", () => setTimeout(fermerSuggestions, 100));

    // ---------------------------------------------------------------- carte
    const OUVERTURE = 60;  // ouverture indicative d'un secteur, en degrés
    const RAYON = 30;      // rayon des secteurs dessinés, en pixels
    // Secteurs toujours dessinés ; réduits en vue éloignée pour rester lisibles.
    const ZOOM_MOYEN = 13, ZOOM_LOIN = 10;

    function angle(azimut, numero, nb) {
      return azimut != null ? azimut : ((numero - 1) * 360) / Math.max(nb, 1);
    }

    function cheminSecteur(cx, cy, r, az, plein = false) {
      if (plein) return `M${cx - r},${cy} a${r},${r} 0 1 0 ${2 * r},0 a${r},${r} 0 1 0 ${-2 * r},0 Z`;  // omni
      const point = (deg) => {
        const rad = (deg * Math.PI) / 180;
        return `${(cx + r * Math.sin(rad)).toFixed(2)},${(cy - r * Math.cos(rad)).toFixed(2)}`;
      };
      return `M${cx},${cy} L${point(az - OUVERTURE / 2)} A${r},${r} 0 0 1 ${point(az + OUVERTURE / 2)} Z`;
    }

    function iconeSite(site) {
      const t = RAYON + 4, etatGlobal = etatSite(site);
      const nb = site.secteurs.length;
      const coins = site.secteurs.map((sec) => {
        const e = etatSecteur(sec);
        const titre = `${site.nom} · secteur ${sec.numero} · ${libelleAzimut(sec.azimut, nb)} · ${pluriel(sec.cellules.length, "cellule")}`;
        return `<path class="ev-coin etat-${e}${sec.azimut == null ? " estime" : ""}" data-secteur="${sec.code}" d="${cheminSecteur(t, t, RAYON, angle(sec.azimut, sec.numero, nb), omni(sec.azimut, nb))}"><title>${echapper(titre)}</title></path>`;
      }).join("");
      const centre = `<circle class="ev-centre etat-${etatGlobal}" data-site-centre="${site.code}" cx="${t}" cy="${t}" r="6"><title>${echapper(`${site.nom} (${site.code}) : site entier`)}</title></circle>`;
      return L.divIcon({
        className: `ev-marqueur etat-${etatGlobal}`,
        html: `<svg width="${2 * t}" height="${2 * t}" viewBox="0 0 ${2 * t} ${2 * t}">${coins}${centre}</svg>`
          + `<span class="ev-marqueur-nom">${echapper(site.nom)}</span>`,
        iconSize: [2 * t, 2 * t],
        iconAnchor: [t, t],
      });
    }

    function echapper(texte) {
      return String(texte).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    }

    function iconeMobile(code) {
      const dep = etat.deploiements[code];
      const t = RAYON + 4, nb = dep.secteurs.length;
      const coins = dep.secteurs.map((sec) => {
        const titre = `${nomMobile(code)} (site mobile) · secteur ${sec.numero} · ${libelleAzimut(sec.azimut, nb)} · ${pluriel(sec.cellules.length, "cellule")}`;
        return `<path class="ev-coin etat-choisi mobile${sec.azimut == null ? " estime" : ""}" d="${cheminSecteur(t, t, RAYON, angle(sec.azimut, sec.numero, nb), omni(sec.azimut, nb))}"><title>${echapper(titre)}</title></path>`;
      }).join("");
      return L.divIcon({
        className: "ev-marqueur ev-marqueur-mobile etat-choisi",
        html: `<svg width="${2 * t}" height="${2 * t}" viewBox="0 0 ${2 * t} ${2 * t}">${coins}`
          + `<rect class="ev-centre-mobile" x="${t - 6}" y="${t - 6}" width="12" height="12" rx="3"/></svg>`
          + `<span class="ev-marqueur-nom">${echapper(nomMobile(code))}</span>`,
        iconSize: [2 * t, 2 * t],
        iconAnchor: [t, t],
      });
    }

    function dessinerMobile(code) {
      if (!carte) return;
      const dep = etat.deploiements[code];
      const ancien = marqueursMobiles.get(code);
      if (!dep || dep.lat == null || dep.lon == null || Math.abs(dep.lat) > 90 || Math.abs(dep.lon) > 180) {
        if (ancien) { ancien.remove(); marqueursMobiles.delete(code); }
        return;
      }
      if (ancien) {
        ancien.setLatLng([dep.lat, dep.lon]);
        ancien.setIcon(iconeMobile(code));
      } else {
        marqueursMobiles.set(code, L.marker([dep.lat, dep.lon], { icon: iconeMobile(code), keyboard: false,
                                                                   interactive: false, zIndexOffset: 2000 }).addTo(carte));
      }
    }

    function commencerPointage(code) {
      pointage = code;
      cadreCarte.classList.add("ev-pointage");
      rendreSelection();
      cadreCarte.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }

    function arreterPointage() {
      pointage = null;
      cadreCarte.classList.remove("ev-pointage");
      rendreSelection();
    }

    function placer(latlng) {
      const dep = etat.deploiements[pointage];
      const code = pointage;
      pointage = null;
      cadreCarte.classList.remove("ev-pointage");
      if (!dep) return;
      dep.lat = Number(latlng.lat.toFixed(6));
      dep.lon = Number(latlng.lng.toFixed(6));
      replies.delete(`mobile:${code}`);
      apresChangementMobile(code);
    }

    function dessinerSite(site) {
      const marqueur = marqueurs.get(site.code);
      if (!marqueur) return;
      marqueur.setIcon(iconeSite(site));
      marqueur.setZIndexOffset(etatSite(site) === "libre" ? 0 : 1000);
    }

    function initialiserCarte() {
      if (!window.L) {
        cadreCarte.replaceChildren(el("p", { class: "ev-vide erreur", text: "Carte indisponible." }));
        return;
      }
      carte = L.map(cadreCarte, { zoomSnap: 0.5, minZoom: 6, maxZoom: 18, worldCopyJump: false });
      if (zone.dataset.tuiles) {
        // Le serveur OpenStreetMap refuse les tuiles demandées sans Referer : la page en envoie (same-origin,
        // réglage de Django), les tuiles reçoivent au moins l'origine du site.
        L.tileLayer(zone.dataset.tuiles, { maxZoom: 19, attribution: zone.dataset.attribution || "",
                                           referrerPolicy: "strict-origin-when-cross-origin" }).addTo(carte);
      }
      carte.attributionControl.setPrefix(false);
      const points = [];
      for (const site of sites.values()) {
        if (site.lat == null || site.lon == null) continue;
        const marqueur = L.marker([site.lat, site.lon], { icon: iconeSite(site), keyboard: false, riseOnHover: true });
        marqueur.on("click", (event) => {
          if (pointage) { placer(event.latlng); return; }
          const cible = event.originalEvent.target.closest?.("[data-secteur], [data-site-centre]");
          if (!cible) return;
          if (cible.dataset.secteur) basculerSecteur(secteurs.get(cible.dataset.secteur));
          else basculerSite(site);
          ouverts.add(site.code);
          rendreSelection();
        });
        marqueur.addTo(carte);
        if (etatSite(site) !== "libre") marqueur.setZIndexOffset(1000);
        marqueurs.set(site.code, marqueur);
        points.push([site.lat, site.lon]);
      }
      const ajusterZoom = () => {
        const zoom = carte.getZoom();
        cadreCarte.classList.toggle("ev-z-loin", zoom < ZOOM_LOIN);
        cadreCarte.classList.toggle("ev-z-moyen", zoom >= ZOOM_LOIN && zoom < ZOOM_MOYEN);
      };
      carte.on("zoomend", ajusterZoom);
      carte.on("click", (event) => { if (pointage) placer(event.latlng); });
      document.addEventListener("keydown", (event) => { if (event.key === "Escape" && pointage) arreterPointage(); });
      Object.keys(etat.deploiements).forEach(dessinerMobile);
      if (!recentrer(false) && points.length) carte.fitBounds(points, { padding: [20, 20] });
      ajusterZoom();
    }

    function recentrer(anime = true) {
      if (!carte) return false;
      const points = ordre.map((c) => sites.get(c)).filter((s) => s && s.lat != null).map((s) => [s.lat, s.lon]);
      for (const marqueur of marqueursMobiles.values()) points.push(marqueur.getLatLng());
      if (!points.length) return false;
      const options = { padding: [60, 60], maxZoom: 15, animate: anime };
      if (points.length === 1) carte.setView(points[0], 15, { animate: anime });
      else carte.fitBounds(points, options);
      return true;
    }

    function centrerSur(site) {
      if (!carte || !site || site.lat == null) return;
      carte.flyTo([site.lat, site.lon], Math.max(carte.getZoom(), 15), { duration: 0.6 });
    }

    zone.querySelector("[data-recentrer]").addEventListener("click", () => recentrer());
  }

  // ------------------------------------------------------------------ KPI
  const blocKpis = formulaire.querySelector("[data-kpis]");
  if (blocKpis) {
    const liste = blocKpis.querySelector("[data-kpis-liste]");
    const compteur = blocKpis.querySelector("[data-nb-kpis]");
    const maj = () => {
      const choisir = blocKpis.querySelector('input[name="kpis_choisis"]:checked')?.value === "true";
      liste.hidden = !choisir;
      const n = liste.querySelectorAll('input[name="kpis"]:checked').length;
      compteur.textContent = choisir ? `${n} coché${n > 1 ? "s" : ""}` : "";
    };
    blocKpis.addEventListener("change", maj);
    maj();
  }
})();
