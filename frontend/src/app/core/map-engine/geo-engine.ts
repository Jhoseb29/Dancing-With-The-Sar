// Motor 2.5D (MapLibre GL). TypeScript puro: no importa @angular/*.
// Se carga solo desde las vistas de cuenca mediante import() dinámico.
import { Map as MapLibreMap, setWorkerUrl, type GeoJSONSource, type StyleSpecification } from 'maplibre-gl';
import type { FeatureCollection, Point } from 'geojson';
import type { BBox } from '../config/runtime-config.model';
import { FeatureInfoQuery, lonLatTo3857 } from '../data-access/gamc-wms.client';

export interface MapBasemap {
  url: string;
  maxZoom: number;
  attribution?: string;
}

/** Capa raster superpuesta (WMS del GAMC o GIBS por fecha) tal como la pide el shadow. */
export interface MapOverlay {
  presetId: string;
  /** URL de teselas ya resuelta (fecha incluida); si cambia, se recrea la fuente. */
  tiles: string;
  maxZoom?: number;
  visible: boolean;
  opacity: number;
  attribution?: string;
}

/** Puntos (p. ej. focos FIRMS) en GeoJSON. `frp` (MW) define el tamaño. */
export type MapPoints = FeatureCollection<Point, { frp?: number; confidence?: string; acq_time?: string }>;

export interface MapClick extends FeatureInfoQuery {
  lon: number;
  lat: number;
}

export interface GeoEngineOptions {
  container: HTMLElement;
  basemap: MapBasemap;
  initialBBox: BBox;
  outlines: { city: BBox; basin: BBox };
  apiBaseUrl: string;
  workerUrl: string;
  onViewChange: (view: { lon: number; lat: number; zoom: number }) => void;
  onLayerStatus: (presetId: string, status: 'loading' | 'ready' | 'error') => void;
  onClick: (click: MapClick) => void;
  /** El panel lateral está visible al crear el mapa (el encuadre le deja espacio). */
  panelOpen: boolean;
}

const OVERLAY_PREFIX = 'ov:';
const POINTS_ID = 'event-points';

export class GeoEngine {
  private readonly map: MapLibreMap;
  private panelOpen: boolean;
  private styleReady = false;
  private pendingLayers: MapOverlay[] | null = null;
  private pendingPoints: MapPoints | null | undefined;
  private readonly tileUrls = new Map<string, string>();

  constructor(private readonly options: GeoEngineOptions) {
    setWorkerUrl(options.workerUrl);
    this.panelOpen = options.panelOpen;

    this.map = new MapLibreMap({
      container: options.container,
      style: buildStyle(options),
      bounds: options.initialBBox,
      fitBoundsOptions: { padding: panelAwarePadding(options.container, options.panelOpen) },
      attributionControl: { compact: true },
    });

    this.map.on('style.load', () => {
      this.map.setProjection({ type: 'globe' });
      this.styleReady = true;
      if (this.pendingLayers) {
        this.setOverlays(this.pendingLayers);
        this.pendingLayers = null;
      }
      if (this.pendingPoints !== undefined) {
        this.setPoints(this.pendingPoints);
        this.pendingPoints = undefined;
      }
    });

    // Publicar la vista solo al terminar el gesto, nunca por frame.
    this.map.on('moveend', () => {
      const center = this.map.getCenter();
      options.onViewChange({ lon: center.lng, lat: center.lat, zoom: this.map.getZoom() });
    });

    this.map.on('sourcedata', (event) => {
      if (event.sourceId?.startsWith(OVERLAY_PREFIX) && event.isSourceLoaded) {
        options.onLayerStatus(event.sourceId.slice(OVERLAY_PREFIX.length), 'ready');
      }
    });

    this.map.on('error', (event) => {
      const sourceId = (event as { sourceId?: string }).sourceId;
      if (sourceId?.startsWith(OVERLAY_PREFIX)) {
        options.onLayerStatus(sourceId.slice(OVERLAY_PREFIX.length), 'error');
      }
    });

    this.map.on('click', (event) => {
      const canvas = this.map.getCanvas();
      const bounds = this.map.getBounds();
      const [minX, minY] = lonLatTo3857(bounds.getWest(), bounds.getSouth());
      const [maxX, maxY] = lonLatTo3857(bounds.getEast(), bounds.getNorth());
      options.onClick({
        lon: event.lngLat.lng,
        lat: event.lngLat.lat,
        bbox3857: [minX, minY, maxX, maxY],
        width: canvas.clientWidth,
        height: canvas.clientHeight,
        x: event.point.x,
        y: event.point.y,
      });
    });
  }

