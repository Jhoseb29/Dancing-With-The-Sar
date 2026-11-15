// Motor 2.5D (MapLibre GL). TypeScript puro: no importa @angular/*.
// Se carga solo desde las vistas de cuenca mediante import() dinámico.
import {
  Map as MapLibreMap,
  setWorkerUrl,
  type GeoJSONSource,
  type ImageSource,
  type StyleSpecification,
} from 'maplibre-gl';
import type { FeatureCollection, Point, Polygon } from 'geojson';
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
export type MapPoints = FeatureCollection<
  Point,
  { frp?: number; confidence?: string; acq_time?: string }
>;

/** Capa de análisis NISAR coloreada en el navegador, georreferenciada por su bbox. */
export interface MapImageOverlay {
  url: string;
  bbox: BBox;
  opacity: number;
}

/** Puntos de cambio del harness (hotspots.geojson). `intensity` 0..1 pesa el mapa de calor. */
export type MapHotspots = FeatureCollection<
  Point,
  { kind: string; intensity: number; magnitude_db: number }
>;

export interface MapClick extends FeatureInfoQuery {
  lon: number;
  lat: number;
  /** Propiedades del objeto del análisis NISAR bajo el clic, si hay uno. */
  analysisObject: Record<string, unknown> | null;
}

/** Objetos del terreno (polígonos por clase de dispersión) y columnas de cambio, en GeoJSON. */
export type MapObjects = FeatureCollection<Polygon, Record<string, unknown>>;

