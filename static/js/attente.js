"use strict";
// Requête longue (analyse d'événement, grande période, gros périmètre) : si la page suivante n'est pas
// arrivée après 3 s, une barre de chargement et le temps écoulé indiquent que le calcul continue.
// Ne s'applique ni aux téléchargements (data-sans-attente, /telecharger/) ni aux liens externes.

(() => {
  const DELAI = 3000;
  let minuterie = null, horloge = null, debut = 0, panneau = null;

  function construire() {
    panneau = document.createElement("div");
    panneau.className = "attente";
    panneau.setAttribute("role", "status");
    panneau.setAttribute("aria-live", "polite");
    panneau.innerHTML = '<div class="attente-barre" aria-hidden="true"><span></span></div>'
      + '<div class="attente-boite"><strong>Calcul en cours… <span data-ecoule></span></strong>'
      + "<small>Les longues périodes et les grandes zones peuvent prendre plus d'une minute. "
      + "Gardez la page ouverte : le résultat s'affichera tout seul.</small></div>";
    document.body.append(panneau);
  }

  function majEcoule() {
    const s = Math.round((Date.now() - debut) / 1000);
    panneau.querySelector("[data-ecoule]").textContent = s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
  }

  function afficher() {
    if (!panneau) construire();
    majEcoule();
    panneau.hidden = false;
    horloge = setInterval(majEcoule, 1000);
  }

  function arreter() {
    clearTimeout(minuterie);
    clearInterval(horloge);
    if (panneau) panneau.hidden = true;
  }

  function demarrer() {
    arreter();
    debut = Date.now();
    minuterie = setTimeout(afficher, DELAI);
  }

  // Écoute sur window : les gestionnaires de la page (qui peuvent annuler l'envoi) passent avant.
  window.addEventListener("submit", (event) => {
    const form = event.target;
    if (event.defaultPrevented || "sansAttente" in form.dataset) return;
    if (form.target && form.target !== "_self") return;
    demarrer();
  });

  window.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const lien = event.target.closest("a[href]");
    if (!lien || "sansAttente" in lien.dataset || lien.hasAttribute("download")) return;
    if (lien.target && lien.target !== "_self") return;
    const url = new URL(lien.href, window.location.href);
    if (url.origin !== window.location.origin || url.pathname.includes("/telecharger/")) return;
    if (url.pathname === window.location.pathname && url.search === window.location.search) return;  // ancre
    demarrer();
  });

  // Retour arrière (cache du navigateur) : la page réaffichée ne doit pas garder la barre.
  window.addEventListener("pageshow", arreter);
})();
