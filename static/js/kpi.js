/* Stats réseau : graphiques ECharts (servi localement), thème clair / sombre, tiroir « Composer
   un rapport », aperçu du réseau de l'accueil et confort des puces. Les pages fonctionnent sans
   JavaScript (formulaires GET) ; ce script n'ajoute que l'affichage graphique et le confort. */
(function () {
  "use strict";

  var graphiques = [];  // { div, construire } : reconstruits au changement de thème

  /* ---------------------------------------------------------------- thème */
  function couleurs() {
    var s = getComputedStyle(document.documentElement);
    var v = function (n) { return s.getPropertyValue(n).trim(); };
    return { texte: v("--texte"), texte2: v("--texte-2"), texte3: v("--texte-3"), bord: v("--bord"), bordFort: v("--bord-fort"),
             surface: v("--surface"), surface3: v("--surface-3"), primaire: v("--primaire"), accent: v("--accent"),
             critique: v("--critique-vif"), alerte: v("--alerte-vif"), sombre: document.documentElement.dataset.theme === "dark" };
  }
  function palette(c) {
    return [c.primaire, c.accent, "#12b76a", "#8b5cf6", "#ef4444", "#06b6d4", "#ec4899", "#84cc16", "#0ea5e9", "#a16207",
            "#64748b", "#d946ef"];
  }
  function infobulle(c, extra) {
    return Object.assign({ backgroundColor: c.surface, borderColor: c.bord, borderWidth: 1, padding: [8, 12],
                           textStyle: { color: c.texte, fontSize: 12, fontFamily: "Inter, system-ui, sans-serif" },
                           extraCssText: "border-radius:10px;box-shadow:0 12px 32px -8px rgba(16,24,40,.25);" }, extra || {});
  }
  function axeX(c, donnees, extra) {
    return Object.assign({ type: "category", data: donnees, axisLabel: { color: c.texte3, fontSize: 11 },
                           axisLine: { lineStyle: { color: c.bord } }, axisTick: { show: false } }, extra || {});
  }

  function basculerTheme() {
    var d = document.documentElement;
    d.dataset.theme = d.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("theme", d.dataset.theme); } catch (e) {}
    redessiner();
  }

  function redessiner() {
    graphiques = graphiques.filter(function (g) { return document.body.contains(g.div); });
    graphiques.forEach(function (g) {
      var ancien = echarts.getInstanceByDom(g.div);
      if (ancien) ancien.dispose();
      g.construire(g.div, couleurs());
    });
  }

  function graphique(div, construire) {
    if (!window.echarts) return;
    graphiques.push({ div: div, construire: construire });
    construire(div, couleurs());
  }
  function dessiner(div, option) {
    var g = echarts.init(div, null, { renderer: "canvas" });
    g.setOption(Object.assign({ textStyle: { fontFamily: "Inter, system-ui, sans-serif" }, animationDuration: 500 }, option));
    return g;
  }

  /* ---------------------------------------------------------------- formats */
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

  function axeY(c, bornes) {
    return Object.assign({ type: "value", axisLabel: { color: c.texte3, fontSize: 11, formatter: graduation },
                           splitLine: { lineStyle: { color: c.bord, type: [4, 4] } } }, bornes);
  }

  function degrade(couleur, haut, bas) {
    return new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: couleur + haut }, { offset: 1, color: couleur + bas }]);
  }
  function hexa(couleur) {  // « #3b5bdb » ou « rgb(…) » -> « #rrggbb » (dégradés avec opacité)
    if (couleur.charAt(0) === "#" && couleur.length === 7) return couleur;
    var m = couleur.match(/\d+/g);
    return m ? "#" + m.slice(0, 3).map(function (x) { return ("0" + (+x).toString(16)).slice(-2); }).join("") : "#3b5bdb";
  }

  /* ---------------------------------------------------------------- résultat d'une recherche */
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
      graphique(cibles[n], function (div, c) {
        var bornes = bornesAxe(g);
        var visibles = seuilsVisibles(g.seuils, bornes);
        var seuils = [];
        if (visibles.alerte !== null) seuils.push({ yAxis: visibles.alerte, name: "alerte", lineStyle: { color: c.alerte, type: "dashed", width: 1.5 } });
        if (visibles.critique !== null) seuils.push({ yAxis: visibles.critique, name: "critique", lineStyle: { color: c.critique, type: "dashed", width: 1.5 } });
        var legende = sousTitreSeuils(visibles);
        var plusieurs = g.series.length > 1;
        var series = g.series.map(function (s, i) {
          var serie = { name: s.nom, type: "line", data: s.valeurs, connectNulls: false, smooth: 0.25,
                        showSymbol: s.valeurs.length < 40, symbolSize: 5, lineStyle: { width: plusieurs ? 1.8 : 2.4 },
                        emphasis: { focus: "series" } };
          if (!plusieurs) serie.areaStyle = { color: degrade(hexa(c.primaire), "33", "00") };
          if (i === 0 && seuils.length) serie.markLine = { symbol: "none", silent: true, label: { show: false }, data: seuils };
          return serie;
        });
        dessiner(div, {
          color: palette(c),
          title: { text: g.titre + " (" + g.unite + ")", left: 4, top: 2, itemGap: 6,
                   textStyle: { fontSize: 13, color: c.texte, fontWeight: 600 },
                   subtext: legende, subtextStyle: { fontSize: 11, color: c.texte3,
                     rich: { a: { color: c.alerte, fontWeight: 700 }, c: { color: c.critique, fontWeight: 700 } } } },
          tooltip: infobulle(c, { trigger: "axis", valueFormatter: function (v) { return nombre(v, g.unite); } }),
          legend: plusieurs ? { type: "scroll", bottom: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 11, color: c.texte2 } } : { show: false },
          grid: { left: 8, right: 16, top: legende ? 60 : 40, bottom: plusieurs ? 40 : 12, containLabel: true },
          xAxis: axeX(c, donnees.periodes, { boundaryGap: false }),
          yAxis: axeY(c, bornes),
          series: series
        });
      });
    });
  }

  function causes(div) {
    var g = JSON.parse(document.getElementById(div.dataset.source).textContent);
    var noms = g.series.map(function (s) { return s.nom; });
    graphique(div, function (div, c) {
      // Légende complète sur plusieurs lignes (pas de pagination) : hauteur adaptée.
      var largeur = Math.max(div.clientWidth || 600, 200);
      var occupe = noms.reduce(function (t, n) { return t + n.length * 6.3 + 38; }, 0);
      var lignes = Math.max(1, Math.ceil(occupe / (largeur - 24)));
      div.style.height = (300 + 22 * (lignes - 1)) + "px";
      var p = palette(c);
      dessiner(div, {
        color: p.slice(0, noms.length - 1).concat(noms[noms.length - 1] === "Non ventilé" ? [c.bordFort] : [p[noms.length - 1]]),
        title: { text: "Par " + g.par + " (" + g.unite + ")", left: 4, top: 2, textStyle: { fontSize: 13, color: c.texte, fontWeight: 600 } },
        tooltip: infobulle(c, { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: function (v) { return nombre(v, g.unite); } }),
        legend: { type: "plain", bottom: 0, left: "center", width: largeur - 24, itemGap: 12, icon: "roundRect", itemWidth: 10, itemHeight: 10,
                  textStyle: { fontSize: 11, color: c.texte2 } },
        grid: { left: 8, right: 16, top: 40, bottom: 18 + 22 * lignes, containLabel: true },
        xAxis: axeX(c, g.axe),
        yAxis: axeY(c, {}),
        series: g.series.map(function (s, i) {
          return { name: s.nom, type: "bar", stack: "causes", data: s.valeurs, barMaxWidth: 36, emphasis: { focus: "series" },
                   itemStyle: i === g.series.length - 1 ? { borderRadius: [4, 4, 0, 0] } : {} };
        })
      });
    });
  }

  /* ---------------------------------------------------------------- événement : événement / référence */
  function courbesEvenement(zone) {
    var donnees = JSON.parse(document.getElementById(zone.dataset.source).textContent);
    donnees.kpis.forEach(function (g) {
      var carte = document.createElement("figure");
      carte.className = "carte-graphique";
      carte.style.margin = "0";
      var div = document.createElement("div");
      div.className = "graphique";
      div.setAttribute("role", "img");
      div.setAttribute("aria-label", g.titre + " : événement et référence");
      carte.appendChild(div);
      zone.appendChild(carte);
      var ecart = g.max.map(function (v, i) { return v === null || g.min[i] === null ? null : v - g.min[i]; });
      graphique(div, function (div, c) {
        dessiner(div, {
          title: { text: g.titre, left: 4, top: 2, textStyle: { fontSize: 13, color: c.texte, fontWeight: 600 } },
          tooltip: infobulle(c, { trigger: "axis", formatter: function (p) {
            var lignes = [p[0].axisValue], i = p[0].dataIndex;
            lignes.push("Événement : " + nombre(g.evenement[i], g.unite));
            lignes.push("Référence : " + nombre(g.reference[i], g.unite));
            if (g.min[i] !== null) lignes.push("Réf. min – max : " + nombre(g.min[i]) + " – " + nombre(g.max[i]));
            return lignes.join("<br>");
          } }),
          legend: { bottom: 0, data: ["Événement", "Référence"], icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { color: c.texte2, fontSize: 11 } },
          grid: { left: 8, right: 16, top: 40, bottom: 40, containLabel: true },
          xAxis: axeX(c, donnees.instants),
          yAxis: Object.assign(axeY(c, {}), { scale: true,
                   max: g.unite === "%" ? function (v) { return Math.min(100, Math.ceil(v.max)); } : null }),
          series: [
            { name: "min", type: "line", data: g.min, stack: "bande", symbol: "none", lineStyle: { opacity: 0 }, silent: true },
            { name: "bande", type: "line", data: ecart, stack: "bande", symbol: "none", lineStyle: { opacity: 0 },
              areaStyle: { color: c.sombre ? "rgba(143,154,176,.18)" : "rgba(102,112,133,.14)" }, silent: true },
            { name: "Référence", type: "line", data: g.reference, color: c.accent, lineStyle: { type: "dashed", width: 2 }, symbol: "none" },
            { name: "Événement", type: "line", data: g.evenement, color: c.primaire, lineStyle: { width: 3 }, symbolSize: 5 }
          ]
        });
      });
    });
  }

  /* ---------------------------------------------------------------- accueil : aperçu du réseau */
  var APERCU = {
    trafic: function (div, d, c) {
      var t = d.trafic;
      dessiner(div, {
        tooltip: infobulle(c, { trigger: "axis", valueFormatter: function (v) { return nombre(v, t.unite); } }),
        grid: { left: 4, right: 12, top: 12, bottom: 4, containLabel: true },
        xAxis: axeX(c, d.heures, { boundaryGap: false }),
        yAxis: axeY(c, {}),
        series: [
          { name: d.veille, type: "line", data: t.veille, smooth: 0.35, symbol: "none", lineStyle: { width: 2, type: [6, 4], color: c.bordFort },
            itemStyle: { color: c.bordFort } },
          { name: d.jour, type: "line", data: t.jour, smooth: 0.35, symbol: "circle", symbolSize: 6, showSymbol: false,
            lineStyle: { width: 3, color: c.primaire }, itemStyle: { color: c.primaire },
            areaStyle: { color: degrade(hexa(c.primaire), "40", "00") } }
        ]
      });
    },
    tendance: function (div, d, c) {
      var t = d.tendance;
      dessiner(div, {
        tooltip: infobulle(c, { trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: function (v) { return nombre(v, t.unite); } }),
        grid: { left: 4, right: 4, top: 10, bottom: 4, containLabel: true },
        xAxis: axeX(c, t.jours, { axisLabel: { color: c.texte3, fontSize: 10, interval: 2 } }),
        yAxis: axeY(c, { splitNumber: 3 }),
        series: [{ name: "Volume", type: "bar", barMaxWidth: 18, data: t.valeurs.map(function (v, i) {
          var cible = t.jours[i] === t.cible;
          return { value: v, itemStyle: { color: cible ? c.primaire : (c.sombre ? "rgba(76,110,245,.35)" : "rgba(59,91,219,.22)"),
                                          borderRadius: [5, 5, 0, 0] } };
        }) }]
      });
    },
    qualite: function (div, d, c) {
      var q = d.qualite;
      var couleursTechno = { LTE: c.primaire, WCDMA: c.accent };
      dessiner(div, {
        tooltip: infobulle(c, { trigger: "axis", valueFormatter: function (v) { return nombre(v, "%"); } }),
        legend: { bottom: 0, icon: "roundRect", itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 10, color: c.texte2 } },
        grid: { left: 4, right: 8, top: 10, bottom: 30, containLabel: true },
        xAxis: axeX(c, d.heures, { boundaryGap: false, axisLabel: { color: c.texte3, fontSize: 10, interval: 5 } }),
        yAxis: axeY(c, { min: 0, splitNumber: 3 }),
        series: q.series.map(function (s, i) {
          var serie = { name: s.nom, type: "line", data: s.valeurs, smooth: 0.3, symbol: "none",
                        lineStyle: { width: 2.2, color: couleursTechno[s.techno] }, itemStyle: { color: couleursTechno[s.techno] } };
          if (i === 0 && q.seuil !== null) {
            serie.markLine = { symbol: "none", silent: true, label: { show: false },
                               data: [{ yAxis: q.seuil, lineStyle: { color: c.alerte, type: "dashed", width: 1.2 } }] };
          }
          return serie;
        })
      });
    }
  };

  function apercu(zone) {
    var boutons = document.querySelectorAll(".segments [data-jour]");
    var sousTitre = document.getElementById("apercu-sous-titre");
    var requete = 0;

    function charger(jour) {
      var numero = ++requete;
      boutons.forEach(function (b) { b.setAttribute("aria-pressed", b.dataset.jour === jour ? "true" : "false"); });
      zone.setAttribute("aria-busy", "true");
      zone.style.opacity = zone.children.length && !zone.querySelector(".squelettes") ? ".55" : "";
      fetch(zone.dataset.url + "?jour=" + encodeURIComponent(jour), { headers: { "Accept": "text/html" }, credentials: "same-origin" })
        .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
        .then(function (html) {
          if (numero !== requete) return;
          zone.innerHTML = html;
          zone.style.opacity = "";
          zone.setAttribute("aria-busy", "false");
          var contenu = zone.querySelector("[data-sous-titre]");
          if (contenu && sousTitre) sousTitre.textContent = contenu.dataset.sousTitre;
          var source = document.getElementById("donnees-apercu");
          if (source) {
            var donnees = JSON.parse(source.textContent);
            zone.querySelectorAll("[data-apercu]").forEach(function (div) {
              var construire = APERCU[div.dataset.apercu];
              if (construire && donnees[div.dataset.apercu]) graphique(div, function (el, c) { construire(el, donnees, c); });
            });
          }
          zone.querySelectorAll("[data-jour]").forEach(function (b) { b.addEventListener("click", function () { charger(b.dataset.jour); }); });
          try { sessionStorage.setItem("apercu", jour); } catch (e) {}
        })
        .catch(function () {
          if (numero !== requete) return;
          zone.style.opacity = "";
          zone.setAttribute("aria-busy", "false");
          zone.innerHTML = '<div class="carte vide-etat"><p>L’aperçu n’a pas pu être chargé.</p>' +
                           '<button class="bouton secondaire petit" type="button">Réessayer</button></div>';
          zone.querySelector("button").addEventListener("click", function () { charger(jour); });
        });
    }
    boutons.forEach(function (b) { b.addEventListener("click", function () { charger(b.dataset.jour); }); });
    var jour = "hier";
    try { jour = sessionStorage.getItem("apercu") || "hier"; } catch (e) {}
    charger(jour === "aujourdhui" ? "aujourdhui" : "hier");
  }

  /* ---------------------------------------------------------------- compositeur de rapport */
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

  /* Le compositeur (section en bas de l'accueil sans JavaScript) devient un tiroir latéral. */
  function tiroir(section) {
    if (!window.HTMLDialogElement) return null;
    var dialogue = document.createElement("dialog");
    dialogue.className = "tiroir";
    dialogue.setAttribute("aria-labelledby", "titre-composer");
    var corps = document.createElement("div");
    corps.className = "tiroir-corps";
    var tete = section.querySelector(".tiroir-tete");
    section.parentNode.insertBefore(dialogue, section);
    dialogue.appendChild(tete);
    corps.appendChild(section);
    dialogue.appendChild(corps);
    section.removeAttribute("id");
    dialogue.id = "composer";
    dialogue.addEventListener("click", function (e) { if (e.target === dialogue) dialogue.close(); });
    dialogue.querySelectorAll("[data-ferme-composer]").forEach(function (b) {
      b.addEventListener("click", function () { dialogue.close(); });
    });
    dialogue.addEventListener("close", function () {
      if (location.hash === "#composer") history.replaceState(null, "", location.pathname + location.search);
    });
    return dialogue;
  }

  /* ---------------------------------------------------------------- démarrage */
  function demarrer() {
    document.documentElement.classList.add("js");
    document.querySelectorAll("[data-bascule-theme]").forEach(function (b) { b.addEventListener("click", basculerTheme); });

    var form = document.getElementById("constructeur");
    if (form) constructeur(form);
    var section = document.querySelector("section.composer-section");
    var dialogue = section ? tiroir(section) : null;
    if (dialogue) {
      var ouvrir = function () {
        if (!dialogue.open) dialogue.showModal();
        var coche = dialogue.querySelector('input[name="intention"]:checked');
        if (coche) coche.focus({ preventScroll: true });
      };
      document.querySelectorAll("[data-ouvre-composer]").forEach(function (a) {
        a.addEventListener("click", function (e) { e.preventDefault(); ouvrir(); });
      });
      if (location.hash === "#composer") ouvrir();
    } else if (section) {  // navigateur sans <dialog> : section affichée en bas de page
      section.style.display = "block";
      document.querySelectorAll("[data-ferme-composer]").forEach(function (b) { b.hidden = true; });
    }

    var zoneApercu = document.getElementById("apercu");
    if (zoneApercu && window.fetch) apercu(zoneApercu);

    if (window.echarts) {
      document.querySelectorAll(".graphiques[data-source]:not([data-courbes-evenement])").forEach(courbes);
      document.querySelectorAll(".graphique-causes[data-source]").forEach(causes);
      document.querySelectorAll("[data-courbes-evenement]").forEach(courbesEvenement);
      var attente;
      window.addEventListener("resize", function () {
        clearTimeout(attente);
        attente = setTimeout(function () {
          graphiques.forEach(function (g) { var i = echarts.getInstanceByDom(g.div); if (i) i.resize(); });
        }, 120);
      });
    }

    // Ombre de la barre du haut dès que la page défile.
    var barre = document.querySelector(".barre-haut");
    if (barre) {
      var majBarre = function () { barre.classList.toggle("defile", window.scrollY > 4); };
      window.addEventListener("scroll", majBarre, { passive: true });
      majBarre();
    }

    // Puces et menu d'export : un seul ouvert à la fois ; Échap ou clic à l'extérieur pour fermer.
    var puces = document.querySelectorAll("details.puce, details.menu-export");
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
