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
    var d = Math.abs(v) >= 100 ? 0 : (Math.abs(v) >= 10 ? 1 : 2);
    return v.toLocaleString("fr-FR", { maximumFractionDigits: d, minimumFractionDigits: 0 }) + (unite ? " " + unite : "");
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
    return Object.assign({ type: "value", axisLabel: { color: "#5f6878", fontSize: 11, formatter: function (v) { return nombre(v); } },
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
      var seuils = [];
      // Étiquettes aux deux extrémités (alerte à droite, critique à gauche) : jamais superposées.
      var etiquette = { formatter: "{b}", color: "#4b5567", fontSize: 11 };
      if (g.seuils.alerte !== null) seuils.push({ yAxis: g.seuils.alerte, name: "alerte", lineStyle: { color: AMBRE, type: "dashed", width: 1.5 },
                                                  label: Object.assign({ position: "insideEndTop" }, etiquette) });
      if (g.seuils.critique !== null) seuils.push({ yAxis: g.seuils.critique, name: "critique", lineStyle: { color: ROUGE, type: "dashed", width: 1.5 },
                                                    label: Object.assign({ position: "insideStartTop" }, etiquette) });
      var plusieurs = g.series.length > 1;
      var series = g.series.map(function (s, i) {
        var serie = { name: s.nom, type: "line", data: s.valeurs, connectNulls: false, smooth: false,
                      showSymbol: s.valeurs.length < 40, symbolSize: 5, lineStyle: { width: plusieurs ? 1.8 : 2.5 },
                      emphasis: { focus: "series" } };
        if (!plusieurs) serie.areaStyle = { color: "rgba(20,40,75,.06)" };
        if (i === 0 && seuils.length) serie.markLine = { symbol: "none", silent: true, label: etiquette, data: seuils };
        return serie;
      });
      initialiser(cibles[n], {
        color: PALETTE,
        title: { text: g.titre + " (" + g.unite + ")", left: 4, top: 2, textStyle: { fontSize: 13, color: MARINE, fontWeight: 600 } },
        tooltip: { trigger: "axis", valueFormatter: function (v) { return nombre(v, g.unite); } },
        legend: plusieurs ? { type: "scroll", bottom: 0, textStyle: { fontSize: 11 } } : { show: false },
        grid: { left: 8, right: 16, top: 40, bottom: plusieurs ? 40 : 12, containLabel: true },
        xAxis: { type: "category", data: donnees.periodes, boundaryGap: false, axisLabel: { color: "#5f6878", fontSize: 11 },
                 axisLine: { lineStyle: { color: "#c3ccda" } } },
        yAxis: axeY(bornesAxe(g)),
        series: series
      });
    });
  }

  function causes(div) {
    var g = JSON.parse(document.getElementById(div.dataset.source).textContent);
    var noms = g.series.map(function (s) { return s.nom; });
    initialiser(div, {
      color: PALETTE.slice(0, noms.length - 1).concat(noms[noms.length - 1] === "Non ventilé" ? ["#aab3c2"] : [PALETTE[noms.length - 1]]),
      title: { text: "Par " + g.par + " (" + g.unite + ")", left: 4, top: 2, textStyle: { fontSize: 13, color: MARINE, fontWeight: 600 } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: function (v) { return nombre(v, g.unite); } },
      legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: 8, right: 16, top: 40, bottom: 44, containLabel: true },
      xAxis: { type: "category", data: g.axe, axisLabel: { color: "#5f6878", fontSize: 11 } },
      yAxis: axeY({}),
      series: g.series.map(function (s) {
        return { name: s.nom, type: "bar", stack: "causes", data: s.valeurs, barMaxWidth: 36, emphasis: { focus: "series" } };
      })
    });
  }

  function demarrer() {
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
