"use strict";
(() => {
  const form = document.querySelector("form[data-periode]");
  if (!form) return;
  const mode = form.querySelector("[data-comparaison]");
  const personnalisee = form.querySelector("[data-reference-personnalisee]");
  const afficher = () => {
    personnalisee.hidden = mode.value !== "personnalisee";
    personnalisee.querySelectorAll("input, select, button").forEach(c => { c.disabled = personnalisee.hidden; });
  };
  mode.addEventListener("change", afficher);
  afficher();
  const lignes = form.querySelector("[data-reference-lignes]");
  form.querySelector("[data-reference-ajouter]").addEventListener("click", () => {
    const ligne = lignes.firstElementChild.cloneNode(true);
    ligne.querySelector("input").value = "";
    lignes.append(ligne);
    ligne.querySelector("input").focus();
  });
  lignes.addEventListener("click", e => {
    if (!e.target.closest("[data-reference-retirer]")) return;
    if (lignes.children.length > 1) e.target.closest("[data-reference-ligne]").remove();
    else lignes.querySelector("input").value = "";
  });
  // Un changement d'édition recharge ses propres créneaux, sans les dates de l'édition affichée.
  form.querySelector("[data-edition]").addEventListener("change", e => {
    const params = new URLSearchParams({edition_id: e.target.value, niveau: form.elements.niveau.value});
    window.location.assign(`${window.location.pathname}?${params}`);
  });
})();
