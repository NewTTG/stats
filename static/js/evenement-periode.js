"use strict";
// Période analysée d'un événement (templates/evenements/detail.html), heures pleines :
// - jours consécutifs à la même plage horaire (du / au, de / à) ;
// - « Heures différentes selon les jours » : une ligne par jour, préremplie depuis la plage commune.
// Le mode masqué est un <fieldset disabled> : ses champs ne sont pas envoyés.

(() => {
  const formulaire = document.querySelector("form[data-periode]");
  if (!formulaire) return;
  const simple = formulaire.querySelector("[data-mode-simple]");
  const detail = formulaire.querySelector("[data-mode-detail]");
  const lignes = detail.querySelector("[data-lignes]");
  const bascule = formulaire.querySelector("[data-bascule-detail]");
  const modele = lignes.querySelector("[data-ligne]").cloneNode(true);

  const lireJour = (texte) => (texte ? new Date(`${texte}T00:00`) : null);
  const versJour = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const plusJours = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);

  function duree(de, a) {
    if (de === "" || a === "") return "";
    const h = ((Number(a) - Number(de)) % 24 + 24) % 24 || 24;
    return `${h} h${Number(a) <= Number(de) && Number(a) !== 24 ? " · finit le lendemain" : ""}`;
  }

  function majSimple() {
    const de = simple.querySelector("[data-de]").value, a = simple.querySelector("[data-a]").value;
    const du = lireJour(simple.querySelector("[data-du]").value), au = lireJour(simple.querySelector("[data-au]").value);
    const nb = du && au && au >= du ? Math.round((au - du) / 864e5) + 1 : du ? 1 : 0;
    const texte = duree(de, a);
    simple.querySelector("[data-duree]").textContent = texte && nb ? `${texte}${nb > 1 ? ` × ${nb} jours` : ""}` : texte;
  }

  function majLigne(ligne) {
    const [de, a] = [...ligne.querySelectorAll("select")].map((s) => s.value);
    ligne.querySelector("[data-duree]").textContent = duree(de, a);
  }

  function ajouterLigne(jour, de, a) {
    const ligne = modele.cloneNode(true);
    ligne.querySelector('input[type="date"]').value = jour || "";
    const [selDe, selA] = ligne.querySelectorAll("select");
    selDe.value = de ?? "";
    selA.value = a ?? "";
    lignes.append(ligne);
    majLigne(ligne);
    return ligne;
  }

  function versDetail() {
    // Une ligne par jour de la plage commune, aux mêmes heures : il ne reste qu'à ajuster.
    const du = lireJour(simple.querySelector("[data-du]").value);
    const au = lireJour(simple.querySelector("[data-au]").value) || du;
    const de = simple.querySelector("[data-de]").value, a = simple.querySelector("[data-a]").value;
    lignes.replaceChildren();
    if (du && au >= du) {
      for (let j = du; j <= au && lignes.children.length < 31; j = plusJours(j, 1)) ajouterLigne(versJour(j), de, a);
    }
    if (!lignes.children.length) ajouterLigne("", de, a);
  }

  function versSimple() {
    const remplies = [...lignes.querySelectorAll("[data-ligne]")].filter((l) => l.querySelector('input[type="date"]').value);
    if (!remplies.length) return;
    const jours = remplies.map((l) => l.querySelector('input[type="date"]').value).sort();
    const [de, a] = [...remplies[0].querySelectorAll("select")].map((s) => s.value);
    simple.querySelector("[data-du]").value = jours[0];
    simple.querySelector("[data-au]").value = jours.length > 1 ? jours[jours.length - 1] : "";
    simple.querySelector("[data-de]").value = de;
    simple.querySelector("[data-a]").value = a;
    majSimple();
  }

  function afficher(enDetail) {
    simple.hidden = simple.disabled = enDetail;
    detail.hidden = detail.disabled = !enDetail;
  }

  bascule.addEventListener("change", () => {
    if (bascule.checked) versDetail(); else versSimple();
    afficher(bascule.checked);
  });

  simple.addEventListener("change", (event) => {
    // Premier jour choisi sans dernier jour : un seul jour, rien à faire. Dernier jour avant le premier : corrigé.
    const du = simple.querySelector("[data-du]"), au = simple.querySelector("[data-au]");
    if (event.target === du && au.value && au.value < du.value) au.value = du.value;
    majSimple();
  });

  detail.addEventListener("change", (event) => {
    const ligne = event.target.closest("[data-ligne]");
    if (ligne) majLigne(ligne);
  });

  detail.addEventListener("click", (event) => {
    const bouton = event.target.closest("button");
    if (!bouton) return;
    if (bouton.matches("[data-retirer]")) {
      const ligne = bouton.closest("[data-ligne]");
      if (lignes.children.length > 1) ligne.remove();
      else { ligne.querySelector('input[type="date"]').value = ""; }
    } else if (bouton.matches("[data-ajouter]")) {
      // Jour suivant le dernier, aux mêmes heures.
      const derniere = lignes.lastElementChild;
      const jour = lireJour(derniere?.querySelector('input[type="date"]').value);
      const [de, a] = derniere ? [...derniere.querySelectorAll("select")].map((s) => s.value) : ["", ""];
      ajouterLigne(jour ? versJour(plusJours(jour, 1)) : "", de, a).querySelector("input").focus();
    }
  });

  majSimple();
  lignes.querySelectorAll("[data-ligne]").forEach(majLigne);
})();
