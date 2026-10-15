"use strict";
// Administration : menus déroulants (filtres, compte), menu latéral sur petit écran, confirmations,
// choix du thème, notifications, fiches ouvertes en fenêtre depuis les listes (config/admin.py,
// ModaleMixin) et modifications non enregistrées des listes à saisie directe.

const MODALE = "_modale";
const enModale = () => document.body.classList.contains("modale");
let envoiEnCours = false;  // formulaire en cours d'envoi : pas d'alerte « modifications non enregistrées »
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
  const ouverts = [...menus()];
  for (const menu of ouverts) {
    menu.open = false;
    menu.querySelector("summary")?.focus();
  }
  document.body.classList.remove("menu-ouvert");
  // Dans une fenêtre : Échap la ferme (sauf s'il refermait d'abord un menu).
  if (!ouverts.length && enModale()) demanderFermeture();
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
  envoiEnCours = true;
  const bouton = form.querySelector("[data-libelle-attente]");
  if (bouton) {
    // Rechargement synchrone : le bouton reste inactif jusqu'à la page suivante.
    setTimeout(() => {
      bouton.disabled = true;
      bouton.textContent = bouton.dataset.libelleAttente;
    });
  }
});

// ------------------------------------------------------------------ thème
// Même clé que admin/js/theme.js de Django (chargé dans l'en-tête, il applique le thème sans flash).
function initialiserTheme() {
  let courant = "auto";
  try {
    courant = localStorage.getItem("theme") || "auto";
  } catch {
    // stockage indisponible : thème du système
  }
  for (const choix of document.querySelectorAll("[data-theme-choix]")) {
    choix.checked = choix.value === courant;
    choix.addEventListener("change", () => {
      if (!choix.checked) return;
      document.documentElement.dataset.theme = choix.value;
      try {
        localStorage.setItem("theme", choix.value);
      } catch {
        // le choix vaut pour cette page seulement
      }
    });
  }
}

// ------------------------------------------------------------------ notifications
// Messages de Django en bas à droite : fermables ; succès et informations disparaissent seuls.
function retirer(element) {
  element.classList.add("disparait");
  setTimeout(() => {
    const liste = element.parentElement;
    element.remove();
    if (liste && !liste.children.length) liste.remove();
  }, 260);
}

function preparerNotification(element) {
  const fermer = document.createElement("button");
  fermer.type = "button";
  fermer.className = "toast-fermer";
  fermer.setAttribute("aria-label", "Fermer");
  fermer.textContent = "×";
  fermer.addEventListener("click", () => retirer(element));
  element.append(fermer);
  if (!element.matches(".warning, .error")) {
    let minuteur = setTimeout(() => retirer(element), 7000);
    element.addEventListener("mouseenter", () => clearTimeout(minuteur));
    element.addEventListener("mouseleave", () => { minuteur = setTimeout(() => retirer(element), 3000); });
  }
}

function notifier(texte, niveau = "success") {
  let liste = document.querySelector("ul.messagelist");
  if (!liste) {
    liste = document.createElement("ul");
    liste.className = "messagelist";
    document.querySelector("main") ? document.querySelector("main").prepend(liste) : document.body.append(liste);
  }
  liste.setAttribute("role", "status");
  const element = document.createElement("li");
  element.className = niveau;
  element.textContent = texte;
  liste.append(element);
  preparerNotification(element);
}

// ------------------------------------------------------------------ listes à saisie directe
// Champs modifiés surlignés, bandeau « N modification(s) non enregistrée(s) », alerte avant de quitter.
const valeur = (champ) => (champ.type === "checkbox" ? String(champ.checked) : champ.value);

