"use strict";
// Administration : menus déroulants (filtres, compte), menu latéral sur petit écran, confirmations.

const menus = () => document.querySelectorAll("details.filtre[open], details.admin-compte[open]");

document.addEventListener("click", (event) => {
  for (const menu of menus()) {
    if (!menu.contains(event.target)) menu.open = false;
  }
  const bouton = event.target.closest("[data-ouvrir-menu]");
  if (bouton) {
    const ouvert = document.body.classList.toggle("menu-ouvert");
    bouton.setAttribute("aria-expanded", String(ouvert));
  } else if (document.body.classList.contains("menu-ouvert") && !event.target.closest("#nav-sidebar")) {
    document.body.classList.remove("menu-ouvert");
    document.querySelector("[data-ouvrir-menu]")?.setAttribute("aria-expanded", "false");
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  for (const menu of menus()) {
    menu.open = false;
    menu.querySelector("summary")?.focus();
  }
  document.body.classList.remove("menu-ouvert");
});

// Un seul menu déroulant ouvert à la fois.
document.addEventListener("toggle", (event) => {
  const cible = event.target;
  if (!(cible instanceof HTMLDetailsElement) || !cible.open) return;
  if (!cible.matches("details.filtre, details.admin-compte")) return;
  for (const menu of menus()) {
    if (menu !== cible) menu.open = false;
  }
}, true);

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (form.dataset.confirmer && !window.confirm(form.dataset.confirmer)) {
    event.preventDefault();
    return;
  }
  const bouton = form.querySelector("[data-libelle-attente]");
  if (bouton) {
    // Rechargement synchrone : le bouton reste inactif jusqu'à la page suivante.
    setTimeout(() => {
      bouton.disabled = true;
      bouton.textContent = bouton.dataset.libelleAttente;
    });
  }
});