  /** Sincroniza las capas raster superpuestas con lo que pide el shadow (en orden). */
  setOverlays(layers: MapOverlay[]): void {
    if (!this.styleReady) {
      this.pendingLayers = layers;
      return;
    }
    const wanted = new Map(layers.map((l) => [OVERLAY_PREFIX + l.presetId, l]));

    // Quitar las que ya no están o cambiaron de URL (p. ej. otra fecha).
    for (const id of Object.keys(this.map.getStyle().sources)) {
      if (!id.startsWith(OVERLAY_PREFIX)) continue;
      const next = wanted.get(id);
      if (!next || this.tileUrls.get(id) !== next.tiles) {
        this.map.removeLayer(id);
        this.map.removeSource(id);
        this.tileUrls.delete(id);
      }
    }

    // Agregar o actualizar, en orden, debajo de los contornos y los puntos.
    for (const layer of layers) {
      const id = OVERLAY_PREFIX + layer.presetId;
      if (!this.map.getSource(id)) {
        this.map.addSource(id, {
          type: 'raster',
          tiles: [layer.tiles],
          tileSize: 256,
          maxzoom: layer.maxZoom ?? 22,
          attribution: layer.attribution,
        });
        this.map.addLayer({ id, type: 'raster', source: id, paint: { 'raster-opacity': layer.opacity } }, 'basin-outline');
        this.tileUrls.set(id, layer.tiles);
        if (layer.visible) {
          this.options.onLayerStatus(layer.presetId, 'loading');
        }
      } else {
        this.map.moveLayer(id, 'basin-outline');
      }
      this.map.setPaintProperty(id, 'raster-opacity', layer.opacity);
      this.map.setLayoutProperty(id, 'visibility', layer.visible ? 'visible' : 'none');
    }
  }

  /** Dibuja (o quita) puntos de eventos, p. ej. focos de calor FIRMS. */
  setPoints(points: MapPoints | null): void {
    if (!this.styleReady) {
      this.pendingPoints = points;
      return;
    }
    const source = this.map.getSource(POINTS_ID) as GeoJSONSource | undefined;
    if (!points) {
      if (source) {
        this.map.removeLayer(POINTS_ID);
        this.map.removeSource(POINTS_ID);
      }
      return;
    }
    if (source) {
      source.setData(points);
      return;
    }
    this.map.addSource(POINTS_ID, { type: 'geojson', data: points });
    this.map.addLayer({
      id: POINTS_ID,
      type: 'circle',
      source: POINTS_ID,
      paint: {
        // Color de datos (no de interfaz): focos de calor.
        'circle-color': ['interpolate', ['linear'], ['coalesce', ['get', 'frp'], 0], 0, '#ffb000', 50, '#ff5a00', 300, '#d10000'],
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 3, 1.5, 8, 4, 12, 7],
        'circle-opacity': 0.85,
        'circle-stroke-width': 0.5,
        'circle-stroke-color': '#000000',
      },
    });
  }

  fitArea(bbox: BBox): void {
    this.map.fitBounds(bbox, { padding: panelAwarePadding(this.map.getContainer(), this.panelOpen), duration: 1500 });
  }

  /** Al ocultar o mostrar el panel, el centro de la vista se desliza al área libre. */
  setPanelOpen(open: boolean): void {
    if (open === this.panelOpen) return;
    this.panelOpen = open;
    this.map.easeTo({ padding: panelAwarePadding(this.map.getContainer(), open), duration: 600 });
  }

  destroy(): void {
    this.map.remove();
  }
}

/** Deja libre el panel flotante (tercio izquierdo en escritorio, hoja inferior en móvil). */
function panelAwarePadding(container: HTMLElement, panelOpen: boolean) {
  const width = container.clientWidth;
  const height = container.clientHeight;
  if (!panelOpen) {
    return { top: 90, left: 40, right: 40, bottom: 40 };
  }
  if (width < 768) {
    return { top: 90, left: 20, right: 20, bottom: Math.round(height * 0.5) };
  }
  return { top: 90, left: Math.min(520, Math.round(width * 0.45)), right: 40, bottom: 40 };
}

function bboxPolygon([minLon, minLat, maxLon, maxLat]: BBox) {
  return {
    type: 'Feature' as const,
    properties: {},
    geometry: {
      type: 'Polygon' as const,
      coordinates: [
        [
          [minLon, minLat],
          [maxLon, minLat],
          [maxLon, maxLat],
          [minLon, maxLat],
          [minLon, minLat],
        ],
      ],
    },
  };
}

function buildStyle({ basemap, outlines }: GeoEngineOptions): StyleSpecification {
  return {
    version: 8,
    sources: {
      basemap: {
        type: 'raster',
        tiles: [basemap.url],
        tileSize: 256,
        maxzoom: basemap.maxZoom,
        attribution: basemap.attribution,
      },
      basin: { type: 'geojson', data: bboxPolygon(outlines.basin) },
      city: { type: 'geojson', data: bboxPolygon(outlines.city) },
    },
    layers: [
      { id: 'background', type: 'background', paint: { 'background-color': '#000000' } },
      { id: 'basemap', type: 'raster', source: 'basemap' },
      {
        id: 'basin-outline',
        type: 'line',
        source: 'basin',
        paint: { 'line-color': '#9a9aa3', 'line-width': 1, 'line-dasharray': [4, 3] },
      },
      { id: 'city-outline', type: 'line', source: 'city', paint: { 'line-color': '#f0f0fa', 'line-width': 1.5 } },
    ],
  };
}