function suivreSaisieDirecte() {
  const form = document.getElementById("changelist-form");
  const enregistrer = form?.querySelector('input[name="_save"]');
  if (!form || !enregistrer) return;
  const champs = [...form.querySelectorAll("input, select, textarea")].filter((c) => /^form-\d+-/.test(c.name) && c.type !== "hidden");
  const initiales = new Map(champs.map((c) => [c, valeur(c)]));
  const bandeau = document.createElement("div");
  bandeau.className = "bandeau-modifications";
  bandeau.hidden = true;
  bandeau.setAttribute("role", "status");
  bandeau.innerHTML = '<span></span><div><button type="button" class="bouton">Annuler</button>' +
    '<button type="button" class="bouton primaire">Enregistrer</button></div>';
  form.append(bandeau);
  const [annuler, valider] = bandeau.querySelectorAll("button");

  const actualiser = () => {
    let nombre = 0;
    for (const [champ, initiale] of initiales) {
      const modifie = valeur(champ) !== initiale;
      champ.closest("td")?.classList.toggle("modifie", modifie);
      nombre += modifie;
    }
    form.dataset.modifications = String(nombre);
    bandeau.hidden = !nombre;
    bandeau.querySelector("span").textContent = `${nombre} modification${nombre > 1 ? "s" : ""} non enregistrée${nombre > 1 ? "s" : ""}`;
  };
  form.addEventListener("input", actualiser);
  form.addEventListener("change", actualiser);
  valider.addEventListener("click", () => form.requestSubmit(enregistrer));
  annuler.addEventListener("click", () => {
    for (const [champ, initiale] of initiales) {
      if (champ.type === "checkbox") champ.checked = initiale === "true";
      else champ.value = initiale;
    }
    actualiser();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!envoiEnCours && Number(form.dataset.modifications)) event.preventDefault();
  });
}

const modificationsEnAttente = () => Number(document.getElementById("changelist-form")?.dataset.modifications || 0);

// ------------------------------------------------------------------ fenêtres (modales)
// Liste (body.ouverture-modale) : lien vers une fiche (…/add/, …/<id>/change/) ou lien [data-modale]
// ouvert dans une fenêtre ; la page de la fiche est chargée avec ?_modale=1 (contenu seul).
const DEFILEMENT = "admin-defilement";

function avecModale(adresse) {
  const url = new URL(adresse, window.location.href);
  url.searchParams.set(MODALE, "1");
  return url;
}

function sansModale(adresse) {
  const url = new URL(adresse, window.location.href);
  url.searchParams.delete(MODALE);
  return url;
}

const estFiche = (url) => url.origin === window.location.origin && /^\/admin\/.+\/(add|[^/]+\/change)\/$/.test(url.pathname);

let fenetre = null;

function creerFenetre() {
  const dialogue = document.createElement("dialog");
  dialogue.className = "admin-modale";
  dialogue.setAttribute("aria-labelledby", "admin-modale-titre");
  dialogue.innerHTML = '<header class="admin-modale-entete"><h2 class="admin-modale-titre" id="admin-modale-titre"></h2>' +
    '<a class="admin-modale-page" href="#" target="_top">Ouvrir en pleine page ↗</a>' +
    '<button type="button" class="admin-modale-fermer" aria-label="Fermer">×</button></header>' +
    '<iframe title="Fiche"></iframe>';
  document.body.append(dialogue);
  const cadre = dialogue.querySelector("iframe");
  const titre = dialogue.querySelector(".admin-modale-titre");
  const pleinePage = dialogue.querySelector(".admin-modale-page");

  dialogue.querySelector(".admin-modale-fermer").addEventListener("click", () => fermerFenetre());
  dialogue.addEventListener("cancel", (event) => {
    event.preventDefault();
    fermerFenetre();
  });
  // Clic sur le voile (hors du cadre) : fermeture.
  dialogue.addEventListener("click", (event) => {
    if (event.target === dialogue) fermerFenetre();
  });
  cadre.addEventListener("admin-modale-fermer", () => fermerFenetre());
  cadre.addEventListener("load", () => {
    dialogue.classList.remove("chargement");
    let doc;
    try {
      doc = cadre.contentDocument;
    } catch {
      return;
    }
    if (!doc || cadre.contentWindow.location.href === "about:blank") return;
    const action = doc.body?.dataset.modaleAction;
    if (action) {
      terminerFenetre(action);
      return;
    }
    const adresse = new URL(cadre.contentWindow.location.href);
    if (!adresse.pathname.startsWith("/admin/")) {
      // Lien vers l'application (fiche réseau, événement…) : ouvert en pleine page.
      window.location.href = adresse.href;
      return;
    }
    if (!adresse.searchParams.has(MODALE) && !doc.body.classList.contains("modale")) {
      cadre.src = avecModale(adresse.href).href;  // redirection de Django sans le paramètre
      return;
    }
    titre.textContent = (doc.title || "").split(" | ")[0];
    pleinePage.href = sansModale(adresse.href).href;
    doc.querySelector("input:not([type=hidden]):not([readonly]), select, textarea")?.focus({ preventScroll: true });
  });
  return { dialogue, cadre, titre };
}

