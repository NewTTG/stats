"use strict";

document.querySelector("[data-copier-demande]")?.addEventListener("click", async () => {
  const texte = document.getElementById("texte-transmission");
  const statut = document.querySelector("[data-statut-copie]");
  try {
    await navigator.clipboard.writeText(texte.value);
    statut.textContent = "Texte copié. Vous pouvez le coller dans votre échange.";
  } catch {
    // Le presse-papiers peut être indisponible sur une adresse HTTP du réseau local.
    texte.focus();
    texte.select();
    statut.textContent = "Texte sélectionné : utilisez Ctrl+C ou ⌘C pour le copier.";
  }
});