/** Modelo de elevación (Terrarium) para dibujar el relieve 3D bajo los datos. */
export interface MapRelief {
  url: string;
  maxZoom: number;
  exaggeration: number;
  attribution?: string;
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
const ANALYSIS_ID = 'nisar-analysis';
const HOTSPOTS_ID = 'nisar-hotspots';
const HOTSPOTS_HEAT = 'nisar-hotspots-heat';
const OBJECTS_ID = 'nisar-objects';
const OBJECTS_FILL = 'nisar-objects-fill';
const OBJECTS_LINE = 'nisar-objects-line';
const OBJECTS_3D = 'nisar-objects-3d';
const COLUMNS_ID = 'nisar-columns';
const AOI_ID = 'nisar-aoi';
/** Área mínima (km²) para levantar una mancha urbana en 3D. */
const URBAN_3D_MIN_KM2 = 0.5;
const DEM_TERRAIN = 'relief-terrain';
const DEM_SHADE = 'relief-shade';

/** Colores de DATOS por clase (mismos que la leyenda del panel). */
const CLASS_COLOR = [
  'match',
  ['get', 'class'],
  'water',
  '#1e6ee6',
  'soil',
  '#c8a26a',
  'vegetation',
  '#2fa64b',
  'urban',
  '#e12d2d',
  '#888888',
];
/** Colores de DATOS por tipo de cambio. */
const KIND_COLOR = [
  'match',
  ['get', 'kind'],
  'perdida_vegetacion',
  '#ff5a00',
  'nueva_agua',
  '#00c8ff',
  'perdida_agua',
  '#8a6cff',
  'nuevo_urbano',
  '#ff2ad4',
  '#ffd000',
];

export class GeoEngine {
  private readonly map: MapLibreMap;
  private panelOpen: boolean;
  private styleReady = false;
  private pendingLayers: MapOverlay[] | null = null;
  private pendingPoints: MapPoints | null | undefined;
  private pendingAnalysis: MapImageOverlay | null | undefined;
  private pendingHotspots: MapHotspots | null | undefined;
  private pendingObjects: MapObjects | null | undefined;
  private pendingColumns: MapObjects | null | undefined;
  private pendingRelief: MapRelief | null | undefined;
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
      if (this.pendingAnalysis !== undefined) {
        this.setAnalysis(this.pendingAnalysis);
        this.pendingAnalysis = undefined;
      }
      if (this.pendingHotspots !== undefined) {
        this.setHotspots(this.pendingHotspots);
        this.pendingHotspots = undefined;
      }
      if (this.pendingRelief !== undefined) {
        this.setRelief(this.pendingRelief);
        this.pendingRelief = undefined;
      }
      if (this.pendingObjects !== undefined) {
        this.setObjects(this.pendingObjects);
        this.pendingObjects = undefined;
      }
      if (this.pendingColumns !== undefined) {
        this.setColumns(this.pendingColumns);
        this.pendingColumns = undefined;
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
      const layers = [OBJECTS_3D, OBJECTS_FILL].filter((id) => this.map.getLayer(id));
      const hit = layers.length
        ? this.map.queryRenderedFeatures(event.point, { layers })[0]
        : undefined;
      options.onClick({
        analysisObject: (hit?.properties as Record<string, unknown> | undefined) ?? null,
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
        this.map.addLayer(
          { id, type: 'raster', source: id, paint: { 'raster-opacity': layer.opacity } },
          'basin-outline',
        );
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
        'circle-color': [
          'interpolate',
          ['linear'],
          ['coalesce', ['get', 'frp'], 0],
          0,
          '#ffb000',
          50,
          '#ff5a00',
          300,
          '#d10000',
        ],
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 3, 1.5, 8, 4, 12, 7],
        'circle-opacity': 0.85,
        'circle-stroke-width': 0.5,
        'circle-stroke-color': '#000000',
      },
    });
  }

  /** Dibuja (o quita) la capa de análisis NISAR (imagen georreferenciada por bbox). */
  setAnalysis(overlay: MapImageOverlay | null): void {
    if (!this.styleReady) {
      this.pendingAnalysis = overlay;
      return;
    }
    const source = this.map.getSource(ANALYSIS_ID) as ImageSource | undefined;
    if (!overlay) {
      if (source) {
        this.map.removeLayer(ANALYSIS_ID);
        this.map.removeSource(ANALYSIS_ID);
      }
      return;
    }
    const [w, s, e, n] = overlay.bbox;
    const coordinates: [[number, number], [number, number], [number, number], [number, number]] = [
      [w, n],
      [e, n],
      [e, s],
      [w, s],
    ];
    if (source) {
      source.updateImage({ url: overlay.url, coordinates });
    } else {
      this.map.addSource(ANALYSIS_ID, { type: 'image', url: overlay.url, coordinates });
      this.map.addLayer(
        {
          id: ANALYSIS_ID,
          type: 'raster',
          source: ANALYSIS_ID,
          paint: { 'raster-resampling': 'linear', 'raster-fade-duration': 0 },
        },
        'basin-outline',
      );
    }
    this.map.setPaintProperty(ANALYSIS_ID, 'raster-opacity', overlay.opacity);
  }

  /** Puntos de cambio: mapa de calor de lejos, puntos por tipo de cerca. */
  setHotspots(points: MapHotspots | null): void {
    if (!this.styleReady) {
      this.pendingHotspots = points;
      return;
    }
    const source = this.map.getSource(HOTSPOTS_ID) as GeoJSONSource | undefined;
    if (!points) {
      if (source) {
        this.map.removeLayer(HOTSPOTS_HEAT);
        this.map.removeSource(HOTSPOTS_ID);
      }
      return;
    }
    if (source) {
      source.setData(points);
      return;
    }
    this.map.addSource(HOTSPOTS_ID, { type: 'geojson', data: points });
    // Colores de datos (no de interfaz).
    this.map.addLayer({
      id: HOTSPOTS_HEAT,
      type: 'heatmap',
      source: HOTSPOTS_ID,
      // De lejos, mapa de calor; de cerca lo reemplazan las columnas 3D.
      maxzoom: 9.5,
      paint: {
        'heatmap-weight': ['coalesce', ['get', 'intensity'], 0.5],
        'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 5, 0.3, 9, 0.8],
        'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 5, 4, 9, 12],
        'heatmap-opacity': ['interpolate', ['linear'], ['zoom'], 7, 0.75, 9.5, 0],
        'heatmap-color': [
          'interpolate',
          ['linear'],
          ['heatmap-density'],
          0,
          'rgba(0,0,0,0)',
          0.2,
          '#ffd000',
          0.5,
          '#ff7a00',
          0.8,
          '#ff2a00',
          1,
          '#ffffff',
        ],
      },
    });
  }

  /** Objetos del terreno: rellenos que se apoyan en el relieve + zonas urbanas levantadas en 3D. */
  setObjects(objects: MapObjects | null): void {
    if (!this.styleReady) {
      this.pendingObjects = objects;
      return;
    }
    const source = this.map.getSource(OBJECTS_ID) as GeoJSONSource | undefined;
    if (!objects) {
      if (source) {
        [OBJECTS_3D, OBJECTS_LINE, OBJECTS_FILL].forEach((id) => this.map.removeLayer(id));
        this.map.removeSource(OBJECTS_ID);
      }
      return;
    }
    if (source) {
      source.setData(objects);
      return;
    }
    this.map.addSource(OBJECTS_ID, { type: 'geojson', data: objects });
    this.map.addLayer(
      {
        id: OBJECTS_FILL,
        type: 'fill',
        source: OBJECTS_ID,
        // Las manchas urbanas pequeñas quedan planas (suelen ser laderas mirando al radar).
        filter: [
          'any',
          ['!=', ['get', 'class'], 'urban'],
          ['<', ['get', 'area_km2'], URBAN_3D_MIN_KM2],
        ],
        paint: {
          'fill-color': CLASS_COLOR as never,
          // El bosque (fondo dominante) casi no tiñe: se ve el terreno real; agua y suelo destacan.
          'fill-opacity': [
            'match',
            ['get', 'class'],
            'vegetation',
            0.06,
            'soil',
            0.45,
            'water',
            0.85,
            0.45,
          ],
          'fill-antialias': true,
        },
      },
      'basin-outline',
    );
    this.map.addLayer(
      {
        id: OBJECTS_LINE,
        type: 'line',
        source: OBJECTS_ID,
        filter: ['!=', ['get', 'class'], 'vegetation'],
        paint: {
          'line-color': CLASS_COLOR as never,
          'line-width': ['interpolate', ['linear'], ['zoom'], 7, 0.4, 12, 1.5],
          'line-opacity': 0.9,
          'line-blur': 0.5,
        },
      },
      'basin-outline',
    );
    this.map.addLayer({
      id: OBJECTS_3D,
      type: 'fill-extrusion',
      source: OBJECTS_ID,
      // Solo manchas de tamaño barrio se levantan en 3D.
      filter: [
        'all',
        ['==', ['get', 'class'], 'urban'],
        ['>=', ['get', 'area_km2'], URBAN_3D_MIN_KM2],
      ],
      paint: {
        'fill-extrusion-color': CLASS_COLOR as never,
        // Más brillo de rebote doble → más alto (exagerado para verse a escala regional).
        'fill-extrusion-height': [
          'interpolate',
          ['linear'],
          ['coalesce', ['get', 'co_db'], -6],
          -8,
          60,
          0,
          380,
        ],
        'fill-extrusion-base': 0,
        'fill-extrusion-opacity': 0.85,
        'fill-extrusion-vertical-gradient': true,
      },
    });
  }

  /** Contorno del área que pidió el usuario (para ver qué parte cubre el satélite). */
  setAoi(bbox: BBox | null): void {
    if (!this.styleReady) {
      this.map.once('style.load', () => this.setAoi(bbox));
      return;
    }
    const source = this.map.getSource(AOI_ID) as GeoJSONSource | undefined;
    if (!bbox) {
      if (source) {
        this.map.removeLayer(AOI_ID);
        this.map.removeSource(AOI_ID);
      }
      return;
    }
    if (source) {
      source.setData(bboxPolygon(bbox));
      return;
    }
    this.map.addSource(AOI_ID, { type: 'geojson', data: bboxPolygon(bbox) });
    this.map.addLayer({
      id: AOI_ID,
      type: 'line',
      source: AOI_ID,
      paint: {
        'line-color': '#f0f0fa',
        'line-width': 1.5,
        'line-dasharray': [3, 2],
        'line-opacity': 0.9,
      },
    });
  }

  /** Columnas 3D de cambio entre tomas (altura = magnitud del cambio). */
  setColumns(columns: MapObjects | null): void {
    if (!this.styleReady) {
      this.pendingColumns = columns;
      return;
    }
    const source = this.map.getSource(COLUMNS_ID) as GeoJSONSource | undefined;
    if (!columns) {
      if (source) {
        this.map.removeLayer(COLUMNS_ID);
        this.map.removeSource(COLUMNS_ID);
      }
      return;
    }
    if (source) {
      source.setData(columns);
      return;
    }
    this.map.addSource(COLUMNS_ID, { type: 'geojson', data: columns });
    this.map.addLayer({
      id: COLUMNS_ID,
      type: 'fill-extrusion',
      source: COLUMNS_ID,
      minzoom: 8,
      paint: {
        'fill-extrusion-color': KIND_COLOR as never,
        'fill-extrusion-height': ['get', 'height'],
        'fill-extrusion-base': 0,
        'fill-extrusion-opacity': 0.9,
        'fill-extrusion-vertical-gradient': true,
      },
    });
  }

  /** Relieve 3D + sombreado de laderas: los datos se apoyan sobre las montañas reales. */
  setRelief(relief: MapRelief | null): void {
    if (!this.styleReady) {
      this.pendingRelief = relief;
      return;
    }
    if (!relief) {
      this.map.setTerrain(null);
      if (this.map.getLayer(DEM_SHADE)) this.map.removeLayer(DEM_SHADE);
      [DEM_SHADE, DEM_TERRAIN].forEach((id) => this.map.getSource(id) && this.map.removeSource(id));
      return;
    }
    if (this.map.getSource(DEM_TERRAIN)) return;
    const dem = {
      type: 'raster-dem' as const,
      tiles: [relief.url],
      tileSize: 256,
      maxzoom: relief.maxZoom,
      encoding: 'terrarium' as const,
      attribution: relief.attribution,
    };
    this.map.addSource(DEM_TERRAIN, dem);
    this.map.addSource(DEM_SHADE, { ...dem, attribution: undefined });
    this.map.addLayer(
      {
        id: DEM_SHADE,
        type: 'hillshade',
        source: DEM_SHADE,
        paint: {
          'hillshade-exaggeration': 0.55,
          'hillshade-shadow-color': '#000000',
          'hillshade-highlight-color': '#ffffff',
          'hillshade-accent-color': '#1a1a1a',
        },
      },
      'basin-outline',
    );
    this.map.setTerrain({ source: DEM_TERRAIN, exaggeration: relief.exaggeration });
  }

  /** Encuadra un área; con `pitch` inclina la cámara al terminar para ver relieve y objetos 3D. */
  fitArea(bbox: BBox, pitch = 0): void {
    this.map.fitBounds(bbox, {
      padding: panelAwarePadding(this.map.getContainer(), this.panelOpen),
      duration: 1500,
    });
    if (pitch) {
      this.map.once('moveend', () => this.map.easeTo({ pitch, bearing: -12, duration: 1400 }));
    } else if (this.map.getPitch()) {
      this.map.easeTo({ pitch: 0, bearing: 0, duration: 800 });
    }
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
      {
        id: 'city-outline',
        type: 'line',
        source: 'city',
        paint: { 'line-color': '#f0f0fa', 'line-width': 1.5 },
      },
    ],
  };
}
