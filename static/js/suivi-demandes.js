"use strict";

document.querySelector("[data-copier-demande]")?.addEventListener("click", async (event) => {
  const bouton = event.currentTarget;
  if (bouton.disabled) return;
  const texte = document.getElementById("texte-transmission");
  const statut = document.querySelector("[data-statut-copie]");
  bouton.disabled = true;
  statut.textContent = "";
  try {
    try {
      await navigator.clipboard.writeText(texte.value);
    } catch {
      // HTTP interne ou API refusée : essayer la copie depuis la sélection.
      texte.focus();
      texte.select();
      if (!document.execCommand("copy")) throw new Error("Copie refusée");
      bouton.focus();
    }
    statut.textContent = "Texte copié. Vous pouvez le coller dans votre échange.";
  } catch {
    // Le presse-papiers peut être indisponible sur une adresse HTTP du réseau local.
    texte.focus();
    texte.select();
    statut.textContent = "Texte sélectionné : utilisez Ctrl+C ou ⌘C pour le copier.";
  } finally {
    bouton.disabled = false;
  }
});
