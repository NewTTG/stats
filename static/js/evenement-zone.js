"use strict";
// Carte de la zone couverte par un événement (templates/evenements/detail.html) : seuls les sites de
// l'événement et leurs secteurs actifs (vert plein : secteur entier, vert clair : en partie),
// cadrée sur la zone. Le reste du réseau est masqué.

(() => {
  const cadre = document.querySelector("[data-zone]");
  if (!cadre || !window.L) return;
  const zone = JSON.parse(document.getElementById(cadre.dataset.zone).textContent);
  const OUVERTURE = 60, RAYON = 30;

  const echapper = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  function chemin(cx, cy, r, az) {
    const point = (deg) => {
      const rad = (deg * Math.PI) / 180;
      return `${(cx + r * Math.sin(rad)).toFixed(2)},${(cy - r * Math.cos(rad)).toFixed(2)}`;
    };
    return `M${cx},${cy} L${point(az - OUVERTURE / 2)} A${r},${r} 0 0 1 ${point(az + OUVERTURE / 2)} Z`;
  }

  function icone(site) {
    const t = RAYON + 4;
    const coins = site.secteurs.map((s) => {
      // Azimut inconnu : secteurs répartis régulièrement (pointillés).
      const az = s.azimut != null ? s.azimut : (s.numero - 1) * 120;
      const titre = `${site.nom} · secteur ${s.numero}${s.azimut == null ? " (azimut inconnu)" : ` · ${s.azimut}°`} · ${s.cellules} cellules`;
      return `<path class="zone-coin ${s.etat}${s.azimut == null ? " estime" : ""}" d="${chemin(t, t, RAYON, az)}"><title>${echapper(titre)}</title></path>`;
    }).join("");
    return L.divIcon({
      className: "zone-marqueur",
      html: `<svg width="${2 * t}" height="${2 * t}" viewBox="0 0 ${2 * t} ${2 * t}">${coins}`
        + `<circle class="zone-centre" cx="${t}" cy="${t}" r="5"/></svg><span class="zone-nom">${echapper(site.nom)}</span>`,
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
