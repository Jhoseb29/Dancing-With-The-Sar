/**
 * Imagen satelital híbrida (relieve, vegetación, ríos, calles y nombres) que se dibuja sobre el
 * mapa base en el globo (Cesium) y en el mapa (MapLibre), para que todas las vistas se vean igual.
 */
export const DETAIL_IMAGERY = {
  url: 'https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
  maxZoom: 20,
  attribution: '© Google',
} as const;
