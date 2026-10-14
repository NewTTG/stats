"use strict";
// Déclaration / modification d'un site (templates/referentiel/edition.html) : ajout de lignes aux formsets
// (secteurs, cellules) à partir de leur modèle <template>, retrait d'une ligne (case DELETE cochée, ligne masquée).

(() => {
  for (const bloc of document.querySelectorAll("[data-formset]")) {
    const prefixe = bloc.dataset.formset;
    const total = bloc.querySelector(`input[name="${prefixe}-TOTAL_FORMS"]`);
    const lignes = bloc.querySelector("[data-lignes]");
    const modele = bloc.querySelector("template[data-modele]");

    bloc.querySelector("[data-ajouter]").addEventListener("click", () => {
      const index = Number(total.value);
      const html = modele.innerHTML.replace(/__prefix__/g, String(index));
      lignes.insertAdjacentHTML("beforeend", html);
      total.value = String(index + 1);
      const ligne = lignes.lastElementChild;
      if (prefixe === "secteurs") {
        // Numéro suivant ceux déjà déclarés.
        const pris = [...lignes.querySelectorAll('tr:not([hidden]) input[name$="-numero"]')].map((c) => Number(c.value));
        const libre = [1, 2, 3, 4, 5, 6, 7, 8, 9].find((n) => !pris.includes(n));
        const numero = ligne.querySelector('input[name$="-numero"]');
        if (libre && numero) numero.value = String(libre);
      }
      ligne.querySelector("input:not([type=checkbox]), select")?.focus();
    });

    lignes.addEventListener("change", (event) => {
      const caseRetrait = event.target.closest('input[name$="-DELETE"]');
      if (caseRetrait?.checked) caseRetrait.closest("tr").hidden = true;
    });
  }
})();
