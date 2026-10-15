/* Écran de recherche KPI : graphiques ECharts (servi localement) et confort des puces.
   La page fonctionne sans JavaScript (formulaires GET et tableaux). */
(function () {
  "use strict";

  var MARINE = "#256b51", AMBRE = "#c59542", ROUGE = "#c0392b";
  var PALETTE = ["#256b51", "#9abd87", "#527da7", "#7c3aed", "#c2410c", "#2563eb", "#be185d", "#4d7c0f",
                 "#0891b2", "#92400e", "#64748b", "#a21caf"];
  var graphiques = [];
  var vues = [], periodeSelectionnee = null, popup = null, vuePopup = null;

  /* Les clés ISO permettent de relier les heures malgré des libellés différents
     (14h / 12/10 14h) et des périodes absentes dans une technologie. */
  function mettreEnAvant(vue) {
    if (!vue.cles.length) return;
    var index = vue.cles.indexOf(periodeSelectionnee);
    var actif = index >= 0;
    var series = vue.option.series.map(function (s, i) {
      var copie = Object.assign({}, s);
      copie.lineStyle = Object.assign({}, s.lineStyle, { opacity: (s.lineStyle && s.lineStyle.opacity !== undefined ? s.lineStyle.opacity : 1) * (actif ? 0.3 : 1) });
      copie.areaStyle = s.areaStyle ? Object.assign({}, s.areaStyle, { opacity: actif ? 0.2 : 1 }) : undefined;
      copie.data = s.data.map(function (v, n) {
        return { value: v, itemStyle: { opacity: actif && n !== index ? 0.25 : 1 } };
      });
      copie.markPoint = { silent: true, symbol: "circle", symbolSize: 10,
        label: { show: false }, itemStyle: { opacity: 1, borderColor: "#fff", borderWidth: 2 },
        data: actif && !s.silent && s.type === "line" && s.data[index] !== null ? [{ coord: [index, s.data[index]] }] : [] };
      if (i === 0) {
        copie.markLine = Object.assign({}, s.markLine, { silent: true, symbol: "none", label: { show: false },
          data: (s.markLine ? s.markLine.data : []).concat(actif ? [{ xAxis: index,
            lineStyle: { color: MARINE, width: 2, type: "solid", opacity: 0.65 } }] : []) });
      }
      return copie;
    });
    vue.g.setOption({ series: series });
    vue.etat.textContent = actif ? "Période sélectionnée : " + vue.periodes[index] : "";
  }

  function selectionner(vue, index) {
    var cle = vue.cles[index];
    if (!cle) return;
    periodeSelectionnee = periodeSelectionnee === cle ? null : cle;
    vues.forEach(mettreEnAvant);
    if (vuePopup) mettreEnAvant(vuePopup);
  }

  /* Sélection d'une période : clic sur le graphique (nouveau clic sur la même période pour l'effacer). */
  function commandes(vue, parent) {
    var barre = document.createElement("div");
    barre.className = "graphique-commandes";
    vue.etat = document.createElement("span");
    vue.etat.className = "graphique-selection";
    vue.etat.setAttribute("role", "status");
    barre.appendChild(vue.etat);
    parent.appendChild(barre);
    return barre;
  }

  function interactions(vue, agrandir) {
    vue.g.on("click", function (e) {
      if (e.componentType === "xAxis" && vue.cles.length) {
        selectionner(vue, vue.periodes.indexOf(e.value));
      } else if (agrandir && (e.componentType === "title" || (!vue.cles.length && e.componentType === "series"))) {
        ouvrirGraphique(vue);
      }
    });
    vue.g.getZr().on("click", function (e) {
      var point = [e.offsetX, e.offsetY];
      if (vue.cles.length && vue.g.containPixel({ gridIndex: 0 }, point)) {
        selectionner(vue, Math.round(vue.g.convertFromPixel({ xAxisIndex: 0 }, e.offsetX)));
      } else if (agrandir && !e.target) {
        ouvrirGraphique(vue);
      }
    });
  }

  function ouvrirGraphique(vue) {
    if (!popup) {
      popup = document.createElement("dialog");
      popup.className = "graphique-popup";
      popup.setAttribute("aria-labelledby", "titre-graphique-popup");
      popup.innerHTML = '<div class="graphique-popup-entete"><h2 id="titre-graphique-popup"></h2>' +
        '<button type="button" class="graphique-action" autofocus aria-label="Fermer le graphique agrandi">Fermer ×</button></div>' +
        '<p class="aide">Cliquez sur une période pour la mettre en avant sur les graphiques ; un nouveau clic l\'efface.</p>' +
        '<div class="graphique-popup-canvas" role="img"></div><div class="graphique-popup-pied"></div>';
      document.body.appendChild(popup);
      popup.querySelector("button").addEventListener("click", function () { popup.close(); });
      popup.addEventListener("click", function (e) {
        var r = popup.getBoundingClientRect();
        if (e.target === popup && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) popup.close();
      });
      popup.addEventListener("close", function () {
        if (vuePopup) {
          var bouton = vuePopup.retour;
          vuePopup.g.dispose();
          vuePopup = null;
          bouton.focus({ preventScroll: true });
        }
        document.body.classList.remove("graphique-popup-ouverte");
      });
    }
    popup.querySelector("h2").textContent = vue.titre;
    popup.querySelector(".aide").hidden = !vue.cles.length;
    var div = popup.querySelector(".graphique-popup-canvas");
    div.setAttribute("aria-label", vue.titre + " : graphique agrandi");
    var pied = popup.querySelector(".graphique-popup-pied");
    pied.replaceChildren();
    document.body.classList.add("graphique-popup-ouverte");
    popup.showModal();
    var g = echarts.init(div, null, { renderer: "canvas" });
    g.setOption(vue.g.getOption());
    vuePopup = { g: g, option: vue.option, cles: vue.cles, periodes: vue.periodes, titre: vue.titre, retour: vue.retour };
    commandes(vuePopup, pied);
    interactions(vuePopup, false);
    mettreEnAvant(vuePopup);
  }

  function nombre(v, unite) {
    if (v === null || v === undefined || isNaN(v)) return "N/D";
    var a = Math.abs(v), d = a >= 100 ? 0 : a >= 10 ? 1 : a >= 0.1 || a === 0 ? 2 : 3;
    return v.toLocaleString("fr-FR", { maximumFractionDigits: d, minimumFractionDigits: 0 }) + (unite ? " " + unite : "");
  }

  /* Graduation d'axe : valeur exacte du repère (jamais deux libellés identiques). */
  function graduation(v) {
    return (Math.round(v * 1e6) / 1e6).toLocaleString("fr-FR", { maximumFractionDigits: 6 });
  }

  /* Seuils dont la ligne tombe dans l'axe Y affiché (les autres ne sont ni tracés ni légendés). */
  function seuilsVisibles(seuils, bornes) {
    var visible = function (s) {
      return s !== null && s !== undefined && bornes.min !== undefined && s >= bornes.min && s <= bornes.max;
    };
    return { alerte: visible(seuils.alerte) ? seuils.alerte : null,
             critique: visible(seuils.critique) ? seuils.critique : null };
  }

  /* Légende des seuils dans le sous-titre : jamais superposée aux courbes. */
  function sousTitreSeuils(seuils) {
    var morceaux = [];
    if (seuils.alerte !== null) morceaux.push("{a|━ ━} alerte " + nombre(seuils.alerte));
    if (seuils.critique !== null) morceaux.push("{c|━ ━} critique " + nombre(seuils.critique));
    return morceaux.join("     ");
  }

  function initialiser(div, option, cles, titre) {
    option.animation = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    option.xAxis.triggerEvent = true;
    if (option.title) option.title.triggerEvent = true;
    var g = echarts.init(div, null, { renderer: "canvas" });
    g.setOption(option);
    graphiques.push(g);
    var vue = { g: g, option: option, cles: cles || [], periodes: option.xAxis.data, titre: titre || div.getAttribute("aria-label") };
    vues.push(vue);
    commandes(vue, div.parentNode);
    // Agrandir : clic hors de la zone tracée ; au clavier, Entrée ou Espace sur le graphique.
    div.tabIndex = 0;
    div.setAttribute("aria-haspopup", "dialog");
    div.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      ouvrirGraphique(vue);
    });
    vue.retour = div;
    interactions(vue, true);
    return g;
  }

  function pasRond(etendue) {
    var brut = etendue / 5, p = Math.pow(10, Math.floor(Math.log10(brut || 1)));
    var r = brut / p;
    return (r <= 1 ? 1 : r <= 2 ? 2 : r <= 2.5 ? 2.5 : r <= 5 ? 5 : 10) * p;
  }

  /* Axe des ordonnées : inclut les seuils (contexte), part de 0 pour un volume ou un taux de
     coupure, borné à 100 pour un pourcentage. */
  function bornesAxe(g) {
    var valeurs = [];
    g.series.forEach(function (s) { s.valeurs.forEach(function (v) { if (v !== null) valeurs.push(v); }); });
    if (!valeurs.length) return {};
    // Un seuil proche des valeurs est inclus (repère) ; un seuil lointain écraserait la courbe.
    var lo = Math.min.apply(null, valeurs), hi = Math.max.apply(null, valeurs);
    var ecart = Math.max(hi - lo, Math.abs(hi) * 0.05, 1e-9);
    [g.seuils.alerte, g.seuils.critique].forEach(function (s) {
      if (s !== null && s !== undefined && s >= lo - 2 * ecart && s <= hi + 2 * ecart) valeurs.push(s);
    });
    var bas = Math.min.apply(null, valeurs), haut = Math.max.apply(null, valeurs);
    if (g.zero) bas = Math.min(0, bas);
    var pas = pasRond((haut - bas) || Math.abs(haut) || 1);
    var min = Math.floor(bas / pas) * pas, max = Math.ceil((haut + pas * 0.15) / pas) * pas;
    if (g.unite === "%") { min = Math.max(0, min); max = Math.min(100, max); }
    if (max <= min) max = min + pas;
    return { min: min, max: max, interval: pas };
  }

  function axeY(bornes) {
    return Object.assign({ type: "value", axisLabel: { color: "#5f6878", fontSize: 11, formatter: graduation },
                           splitLine: { lineStyle: { color: "#eef1f6" } } }, bornes);
  }

  function courbes(zone) {
    var donnees = JSON.parse(document.getElementById(zone.dataset.source).textContent);
    // Tous les conteneurs d'abord : la grille connaît alors sa largeur finale.
    var cibles = donnees.kpis.map(function (g) {
      var carte = document.createElement("figure");
      carte.className = "carte-graphique";
      carte.style.margin = "0";
      var div = document.createElement("div");
      div.className = "graphique";
      div.setAttribute("role", "img");
      div.setAttribute("aria-label", "Évolution : " + g.titre);
      carte.appendChild(div);
      zone.appendChild(carte);
      return div;
    });
    donnees.kpis.forEach(function (g, n) {
      var bornes = bornesAxe(g);
      var visibles = seuilsVisibles(g.seuils, bornes);
      var seuils = [];
      if (visibles.alerte !== null) seuils.push({ yAxis: visibles.alerte, name: "alerte", lineStyle: { color: AMBRE, type: "dashed", width: 1.5 } });
      if (visibles.critique !== null) seuils.push({ yAxis: visibles.critique, name: "critique", lineStyle: { color: ROUGE, type: "dashed", width: 1.5 } });
      var legende = sousTitreSeuils(visibles);
      var plusieurs = g.series.length > 1;
      var series = g.series.map(function (s, i) {
        var serie = { name: s.nom, type: "line", data: s.valeurs, connectNulls: false, smooth: false,
                      showSymbol: s.valeurs.length < 40, symbolSize: 5, lineStyle: { width: plusieurs ? 1.8 : 2.5 },
                      emphasis: { focus: "series" } };
        if (!plusieurs) serie.areaStyle = { color: "rgba(37,107,81,.06)" };
        if (i === 0 && seuils.length) serie.markLine = { symbol: "none", silent: true, label: { show: false }, data: seuils };
        return serie;
      });
      initialiser(cibles[n], {
        color: PALETTE,
        title: { text: g.titre + " (" + g.unite + ")", left: 4, top: 2, itemGap: 6,
                 textStyle: { fontSize: 13, color: MARINE, fontWeight: 600 },
                 subtext: legende, subtextStyle: { fontSize: 11, color: "#4b5567",
                   rich: { a: { color: AMBRE, fontWeight: 700 }, c: { color: ROUGE, fontWeight: 700 } } } },
        tooltip: { trigger: "axis", valueFormatter: function (v) { return nombre(v, g.unite); } },
        legend: plusieurs ? { type: "scroll", bottom: 0, textStyle: { fontSize: 11 } } : { show: false },
        grid: { left: 8, right: 16, top: legende ? 60 : 40, bottom: plusieurs ? 40 : 12, containLabel: true },
        xAxis: { type: "category", data: donnees.periodes, boundaryGap: false, axisLabel: { color: "#5f6878", fontSize: 11 },
                 axisLine: { lineStyle: { color: "#c3ccda" } } },
        yAxis: axeY(bornes),
        series: series
      }, donnees.periodes_cles, g.titre);
    });
  }

  /* Graphiques thématiques (config/graphes.yaml) : plusieurs KPI sur un graphique, barres,
     barres empilées, courbes ou aires, axe de gauche ou de droite ; un graphique par entité, choisie
     dans la liste (data-graphes-entite). */
  /* Bornes d'un axe : depuis 0 s'il porte des barres, cumul des barres empilées, 100 au plus en %. */
  function bornesTheme(series, depuisZero, pourcent) {
    var valeurs = [], piles = {};
    series.forEach(function (s) {
      s.data.forEach(function (v, i) {
        if (v === null || v === undefined) return;
        if (s.stack) piles[i] = (piles[i] || 0) + Math.max(v, 0);
        else valeurs.push(v);
      });
    });
    Object.keys(piles).forEach(function (i) { valeurs.push(piles[i]); });
    if (!valeurs.length) return {};
    var bas = Math.min.apply(null, valeurs), haut = Math.max.apply(null, valeurs);
    if (depuisZero) bas = Math.min(0, bas);
    var pas = pasRond((haut - bas) || Math.abs(haut) || 1);
    var min = Math.floor(bas / pas) * pas, max = Math.ceil((haut + pas * 0.15) / pas) * pas;
    // En %, borné à [0, 100] sauf si les données en sortent (ratio publié > 100 %, échec négatif).
    if (pourcent && bas >= 0) min = Math.max(0, min);
    if (pourcent && haut <= 100) max = Math.min(100, max);
    if (max <= min) {  // valeur constante (ex. disponibilité à 100 %) : la courbe reste en haut
      if (pourcent && max >= 100) min = Math.max(0, max - pas);
      else max = min + pas;
    }
    return { min: min, max: max, interval: pas };
  }

  /* Lignes de légende (retour à la ligne, jamais tronquée) : sert à réserver la marge du bas. */
  function lignesLegende(noms, largeur) {
    var lignes = 1, occupe = 0, dispo = Math.max(largeur - 24, 200);
    noms.forEach(function (nom) {
      var l = nom.length * 6.1 + 36;
      if (occupe && occupe + l > dispo) { lignes += 1; occupe = 0; }
      occupe += l;
    });
    return lignes;
  }

  function optionTheme(g, donnees, n, largeur) {
    var series = g.series.map(function (s) {
      var data = donnees.valeurs[s.kpi][n];
      var serie = { name: s.nom + " (" + donnees.syntheses[s.kpi][n] + ")", data: data, axe: s.axe,
                    emphasis: { focus: "series" }, unite: s.unite };
      if (s.type === "ligne" || s.type === "aire") {
        Object.assign(serie, { type: "line", connectNulls: false, showSymbol: data.length < 40, symbolSize: 5,
                               lineStyle: { width: 2.2 }, z: 3 });
        if (s.type === "aire") Object.assign(serie, { areaStyle: { opacity: 0.12 }, z: 1 });
        return serie;
      }
      serie.type = "bar";
      serie.barMaxWidth = 28;
      if (s.type === "barres_empilees") serie.stack = "pile";
      return serie;
    });
    var gauche = series.filter(function (s) { return s.axe === "gauche"; });
    var droite = series.filter(function (s) { return s.axe === "droite"; });
    if (!gauche.length) { gauche = droite; droite = []; }
    var yAxis = [gauche, droite].map(function (liste, i) {
      var unites = [];
      liste.forEach(function (s) { if (unites.indexOf(s.unite) < 0) unites.push(s.unite); });
      liste.forEach(function (s) { s.yAxisIndex = i; });
      var bornes = bornesTheme(liste, liste.some(function (s) { return s.type === "bar"; }),
                               unites.length === 1 && unites[0] === "%");
      return Object.assign({ type: "value", name: unites.join(" · "), position: i ? "right" : "left", show: liste.length > 0,
                             nameTextStyle: { color: "#5f6878", fontSize: 11, align: i ? "right" : "left" },
                             axisLabel: { color: "#5f6878", fontSize: 11, formatter: graduation },
                             splitLine: { show: i === 0, lineStyle: { color: "#eef1f6" } } }, bornes);
    });
    var unites = {};
    series.forEach(function (s) { unites[s.name] = s.unite; delete s.axe; });
    var lignes = lignesLegende(series.map(function (s) { return s.name; }), largeur || 460);
    return {
      color: PALETTE,
      title: { text: g.titre, left: 4, top: 2, textStyle: { fontSize: 13, color: MARINE, fontWeight: 600 } },
      tooltip: { trigger: "axis", confine: true, axisPointer: { type: "shadow" },
                 formatter: function (points) {
                   if (!points.length) return "";
                   return points[0].axisValueLabel + points.map(function (p) {
                     var v = p.value !== null && typeof p.value === "object" ? p.value.value : p.value;
                     return "<br>" + p.marker + p.seriesName.replace(/ \([^()]*\)$/, "") + " : <strong>" +
                       nombre(v, unites[p.seriesName]) + "</strong>";
                   }).join("");
                 } },
      legend: { type: "plain", bottom: 4, left: 8, right: 8, itemGap: 12, itemHeight: 10, textStyle: { fontSize: 11 } },
      grid: { left: 8, right: droite.length ? 8 : 16, top: 52, bottom: 12 + lignes * 20, containLabel: true },
      xAxis: { type: "category", data: donnees.periodes, boundaryGap: true, axisLabel: { color: "#5f6878", fontSize: 11 },
               axisLine: { lineStyle: { color: "#c3ccda" } } },
      yAxis: yAxis,
      series: series
    };
  }

  function graphesThemes(zone) {
    var donnees = JSON.parse(document.getElementById(zone.dataset.graphesThemes).textContent);
    var cibles = [];
    donnees.themes.forEach(function (t) {
      var titre = document.createElement("h4");
      titre.className = "titre-section";
      titre.id = zone.dataset.prefixe + t.code;
      titre.textContent = t.titre;
      zone.appendChild(titre);
      var grille = document.createElement("div");
      grille.className = "graphiques";
      zone.appendChild(grille);
      t.graphes.forEach(function (g) {
        var carte = document.createElement("figure");
        carte.className = "carte-graphique";
        carte.style.margin = "0";
        var div = document.createElement("div");
        div.className = "graphique graphique-theme";
        div.setAttribute("role", "img");
        div.setAttribute("aria-label", g.titre);
        carte.appendChild(div);
        grille.appendChild(carte);
        cibles.push({ g: g, div: div });
      });
    });
    var instances = cibles.map(function (c) {
      var g = initialiser(c.div, optionTheme(c.g, donnees, 0, c.div.clientWidth), donnees.periodes_cles, c.g.titre);
      return vues.filter(function (v) { return v.g === g; })[0];
    });
    var choix = document.querySelector('[data-graphes-entite="' + zone.dataset.graphesThemes + '"]');
    if (!choix) return;
    choix.addEventListener("change", function () {
      var n = Number(choix.value);
      cibles.forEach(function (c, i) {
        var vue = instances[i], option = optionTheme(c.g, donnees, n, c.div.clientWidth);
        option.animation = vue.option.animation;
        option.xAxis.triggerEvent = true;
        option.title.triggerEvent = true;
        vue.option = option;
        vue.g.setOption(option, true);
        mettreEnAvant(vue);
      });
    });
  }

  /* Courbes d'un événement : Global (événement, référence, bande min–max des semaines de référence),
     Par site ou Par cellule (valeurs de l'événement, une courbe par site / cellule, noms en légende). */
  var VUES_EVENEMENT = [["global", "Global"], ["site", "Par site"], ["cellule", "Par cellule"]];

  function optionEvenement(g, instants, vue) {
    var axeY = { type: "value", scale: true,
                 max: g.unite === "%" ? function (v) { return Math.min(100, Math.ceil(v.max)); } : null,
                 axisLabel: { formatter: function (v) { return (Math.round(v * 1e6) / 1e6).toLocaleString("fr-FR", { maximumFractionDigits: 6 }); } } };
    var base = {
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      aria: { enabled: true },
      title: { text: g.titre, textStyle: { fontSize: 13, color: "#256b51" } },
      xAxis: { type: "category", data: instants, triggerEvent: true, axisLabel: { hideOverlap: true } },
      yAxis: axeY
    };
    if (vue !== "global") {
      var detail = vue === "site" ? g.sites : g.cellules;
      return Object.assign(base, {
        color: PALETTE,
        tooltip: { trigger: "axis", confine: true, valueFormatter: function (v) { return nombre(v, g.unite); } },
        legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 11 } },
        grid: { left: 8, right: 16, top: 40, bottom: 44, containLabel: true },
        series: detail.map(function (s) {
          return { name: s.nom, type: "line", data: s.valeurs, symbolSize: 4, showSymbol: instants.length < 40,
                   lineStyle: { width: 1.8 }, emphasis: { focus: "series" } };
        })
      });
    }
    var ecart = g.max.map(function (v, i) { return v === null || g.min[i] === null ? null : v - g.min[i]; });
    return Object.assign(base, {
      tooltip: { trigger: "axis", confine: true, formatter: function (p) {
        var lignes = [p[0].axisValue], i = p[0].dataIndex;
        lignes.push("Événement : " + (g.evenement[i] === null ? "N/D" : g.evenement[i]));
        lignes.push("Référence : " + (g.reference[i] === null ? "N/D" : g.reference[i]));
        if (g.min[i] !== null) lignes.push("Réf. min – max : " + g.min[i] + " – " + g.max[i]);
        return lignes.join("<br>");
      } },
      legend: { bottom: 0, data: ["Événement", "Référence"] },
      grid: { left: 8, right: 16, top: 40, bottom: 40, containLabel: true },
      series: [
        { name: "min", type: "line", data: g.min, stack: "bande", symbol: "none", lineStyle: { opacity: 0 }, silent: true },
        { name: "bande", type: "line", data: ecart, stack: "bande", symbol: "none", lineStyle: { opacity: 0 },
          areaStyle: { color: "rgba(138,148,166,.25)" }, silent: true },
        { name: "Référence", type: "line", data: g.reference, color: "#c59542", lineStyle: { type: "dashed" } },
        { name: "Événement", type: "line", data: g.evenement, color: "#256b51", lineStyle: { width: 3 } }
      ]
    });
  }

  function courbesEvenement(zone) {
    var donnees = JSON.parse(document.getElementById(zone.dataset.source).textContent);
    // Tous les conteneurs d'abord : la grille connaît sa largeur finale avant le premier graphique
    // (sinon le premier, dessiné seul sur toute la largeur, déborde sur son voisin).
    var cibles = donnees.kpis.map(function (g) {
      var carte = document.createElement("figure");
      carte.className = "carte-graphique";
      carte.style.margin = "0";
      var div = document.createElement("div");
      div.className = "graphique";
      div.setAttribute("role", "img");
      div.setAttribute("aria-label", g.titre + " : événement et référence");
      carte.appendChild(div);
      zone.appendChild(carte);
      return div;
    });
    var instances = donnees.kpis.map(function (g, n) {
      var g2 = initialiser(cibles[n], optionEvenement(g, donnees.instants, "global"), donnees.instants, g.titre);
      return vues.filter(function (v) { return v.g === g2; })[0];
    });

    var barre = document.createElement("div");
    barre.className = "selecteur-vue courbes-vue";
    barre.setAttribute("role", "group");
    barre.setAttribute("aria-label", "Détail des courbes");
    var legende = zone.parentNode.querySelector("[data-legende-courbes]");
    var textes = { global: legende ? legende.textContent : "",
                   site: "Une courbe par site : valeurs pendant l'événement.",
                   cellule: "Une courbe par cellule : valeurs pendant l'événement." };
    VUES_EVENEMENT.forEach(function (v) {
      var bouton = document.createElement("button");
      bouton.type = "button";
      bouton.textContent = v[1];
      bouton.dataset.vue = v[0];
      bouton.setAttribute("aria-pressed", String(v[0] === "global"));
      bouton.addEventListener("click", function () {
        barre.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", String(b === bouton)); });
        if (legende) legende.textContent = textes[v[0]];
        donnees.kpis.forEach(function (g, n) {
          var vue = instances[n], option = optionEvenement(g, donnees.instants, v[0]);
          vue.option = option;
          vue.g.setOption(option, true);
          if (periodeSelectionnee) mettreEnAvant(vue);
        });
      });
      barre.appendChild(bouton);
    });
    zone.parentNode.insertBefore(barre, zone);
  }

  function causes(div) {
    var g = JSON.parse(document.getElementById(div.dataset.source).textContent);
    var noms = g.series.map(function (s) { return s.nom; });
    // Légende complète sur plusieurs lignes (pas de pagination) : hauteur adaptée.
    var largeur = Math.max(div.clientWidth || 600, 200);
    var occupe = noms.reduce(function (t, n) { return t + n.length * 6.3 + 38; }, 0);
    var lignes = Math.max(1, Math.ceil(occupe / (largeur - 24)));
    div.style.height = (300 + 22 * (lignes - 1)) + "px";
    initialiser(div, {
      color: PALETTE.slice(0, noms.length - 1).concat(noms[noms.length - 1] === "Non ventilé" ? ["#aab3c2"] : [PALETTE[noms.length - 1]]),
      title: { text: "Par " + g.par + " (" + g.unite + ")", left: 4, top: 2, textStyle: { fontSize: 13, color: MARINE, fontWeight: 600 } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: function (v) { return nombre(v, g.unite); } },
      legend: { type: "plain", bottom: 0, left: "center", width: largeur - 24, itemGap: 12, textStyle: { fontSize: 11 } },
      grid: { left: 8, right: 16, top: 40, bottom: 18 + 22 * lignes, containLabel: true },
      xAxis: { type: "category", data: g.axe, axisLabel: { color: "#5f6878", fontSize: 11 } },
      yAxis: axeY({}),
      series: g.series.map(function (s) {
        return { name: s.nom, type: "bar", stack: "causes", data: s.valeurs, barMaxWidth: 36, emphasis: { focus: "series" } };
      })
    }, g.periodes_cles, g.titre + " · par " + g.par);
  }

  /* Tableau détaillé : 13 lignes visibles, défilement vertical sous des en-têtes figés
     (hauteur mesurée : les lignes passent à la ligne sur mobile). */
  var LIGNES_VISIBLES = 13;
  function limiterHauteur(defil) {
    var lignes = defil.querySelectorAll("tbody tr");
    if (!defil.offsetParent) return;  // panneau masqué : mesuré à l'affichage
    if (lignes.length <= LIGNES_VISIBLES) { defil.style.maxHeight = ""; return; }
    // offsetTop (relatif au tableau) = en-tête + 13 lignes ; s'y ajoutent bordures et barre horizontale.
    defil.style.maxHeight = (lignes[LIGNES_VISIBLES].offsetTop + defil.offsetHeight - defil.clientHeight) + "px";
  }

  function texteCellule(cellule) {
    var copie = cellule.cloneNode(true);
    copie.querySelectorAll(".sur-mobile").forEach(function (e) { e.remove(); });
    var texte = copie.textContent.replace(/\s+/g, " ").trim();
    // Nombres sans séparateur de milliers : lus comme valeurs par Excel (virgule décimale).
    if (cellule.classList.contains("nombre")) texte = texte.replace(/[\s\u00a0\u202f]/g, "");
    return /[";\n]/.test(texte) ? '"' + texte.replace(/"/g, '""') + '"' : texte;
  }

  function exporterTableau(defil) {
    var lignes = Array.prototype.map.call(defil.querySelectorAll("tr"), function (tr) {
      return Array.prototype.map.call(tr.children, texteCellule).join(";");
    });
    var bloc = defil.closest("section.bloc-techno");
    var nom = "tableau-detaille" + (bloc && bloc.id ? "-" + bloc.id.replace(/^bloc-/, "") : "") + ".csv";
    var lien = document.createElement("a");
    lien.href = URL.createObjectURL(new Blob(["\ufeff" + lignes.join("\r\n")], { type: "text/csv;charset=utf-8" }));
    lien.download = nom;
    document.body.appendChild(lien);
    lien.click();
    lien.remove();
    setTimeout(function () { URL.revokeObjectURL(lien.href); }, 0);
  }

  function tableauDetaille(defil) {
    var outils = document.createElement("div");
    outils.className = "tableau-outils";
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "graphique-action";
    bouton.textContent = "Exporter le tableau (CSV)";
    bouton.addEventListener("click", function () { exporterTableau(defil); });
    outils.appendChild(bouton);
    defil.parentNode.insertBefore(outils, defil);
    var repliable = defil.closest("details");
    if (repliable) repliable.addEventListener("toggle", function () { limiterHauteur(defil); });
    limiterHauteur(defil);
  }

  /* Un seul espace pour lire une évolution : le contrôle remplace le graphique par le
     tableau, sans dupliquer deux blocs ouverts dans la page. */
  function basculeVisualisation(zone) {
    var boutons = zone.querySelectorAll("[data-vue]");
    var panneaux = zone.querySelectorAll("[data-vue-panneau]");
    function afficher(vue) {
      boutons.forEach(function (bouton) {
        var actif = bouton.dataset.vue === vue;
        bouton.setAttribute("aria-pressed", actif ? "true" : "false");
      });
      panneaux.forEach(function (panneau) { panneau.hidden = panneau.dataset.vuePanneau !== vue; });
      if (vue === "graphique") setTimeout(function () { graphiques.forEach(function (g) { g.resize(); }); }, 0);
      else zone.querySelectorAll(".tableau-detaille").forEach(limiterHauteur);
    }
    boutons.forEach(function (bouton) { bouton.addEventListener("click", function () { afficher(bouton.dataset.vue); }); });
    afficher(window.echarts ? "graphique" : "tableau");
  }

  /* Accueil : rapport type + lieu + période. Sans JavaScript, le formulaire fonctionne tel quel ;
     ici : dates précises affichées à la demande, « Sur mesure » ouvert quand on le choisit,
     lieux (sites) suggérés au fil de la saisie, et URL sans paramètres vides. */
  function choisirGraphiques(zone) {
    var form = zone.closest("form"), cases = zone.querySelectorAll('input[name="graphes"]');
    var personnalise = zone.querySelector('input[name="graphiques_personnalises"]');
    var recherche = zone.querySelector("[data-recherche-graphes]");
    var modelesNode = document.getElementById("rapports-composition");
    var modeles = modelesNode ? JSON.parse(modelesNode.textContent) : [];
    function compteur() {
      var n = Array.from(cases).filter(function (c) {return c.checked;}).length;
      zone.querySelector("[data-compteur-graphes]").textContent = "· " + n + " sélectionnés";
    }
    function rapport() {
      var radio = form.querySelector('input[name="intention"]:checked');
      var modele = modeles.find(function (r) {return radio && r.code === radio.value;});
      cases.forEach(function (c) {c.checked = !!modele && modele.graphes.includes(c.value);});
      personnalise.checked = false; compteur();
    }
    cases.forEach(function (c) {c.addEventListener("change", function () {personnalise.checked = true; compteur();});});
    personnalise.addEventListener("change", function () {
      if (!personnalise.checked) { if (modeles.length) rapport(); else {cases.forEach(function(c) {c.checked=false;}); compteur();} }
    });
    recherche.addEventListener("input", function () {
      var texte = recherche.value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(), n = 0;
      zone.querySelectorAll("[data-vignette-graphe]").forEach(function (row) {
        row.hidden = !row.textContent.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().includes(texte);
        if (!row.hidden) n++;
      }); zone.querySelector("[data-graphes-vides]").hidden = n > 0;
    });
    form.querySelectorAll('input[name="intention"]').forEach(function (r) {r.addEventListener("change", rapport);});
    // Les cases précochées montrent le contenu du modèle ; seuls les choix personnalisés sont envoyés.
    form.addEventListener("formdata", function (e) {
      if (!personnalise.checked && modeles.length) e.formData.delete("graphes");
    });
    if (modeles.length && !personnalise.checked) rapport(); else compteur();
  }

  function constructeur(form) {
    var dates = form.querySelector("#dates-precises");
    var surMesure = form.querySelector("#sur-mesure");
    var radioSurMesure = form.querySelector('input[name="intention"][value=""]');
    var kpis = form.querySelectorAll('input[name="kpis"]');

    function majDates() {
      var choisie = form.querySelector('input[name="periode"]:checked');
      var precises = choisie && choisie.value === "dates";
      dates.hidden = !precises;
      dates.querySelectorAll("input").forEach(function (i) { i.disabled = !precises; i.required = precises; });
    }
    form.querySelectorAll('input[name="periode"]').forEach(function (r) { r.addEventListener("change", majDates); });
    majDates();

    form.querySelectorAll('input[name="intention"]').forEach(function (r) {
      r.addEventListener("change", function () { if (r.value === "" && r.checked) surMesure.open = true; });
    });
    kpis.forEach(function (c) {
      c.addEventListener("change", function () { if (c.checked) {
        radioSurMesure.checked = true;
        var personnalise = form.querySelector('input[name="graphiques_personnalises"]');
        if (personnalise) personnalise.checked = true;
      } });
    });

    form.addEventListener("submit", function (e) {
      var intention = form.querySelector('input[name="intention"]:checked');
      var surMesureChoisi = !intention || intention.value === "";
      if (surMesureChoisi && !form.querySelector('input[name="graphes"]:checked') && !Array.prototype.some.call(kpis, function (c) { return c.checked; })) {
        e.preventDefault();
        surMesure.open = true;
        surMesure.scrollIntoView({ block: "center", behavior: "smooth" });
        if (kpis.length) kpis[0].focus({ preventScroll: true });
        return;
      }
      // Rapport type choisi : les cases « sur mesure » ne sont pas transmises.
      if (!surMesureChoisi) kpis.forEach(function (c) { c.disabled = true; });
      if (surMesureChoisi && intention) intention.disabled = true;
      var periode = form.querySelector('input[name="periode"]:checked');
      if (periode && periode.value === "dates") periode.disabled = true;
      form.querySelectorAll("select").forEach(function (s) { if (!s.value) s.disabled = true; });
      // Retour arrière du navigateur : formulaire de nouveau utilisable.
      setTimeout(function () {
        form.querySelectorAll("input, select").forEach(function (x) { x.disabled = false; });
        majDates();
      }, 0);
    });

    donnees(form);
    comboLieu(form);
  }

  /* Données journalières ou horaires. Tant qu'on n'a pas choisi, la case suit la règle du serveur
     (horaires pour un ou deux jours, un point par heure ou une plage horaire) et n'est pas envoyée.
     Un point par heure ou une plage horaire demandent les données horaires ; revenir aux
     journalières remet ces deux options à « automatique ». */
  function donnees(form) {
    var radios = form.querySelectorAll('input[name="donnees"]');
    var temps = form.querySelector("#o-temps"), heures = form.querySelector("#o-heures");
    if (!radios.length || !temps || !heures) return;
    var choisi = false;
    function cocher(valeur) { radios.forEach(function (r) { r.checked = r.value === valeur; }); }
    function horaireNecessaire() { return temps.value === "heure" || heures.value !== ""; }
    function suivre() {
      if (choisi && !horaireNecessaire()) return;
      var horaire = horaireNecessaire();
      var periode = form.querySelector('input[name="periode"]:checked');
      if (!horaire && periode && periode.value === "hier") horaire = true;
      if (!horaire && periode && periode.value === "dates") {
        var debut = form.querySelector("#debut").valueAsNumber, fin = form.querySelector("#fin").valueAsNumber;
        horaire = !isNaN(debut) && !isNaN(fin) && Math.abs(fin - debut) / 864e5 < 2;
      }
      cocher(horaire ? "heure" : "jour");
    }
    radios.forEach(function (r) {
      r.addEventListener("change", function () {
        choisi = true;
        if (r.value === "jour") {
          if (temps.value === "heure") temps.value = "";
          heures.value = "";
        }
      });
    });
    form.querySelectorAll('input[name="periode"], #debut, #fin, #o-temps, #o-heures').forEach(function (x) {
      x.addEventListener("change", suivre);
    });
    form.addEventListener("submit", function (e) {
      if (!choisi && !e.defaultPrevented) radios.forEach(function (r) { r.disabled = true; });
    });
    suivre();
  }

  /* Lieu : liste sous le champ (régions, communes, événements, puis sites trouvés au fil de la
     saisie). Le texte reste libre : plusieurs lieux séparés par « , » ou « et », la proposition
     choisie remplace le dernier. Sans JavaScript, la datalist d'origine sert de repli. */
  function comboLieu(form) {
    var champ = form.querySelector("#lieu"), source = document.getElementById("lieux-accueil");
    if (!champ || !source) return;
    var base = Array.prototype.map.call(source.options, function (o) {
      return { valeur: o.value, type: o.textContent.trim(), detail: "" };
    });
    var sites = [], visibles = [], actif = -1, attente, derniere = "";
    var liste = document.createElement("ul");
    liste.id = "lieu-propositions";
    liste.className = "combo-liste";
    liste.setAttribute("role", "listbox");
    liste.setAttribute("aria-label", "Lieux proposés");
    liste.hidden = true;
    champ.parentNode.appendChild(liste);
    // Clic sur une proposition ou sur la barre de défilement : le champ garde le focus.
    liste.addEventListener("mousedown", function (e) { e.preventDefault(); });
    champ.removeAttribute("list");
    champ.setAttribute("role", "combobox");
    champ.setAttribute("aria-autocomplete", "list");
    champ.setAttribute("aria-controls", liste.id);
    champ.setAttribute("aria-expanded", "false");

    function normaliser(t) { return t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
    function decouper() {  // [lieux déjà saisis + séparateur, lieu en cours]
      var m = champ.value.match(/^(.*(?:,\s*|\s+et\s+))?(.*)$/i);
      return [m[1] || "", m[2]];
    }
    function rang(item, q) {
      if (!q) return 0;
      var n = normaliser(item.valeur + " " + item.detail);
      if (n.indexOf(q) === 0) return 1;
      if (n.indexOf(" " + q) >= 0 || n.indexOf("(" + q) >= 0) return 2;
      return n.indexOf(q) >= 0 ? 3 : -1;
    }
    function texteAvecMarque(parent, texte, q) {
      var i = q ? normaliser(texte).indexOf(q) : -1;
      if (i < 0) { parent.appendChild(document.createTextNode(texte)); return; }
      var mark = document.createElement("mark");
      mark.textContent = texte.slice(i, i + q.length);
      parent.append(texte.slice(0, i), mark, texte.slice(i + q.length));
    }
    function fermer() {
      liste.hidden = true;
      actif = -1;
      champ.setAttribute("aria-expanded", "false");
      champ.removeAttribute("aria-activedescendant");
    }
    function activer(i) {
      var items = liste.children;
      if (actif >= 0 && items[actif]) {
        items[actif].classList.remove("actif");
        items[actif].removeAttribute("aria-selected");
      }
      actif = i;
      if (i < 0) { champ.removeAttribute("aria-activedescendant"); return; }
      items[i].classList.add("actif");
      items[i].setAttribute("aria-selected", "true");
      champ.setAttribute("aria-activedescendant", items[i].id);
      items[i].scrollIntoView({ block: "nearest" });
    }
    function afficher() {
      var q = normaliser(decouper()[1].trim());
      visibles = base.concat(sites)
        .map(function (item, n) { return { item: item, rang: rang(item, q), n: n }; })
        .filter(function (x) { return x.rang >= 0; })
        .sort(function (a, b) { return a.rang - b.rang || a.n - b.n; })
        .map(function (x) { return x.item; });
      liste.textContent = "";
      actif = -1;
      if (!visibles.length) { fermer(); return; }
      visibles.forEach(function (item, i) {
        var li = document.createElement("li");
        li.id = "lieu-proposition-" + i;
        li.setAttribute("role", "option");
        var valeur = document.createElement("span");
        valeur.className = "valeur";
        texteAvecMarque(valeur, item.valeur, q);
        if (item.detail) {
          var detail = document.createElement("span");
          detail.className = "detail";
          detail.textContent = " " + item.detail;
          valeur.appendChild(detail);
        }
        var type = document.createElement("span");
        type.className = "type";
        type.textContent = item.type;
        li.append(valeur, type);
        li.addEventListener("click", function () { choisir(i); });
        liste.appendChild(li);
      });
      liste.hidden = false;
      liste.scrollTop = 0;
      champ.setAttribute("aria-expanded", "true");
    }
    function choisir(i) {
      champ.value = decouper()[0] + visibles[i].valeur;
      fermer();
      champ.focus();
    }
    function chercherSites() {
      clearTimeout(attente);
      var texte = decouper()[1].trim();
      if (!window.fetch || texte.length < 2 || texte === derniere) return;
      attente = setTimeout(function () {
        derniere = texte;
        fetch(form.dataset.suggestions + "?q=" + encodeURIComponent(texte), { headers: { "Accept": "application/json" } })
          .then(function (r) { return r.ok ? r.json() : { lieux: [] }; })
          .then(function (d) {
            sites = d.lieux.filter(function (l) { return l.type === "site"; }).map(function (l) {
              return { valeur: l.valeur, type: "Site", detail: l.libelle !== l.valeur ? l.libelle : "" };
            });
            if (document.activeElement === champ) afficher();
          })
          .catch(function () {});
      }, 200);
    }

    champ.addEventListener("focus", afficher);
    champ.addEventListener("click", function () { if (liste.hidden) afficher(); });
    champ.addEventListener("input", function () { afficher(); chercherSites(); });
    champ.addEventListener("blur", fermer);
    champ.addEventListener("keydown", function (e) {
      var ouvert = !liste.hidden;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!ouvert) { afficher(); if (liste.hidden) return; }
        var n = liste.children.length;
        activer(e.key === "ArrowDown" ? (actif + 1) % n : (actif <= 0 ? n - 1 : actif - 1));
      } else if (e.key === "Enter" && ouvert && actif >= 0) {
        e.preventDefault();  // choisit la proposition sans envoyer le formulaire
        choisir(actif);
      } else if (e.key === "Escape" && ouvert) {
        e.preventDefault();
        fermer();
      }
    });
  }

  function graphiquesDashboard() {
    if (!window.echarts) return;
    var dashboardData = document.getElementById("dashboard-data");
    if (dashboardData) {
      var metrics = JSON.parse(dashboardData.textContent);
      document.querySelectorAll(".dashboard-chart").forEach(function (div) {
        var g = metrics[Number(div.dataset.index)], color = ["#347956", "#859cbd", "#ac9667", "#4b908c"][Number(div.dataset.index) % 4];
        initialiser(div, {
          animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
          aria: { enabled: true },
          tooltip: { trigger: "axis", valueFormatter: function (v) { return nombre(v, g.unite); } },
          grid: { top: 18, left: 8, right: 12, bottom: 10, containLabel: true },
          xAxis: { type: "category", data: g.periodes, boundaryGap: false, axisTick: { show: false }, axisLine: { show: false }, axisLabel: { color: "#86968a", fontSize: 10, hideOverlap: true } },
          yAxis: { type: "value", min: g.unite === "%" ? function (range) { return Math.max(0, Math.floor(range.min - Math.max(1, range.max - range.min) * .2)); } : 0, max: g.unite === "%" ? 100 : null, axisLabel: { color: "#86968a", fontSize: 10, formatter: function (v) { return nombre(v); } }, splitLine: { lineStyle: { color: "#edf2ed", type: "dashed" } } },
          series: [{ type: "line", data: g.valeurs, connectNulls: false, showSymbol: false, lineStyle: { color: color, width: 2.5 }, itemStyle: { color: color }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: color + "32" }, { offset: 1, color: color + "02" }]) } }]
        }, g.periodes_cles, g.titre);
      });
    }
  }

  function chargerDashboard() {
    var zone = document.getElementById("dashboard-charge");
    if (!zone) return;
    var message = zone.querySelector('[role="status"]');
    var bouton = zone.querySelector("[data-reessayer]");
    var enCours = false;
    function charger() {
      if (enCours) return;
      enCours = true;
      zone.setAttribute("aria-busy", "true");
      bouton.hidden = true;
      message.textContent = "Chargement des indicateurs… Vous pouvez continuer à naviguer.";
      var controle = new AbortController();
      var delai = setTimeout(function () { controle.abort(); }, 90000);
      fetch(zone.dataset.url, { signal: controle.signal, credentials: "same-origin",
        headers: { "Accept": "application/json" } })
        .then(function (r) {
          if (!r.ok || r.redirected) throw new Error("Indicateurs indisponibles");
          return r.json();
        })
        .then(function (donnees) {
          if (typeof donnees.html !== "string") throw new Error("Réponse invalide");
          zone.innerHTML = donnees.html;
          document.querySelectorAll(".quick-reports a").forEach(function (lien) {
            var url = new URL(lien.href);
            url.searchParams.set("debut", donnees.debut);
            url.searchParams.set("fin", donnees.fin);
            lien.href = url.href;
          });
          graphiquesDashboard();
        })
        .catch(function () {
          message.textContent = "Le chargement des indicateurs n’a pas abouti. Réessayez dans un instant ; les autres pages restent accessibles.";
          bouton.hidden = false;
        })
        .finally(function () {
          clearTimeout(delai);
          enCours = false;
          zone.setAttribute("aria-busy", "false");
        });
    }
    bouton.addEventListener("click", charger);
    charger();
  }

  function demarrer() {
    document.documentElement.classList.add("js");
    document.querySelectorAll("[data-choix-graphiques]").forEach(choisirGraphiques);
    var form = document.getElementById("constructeur");
    if (form) constructeur(form);
    chargerDashboard();
    if (window.echarts) {
      graphiquesDashboard();
      document.querySelectorAll(".graphiques[data-source]:not(.courbes)").forEach(courbes);
      document.querySelectorAll(".graphique-causes[data-source]").forEach(causes);
      document.querySelectorAll("[data-graphes-themes]").forEach(graphesThemes);
      document.querySelectorAll(".courbes[data-source]").forEach(courbesEvenement);
      var attente;
      window.addEventListener("resize", function () {
        clearTimeout(attente);
        attente = setTimeout(function () {
          graphiques.forEach(function (g) { g.resize(); });
          if (vuePopup) vuePopup.g.resize();
        }, 120);
      });
    }
    var tableaux = document.querySelectorAll(".tableau-detaille");
    tableaux.forEach(tableauDetaille);
    window.addEventListener("resize", function () { tableaux.forEach(limiterHauteur); });
    document.querySelectorAll("[data-visualisation]").forEach(basculeVisualisation);

    // Puces : une seule ouverte à la fois ; Échap ou clic à l'extérieur pour fermer.
    var puces = document.querySelectorAll("details.puce");
    puces.forEach(function (d) {
      d.addEventListener("toggle", function () {
        if (!d.open) return;
        puces.forEach(function (autre) { if (autre !== d) autre.open = false; });
        var champ = d.querySelector(".panneau input:not([type=hidden]), .panneau select, .panneau button");
        if (champ) champ.focus({ preventScroll: true });
      });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      puces.forEach(function (d) { if (d.open) { d.open = false; d.querySelector("summary").focus(); } });
    });
    document.addEventListener("click", function (e) {
      puces.forEach(function (d) { if (d.open && !d.contains(e.target)) d.open = false; });
    });

    // Menus principaux : même comportement familier que les puces de filtre.
    var menus = document.querySelectorAll("details.menu-actions, details.filtres-resultat");
    menus.forEach(function (menu) {
      menu.addEventListener("toggle", function () {
        if (!menu.open) return;
        menus.forEach(function (autre) { if (autre !== menu) autre.open = false; });
      });
    });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") return;
      menus.forEach(function (menu) { if (menu.open) { menu.open = false; menu.querySelector("summary").focus(); } });
    });
    document.addEventListener("click", function (e) {
      menus.forEach(function (menu) { if (menu.open && !menu.contains(e.target)) menu.open = false; });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer);
  else demarrer();
})();
