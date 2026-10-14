"use strict";
// Période analysée d'un événement (templates/evenements/detail.html) : lignes de créneaux à ajouter,
// retirer ou copier au lendemain, durée affichée, fin proposée 3 h après le début.

(() => {
  const formulaire = document.querySelector("form[data-periode]");
  if (!formulaire) return;
  const liste = formulaire.querySelector("[data-creneaux]");
  const HEURE = 3600 * 1000;
  const lignes = () => [...liste.querySelectorAll("[data-creneau]")];
  const champs = (ligne) => ligne.querySelectorAll('input[type="datetime-local"]');
  const lireDate = (input) => (input.value ? new Date(input.value) : null);
  const versChamp = (date) => {
    const p = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}T${p(date.getHours())}:${p(date.getMinutes())}`;
  };

  function majDuree(ligne) {
    const [debut, fin] = [...champs(ligne)].map(lireDate);
    const sortie = ligne.querySelector("[data-duree]");
    sortie.classList.remove("erreur");
    if (!debut || !fin) { sortie.textContent = ""; return; }
    const minutes = Math.round((fin - debut) / 60000);
    if (minutes <= 0) {
      sortie.textContent = "La fin doit suivre le début";
      sortie.classList.add("erreur");
      return;
    }
    const j = Math.floor(minutes / 1440), h = Math.floor((minutes % 1440) / 60), m = minutes % 60;
    sortie.textContent = [j && `${j} j`, h && `${h} h`, m && `${m} min`].filter(Boolean).join(" ");
  }

  function ajouter(debut, fin) {
    const ligne = lignes()[0].cloneNode(true);
    const [champDebut, champFin] = champs(ligne);
    champDebut.value = debut ? versChamp(debut) : "";
    champFin.value = fin ? versChamp(fin) : "";
    liste.append(ligne);
    majDuree(ligne);
    if (!debut) champDebut.focus();
  }

  liste.addEventListener("change", (event) => {
    const ligne = event.target.closest("[data-creneau]");
    if (!ligne) return;
    const [champDebut, champFin] = champs(ligne);
    if (event.target === champDebut && champDebut.value && !champFin.value) {
      champFin.value = versChamp(new Date(lireDate(champDebut).getTime() + 3 * HEURE));
    }
    majDuree(ligne);
  });

  liste.addEventListener("click", (event) => {
    const bouton = event.target.closest("button");
    const ligne = bouton?.closest("[data-creneau]");
    if (!ligne) return;
    if (bouton.matches("[data-retirer]")) {
      if (lignes().length > 1) ligne.remove();
      else champs(ligne).forEach((c) => { c.value = ""; majDuree(ligne); });
    } else if (bouton.matches("[data-jour-suivant]")) {
      const [debut, fin] = [...champs(ligne)].map(lireDate);
      if (!debut || !fin) { champs(ligne)[debut ? 1 : 0].focus(); return; }
      ajouter(new Date(debut.getTime() + 24 * HEURE), new Date(fin.getTime() + 24 * HEURE));
    }
  });

  formulaire.querySelector("[data-ajouter]").addEventListener("click", () => ajouter());
  lignes().forEach(majDuree);
})();
