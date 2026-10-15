/* Éditeurs de graphiques et rapports. Les formulaires restent utilisables sans JS. */
(function () {
  "use strict";
  function normaliser(s) { return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
  var detailsNode = document.getElementById("graphiques-details");
  var details = detailsNode ? JSON.parse(detailsNode.textContent) : {};
  ["id_graphes", "id_kpis"].forEach(function (id) {
    var liste = document.getElementById(id);
    if (!liste) return;
    liste.classList.add("composition-liste");
    var barre = document.createElement("div"); barre.className = "composition-recherche";
    var recherche = document.createElement("input"); recherche.type = "search";
    recherche.placeholder = id === "id_graphes" ? "Rechercher un graphique, 3G, 4G, un thème…" : "Rechercher un indicateur…";
    recherche.setAttribute("aria-label", recherche.placeholder);
    var compteur = document.createElement("span"); compteur.className = "composition-compteur"; compteur.setAttribute("role", "status");
    barre.append(recherche, compteur); liste.before(barre);
    function actualiser() {
      var selection = liste.querySelectorAll("input:checked").length;
      compteur.textContent = selection + (id === "id_graphes" ? " graphiques choisis" : " indicateurs choisis");
      Array.from(liste.children).forEach(function (row) {
        row.hidden = !normaliser(row.textContent).includes(normaliser(recherche.value));
        var commandes = row.querySelector(".composition-ordre");
        if (commandes) commandes.hidden = !row.querySelector("input").checked;
      });
    }
    Array.from(liste.children).forEach(function (row) {
      var input = row.querySelector("input"); if (!input) return;
      if (details[input.value]) {
        var info = document.createElement("small");
        info.textContent = details[input.value].theme + " · " + details[input.value].series + " séries";
        row.querySelector("label").append(info);
      }
      if (id === "id_graphes") {
        var actions = document.createElement("span"); actions.className = "composition-ordre";
        [-1, 1].forEach(function (sens) {
          var bouton = document.createElement("button"); bouton.type = "button"; bouton.textContent = sens < 0 ? "↑" : "↓";
          bouton.setAttribute("aria-label", (sens < 0 ? "Monter " : "Descendre ") + row.textContent.trim());
          bouton.addEventListener("click", function () {
            var selection = Array.from(liste.children).filter(function (r) { return r.querySelector("input:checked"); });
            var voisin = selection[selection.indexOf(row) + sens];
            if (voisin) { if (sens < 0) voisin.before(row); else voisin.after(row); bouton.focus(); }
          }); actions.append(bouton);
        }); row.append(actions);
      }
    });
    recherche.addEventListener("input", actualiser); liste.addEventListener("change", actualiser); actualiser();
  });

  var canvas = document.getElementById("apercu-graphique");
  if (!canvas || !window.echarts) return;
  var cat = JSON.parse(document.getElementById("indicateurs-apercu").textContent);
  var chart = echarts.init(canvas), message = document.getElementById("apercu-message");
  function apercu() {
    var lignes = Array.from(document.querySelectorAll('#series-group tr.form-row:not(.empty-form)')).filter(function (row) {
      var suppression = row.querySelector('input[name$="-DELETE"]'); return !suppression || !suppression.checked;
    });
    lignes.sort(function (a, b) { return Number(a.querySelector('[name$="-ordre"]').value) - Number(b.querySelector('[name$="-ordre"]').value); });
    var unites = [new Set(), new Set()], technos = new Set(), series = [];
    lignes.forEach(function (row, n) {
      var code = row.querySelector('[name$="-kpi"]').value, k = cat[code]; if (!k) return;
      var type = row.querySelector('[name$="-type"]').value;
      var axe = row.querySelector('[name$="-axe"]').value === "droite" ? 1 : 0;
      unites[axe].add(k.unite); technos.add(k.techno);
      series.push({name:k.nom, type:type.startsWith("barres") ? "bar" : "line", yAxisIndex:axe,
        stack:type === "barres_empilees" ? "pile-" + axe : undefined,
        areaStyle:type === "aire" ? {opacity:0.25} : undefined,
        data:[35,46,42,61,53,70,64].map(function (v) {return k.unite === "%" ? Math.round(v / (n + 1)) : v * (n + 1);})});
    });
    message.textContent = technos.size > 1 ? "Choisissez une seule technologie par graphique." :
      unites.some(function (u) {return u.size > 1;}) ? "Séparez les unités : une unité par axe." :
      series.length ? "Aperçu fictif · " + series.length + " séries" : "Ajoutez un indicateur pour voir l’aperçu.";
    chart.setOption({animation:false, tooltip:{trigger:"axis",renderMode:"richText"},legend:{type:"scroll",bottom:0},
      grid:{left:65,right:65,top:45,bottom:65},xAxis:{type:"category",data:["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"]},
      yAxis:unites.map(function (u) {return {type:"value",name:Array.from(u).join(" / ")};}),series:series},true);
  }
  document.addEventListener("change", apercu);
  document.addEventListener("formset:added", apercu); document.addEventListener("formset:removed", apercu);
  window.addEventListener("resize", function () {chart.resize();}); apercu();
}());
