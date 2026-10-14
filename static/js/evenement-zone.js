"use strict";
// Carte de la zone couverte par un événement (templates/evenements/detail.html) : seuls les sites de
// l'événement et leurs secteurs actifs (vert plein : secteur entier, vert clair : en partie),
// cadrée sur la zone. Le reste du réseau est masqué. Remorques (sites mobiles) : à la position et selon
// les secteurs déclarés dans l'événement, centre carré.

(() => {
  const cadre = document.querySelector("[data-zone]");
  if (!cadre || !window.L) return;
  const zone = JSON.parse(document.getElementById(cadre.dataset.zone).textContent);
  const OUVERTURE = 60, RAYON = 30;

  const echapper = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  function chemin(cx, cy, r, az, plein = false) {
    if (plein) return `M${cx - r},${cy} a${r},${r} 0 1 0 ${2 * r},0 a${r},${r} 0 1 0 ${-2 * r},0 Z`;  // omni
    const point = (deg) => {
      const rad = (deg * Math.PI) / 180;
      return `${(cx + r * Math.sin(rad)).toFixed(2)},${(cy - r * Math.cos(rad)).toFixed(2)}`;
    };
    return `M${cx},${cy} L${point(az - OUVERTURE / 2)} A${r},${r} 0 0 1 ${point(az + OUVERTURE / 2)} Z`;
  }

  function icone(site) {
    const t = RAYON + 4;
    const nb = site.nb_secteurs || site.secteurs.length;
    const coins = site.secteurs.map((s) => {
      // Azimut inconnu : secteurs répartis régulièrement (pointillés). Seul secteur à 0° : omni (360°).
      const omni = nb === 1 && s.azimut === 0;
      const az = s.azimut != null ? s.azimut : ((s.numero - 1) * 360) / Math.max(nb, 1);
      const azimut = s.azimut == null ? " (azimut inconnu)" : omni ? " · omni (360°)" : ` · ${s.azimut}°`;
      const titre = `${site.nom}${site.mobile ? " (site mobile)" : ""} · secteur ${s.numero}${azimut} · ${s.cellules} cellules`;
      return `<path class="zone-coin ${s.etat}${s.azimut == null ? " estime" : ""}" d="${chemin(t, t, RAYON, az, omni)}"><title>${echapper(titre)}</title></path>`;
    }).join("");
    const centre = site.mobile ? `<rect class="zone-centre" x="${t - 5}" y="${t - 5}" width="10" height="10" rx="2"/>`
      : `<circle class="zone-centre" cx="${t}" cy="${t}" r="5"/>`;
    return L.divIcon({
      className: `zone-marqueur${site.mobile ? " mobile" : ""}`,
      html: `<svg width="${2 * t}" height="${2 * t}" viewBox="0 0 ${2 * t} ${2 * t}">${coins}`
        + `${centre}</svg><span class="zone-nom">${echapper(site.nom)}</span>`,
      iconSize: [2 * t, 2 * t],
      iconAnchor: [t, t],
    });
  }

  const carte = L.map(cadre, { scrollWheelZoom: false, zoomSnap: 0.5, maxZoom: 18 });
  if (cadre.dataset.tuiles) {
    // OpenStreetMap refuse les tuiles sans Referer : l'origine du site est envoyée (cf. edition).
    L.tileLayer(cadre.dataset.tuiles, { maxZoom: 19, attribution: cadre.dataset.attribution || "",
                                        referrerPolicy: "strict-origin-when-cross-origin" }).addTo(carte);
  }
  carte.attributionControl.setPrefix(false);
  const points = zone.sites.map((site) => {
    L.marker([site.lat, site.lon], { icon: icone(site), keyboard: false, interactive: false }).addTo(carte);
    return [site.lat, site.lon];
  });
  if (points.length === 1) carte.setView(points[0], 15);
  else carte.fitBounds(points, { padding: [50, 50], maxZoom: 16 });
  // Molette : seulement après un clic sur la carte (la page défile normalement).
  carte.once("click", () => carte.scrollWheelZoom.enable());
})();