function ouvrirFenetre(adresse, libelle) {
  fenetre ??= creerFenetre();
  fenetre.titre.textContent = libelle || "";
  fenetre.dialogue.classList.add("chargement");
  fenetre.cadre.src = avecModale(adresse).href;
  fenetre.dialogue.showModal();
}

function fermerFenetre({ forcer = false } = {}) {
  if (!fenetre?.dialogue.open) return;
  let modifiee = false;
  try {
    modifiee = Boolean(fenetre.cadre.contentWindow?.modaleModifiee);
  } catch {
    // autre origine : rien à vérifier
  }
  if (modifiee && !forcer && !window.confirm("Fermer sans enregistrer les modifications ?")) return;
  fenetre.dialogue.close();
  fenetre.cadre.src = "about:blank";
}

function terminerFenetre(action) {
  fermerFenetre({ forcer: true });
  const texte = action === "supprime" ? "Supprimé." : "Enregistré.";
  if (modificationsEnAttente()) {
    // Saisie en cours dans la liste : pas de rechargement, le message de Django suivra.
    notifier(`${texte} Enregistrez vos modifications de la liste puis rechargez pour voir la fiche à jour.`, "info");
    return;
  }
  // Même liste, mêmes filtres (adresse inchangée), même position ; le message de Django s'affiche au retour.
  try {
    sessionStorage.setItem(DEFILEMENT, JSON.stringify({ page: window.location.href, y: window.scrollY }));
  } catch {
    // position perdue, liste rechargée quand même
  }
  window.location.reload();
}

function restaurerDefilement() {
  try {
    const memo = JSON.parse(sessionStorage.getItem(DEFILEMENT) || "null");
    sessionStorage.removeItem(DEFILEMENT);
    if (memo && memo.page === window.location.href) window.scrollTo(0, memo.y);
  } catch {
    // rien à restaurer
  }
}

document.addEventListener("click", (event) => {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const lien = event.target.closest("a[href]");
  if (!lien || lien.target === "_blank" || lien.hasAttribute("download")) return;
  const url = new URL(lien.href, window.location.href);
  if (enModale()) {
    // Dans la fenêtre : les pages de l'administration (suppression, historique, mot de passe) y restent.
    if (lien.matches(".closelink")) {
      event.preventDefault();
      demanderFermeture();
    } else if (url.origin === window.location.origin && url.pathname.startsWith("/admin/") && !url.searchParams.has(MODALE)) {
      event.preventDefault();
      window.location.href = avecModale(url.href).href;
    }
    return;
  }
  const dansListe = document.body.classList.contains("ouverture-modale") &&
    lien.closest("#result_list, .object-tools, .panneau") && estFiche(url);
  if (lien.hasAttribute("data-modale") || dansListe) {
    event.preventDefault();
    ouvrirFenetre(url.href, lien.dataset.modaleTitre || "");
  }
});

// Page affichée dans une fenêtre : fermeture demandée à la page parente, suivi des modifications.
function demanderFermeture() {
  window.frameElement?.dispatchEvent(new CustomEvent("admin-modale-fermer"));
}

function suivreFormulaireEnModale() {
  if (!enModale()) return;
  window.modaleModifiee = false;
  for (const form of document.querySelectorAll("#content form[method=post]")) {
    form.addEventListener("input", () => { window.modaleModifiee = true; });
    form.addEventListener("change", () => { window.modaleModifiee = true; });
  }
}

// ------------------------------------------------------------------ démarrage
initialiserTheme();
for (const element of document.querySelectorAll("body:not(.modale) ul.messagelist > li")) preparerNotification(element);
suivreSaisieDirecte();
suivreFormulaireEnModale();
restaurerDefilement();
