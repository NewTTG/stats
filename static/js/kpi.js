/* Écran de recherche KPI : graphiques ECharts (servi localement) et confort des puces.
   La page fonctionne sans JavaScript (formulaires GET) ; ce script n'ajoute que l'affichage graphique. */
(function () {
  "use strict";

  var MARINE = "#14284b", AMBRE = "#f0a500", ROUGE = "#c0392b";
  var PALETTE = ["#14284b", "#f0a500", "#0f766e", "#7c3aed", "#c2410c", "#2563eb", "#be185d", "#4d7c0f",
                 "#0891b2", "#92400e", "#64748b", "#a21caf"];
  var graphiques = [];

  function nombre(v, unite) {
    if (v === null || v === undefined || isNaN(v)) return "—";
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

  function initialiser(div, option) {
    var g = echarts.init(div, null, { renderer: "canvas" });
    g.setOption(option);
    graphiques.push(g);
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
        if (!plusieurs) serie.areaStyle = { color: "rgba(20,40,75,.06)" };
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
      });
    });
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
    });
  }

  /* Accueil : rapport type + lieu + période. Sans JavaScript, le formulaire fonctionne tel quel ;
     ici : dates précises affichées à la demande, « Sur mesure » ouvert quand on le choisit,
     lieux (sites) suggérés au fil de la saisie, et URL sans paramètres vides. */
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
      c.addEventListener("change", function () { if (c.checked) radioSurMesure.checked = true; });
    });

    form.addEventListener("submit", function (e) {
      var intention = form.querySelector('input[name="intention"]:checked');
      var surMesureChoisi = !intention || intention.value === "";
      if (surMesureChoisi && !Array.prototype.some.call(kpis, function (c) { return c.checked; })) {
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

    // Sites proposés au fil de la saisie (communes, régions et événements sont déjà dans la liste).
    var champ = form.querySelector("#lieu"), liste = document.getElementById("lieux-accueil");
    if (!champ || !liste || !window.fetch) return;
    var base = liste.innerHTML, attente, derniere = "";
    champ.addEventListener("input", function () {
      clearTimeout(attente);
      var texte = champ.value.split(/,| et /).pop().trim();
      if (texte.length < 2 || texte === derniere) return;
      attente = setTimeout(function () {
        derniere = texte;
        fetch(form.dataset.suggestions + "?q=" + encodeURIComponent(texte), { headers: { "Accept": "application/json" } })
          .then(function (r) { return r.ok ? r.json() : { lieux: [] }; })
          .then(function (d) {
            var options = d.lieux.filter(function (l) { return l.type === "site"; }).map(function (l) {
              var o = document.createElement("option");
              o.value = l.valeur;
              o.textContent = l.libelle;
              return o.outerHTML;
            });
            liste.innerHTML = base + options.join("");
          })
          .catch(function () {});
      }, 200);
    });
  }

  function demarrer() {
    document.documentElement.classList.add("js");
    var form = document.getElementById("constructeur");
    if (form) constructeur(form);
    if (window.echarts) {
      document.querySelectorAll(".graphiques[data-source]").forEach(courbes);
      document.querySelectorAll(".graphique-causes[data-source]").forEach(causes);
      var attente;
      window.addEventListener("resize", function () {
        clearTimeout(attente);
        attente = setTimeout(function () { graphiques.forEach(function (g) { g.resize(); }); }, 120);
      });
    }

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
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", demarrer);
  else demarrer();
})();
