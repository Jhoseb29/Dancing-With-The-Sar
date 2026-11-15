import { Injectable, computed, inject, signal } from '@angular/core';
import type { Feature, FeatureCollection, Point, Polygon } from 'geojson';
import { RuntimeConfigService } from '../config/runtime-config.service';
import { cellAt, hasLayer, renderLayer } from '../harness/globe-grid';
import { runFileUrl } from '../harness/harness-client';
import { GlobeGrid, GlobeLayerId, HarnessGlobe, HarnessPayload } from '../harness/harness.model';
import { SceneStore } from '../scene/scene.store';

export interface HotspotProps {
  kind: string;
  magnitude_db: number;
  intensity: number;
  from?: string;
  to?: string;
}
export type HotspotPoints = FeatureCollection<Point, HotspotProps>;
/** Columnas 3D de cambio: un prisma por celda, altura según la magnitud del cambio. */
export type HotspotColumns = FeatureCollection<Polygon, HotspotProps & { height: number }>;

export interface ObjectProps {
  class_id: number;
  class: string;
  cells: number;
  area_km2: number;
  co_db: number | null;
  cross_db: number | null;
}
/** Objetos del terreno (nisar-harness/lib/objects.py): una mancha por clase de dispersión. */
export type TerrainObjects = FeatureCollection<Polygon, ObjectProps>;

export interface AnalysisOverlay {
  url: string;
  bbox: [number, number, number, number];
  opacity: number;
}

export interface ActiveAnalysis {
  runId: string;
  question: string;
  place: string | null;
  globe: HarnessGlobe;
  payload: HarnessPayload;
}

export interface InspectedCell {
  lon: number;
  lat: number;
  classId: number | null;
  coDb: number | null;
  crossDb: number | null;
  object: ObjectProps | null;
}

/** Altura de las columnas de cambio (m por dB): visibles a escala regional sin tapar el relieve. */
const COLUMN_M_PER_DB = 150;

/**
 * Estado del análisis NISAR que se dibuja en el globo (vista "insights"): qué toma (fecha)
 * y qué capa se ven, objetos del terreno, columnas de cambio, celda inspeccionada.
 * El harness entrega datos (grillas y polígonos); aquí se convierten en objetos del globo.
 */
@Injectable({ providedIn: 'root' })
export class HarnessGlobeService {
  private readonly apiBaseUrl = inject(RuntimeConfigService).value.apiBaseUrl;
  private readonly scene = inject(SceneStore);
  private readonly cache = new Map<string, Promise<unknown>>();

  readonly active = signal<ActiveAnalysis | null>(null);
  readonly takeIndex = signal(0);
  readonly layer = signal<GlobeLayerId>('objects');
  readonly hiddenClasses = signal<ReadonlySet<number>>(new Set());
  readonly showHotspots = signal(true);
  readonly opacity = signal(0.85);
  readonly grid = signal<GlobeGrid | null>(null);
  readonly objects = signal<TerrainObjects | null>(null);
  readonly hotspots = signal<HotspotPoints | null>(null);
  /** Cauces significativos del área (líneas GeoJSON) usados como corredor del sedimento. */
  readonly channels = signal<FeatureCollection | null>(null);
  readonly loading = signal(false);
  readonly inspected = signal<InspectedCell | null>(null);
  /** Se incrementa para pedir al mapa que encuadre el área (comando, no estado). */
  readonly focusRequest = signal(0);

  readonly take = computed(() => this.active()?.globe.takes[this.takeIndex()] ?? null);
  readonly availableLayers = computed(() => {
    const grid = this.grid();
    const raster = (['classes', 'co', 'cross'] as GlobeLayerId[]).filter(
      (l) => grid && hasLayer(grid, l),
    );
    return this.objects() ? (['objects', ...raster] as GlobeLayerId[]) : raster;
  });

  /** Campos continuos (HH, HV, clases por celda) coloreados en el navegador y apoyados sobre el relieve. */
  readonly overlay = computed<AnalysisOverlay | null>(() => {
    const grid = this.grid();
    const layer = this.layer();
    if (!grid || layer === 'objects') return null;
    const url = renderLayer(grid, layer, this.hiddenClasses());
    return url ? { url, bbox: grid.bbox, opacity: this.opacity() } : null;
  });

  /** Objetos visibles (filtrados por las clases activas en la leyenda). */
  readonly visibleObjects = computed<TerrainObjects | null>(() => {
    const fc = this.objects();
    if (!fc || this.layer() !== 'objects') return null;
    const hidden = this.hiddenClasses();
    return hidden.size
      ? { ...fc, features: fc.features.filter((f) => !hidden.has(f.properties.class_id)) }
      : fc;
  });

  readonly visibleHotspots = computed(() => (this.showHotspots() ? this.hotspots() : null));

  /** Cada punto de cambio como columna (prisma) del tamaño de su celda. */
  readonly hotspotColumns = computed<HotspotColumns | null>(() => {
    const points = this.visibleHotspots();
    const cellKm2 = this.active()?.globe.hotspots_summary?.cell_area_km2;
    if (!points?.features.length || !cellKm2) return null;
    const halfKm = Math.sqrt(cellKm2) * 0.4;
    const features = points.features.map(
      (f): Feature<Polygon, HotspotProps & { height: number }> => {
        const [lon, lat] = f.geometry.coordinates;
        const dLat = halfKm / 110.57;
        const dLon = halfKm / (111.32 * Math.cos((lat * Math.PI) / 180));
        return {
          type: 'Feature',
          properties: {
            ...f.properties,
            height: Math.round(f.properties.magnitude_db * COLUMN_M_PER_DB),
          },
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [lon - dLon, lat - dLat],
                [lon + dLon, lat - dLat],
                [lon + dLon, lat + dLat],
                [lon - dLon, lat + dLat],
                [lon - dLon, lat - dLat],
              ],
            ],
          },
        };
      },
    );
    return { type: 'FeatureCollection', features };
  });

  /** Muestra un resultado del harness en el globo y abre la vista de análisis. */
  async show(runId: string, payload: HarnessPayload, question: string): Promise<void> {
    const globe = payload.globe;
    if (!globe?.takes.length) return;
    this.active.set({ runId, question, place: payload.query?.place_name ?? null, globe, payload });
    this.inspected.set(null);
    this.hotspots.set(null);
    this.layer.set('objects');
    this.hiddenClasses.set(new Set());
    await this.selectTake(globe.takes.length - 1);
    void this.load<HotspotPoints>(runId, globe.hotspots).then((fc) => {
      if (this.active()?.runId === runId) this.hotspots.set(fc);
    });
    this.channels.set(null);
    void this.load<FeatureCollection>(runId, globe.channels ?? null).then((fc) => {
      if (this.active()?.runId === runId) this.channels.set(fc);
    });
    if (this.scene.route() !== 'insights') {
      await this.scene.set('/route', 'insights');
    }
    this.focusRequest.update((n) => n + 1);
  }

  /** Abre una corrida ya terminada (enlace compartido `?run=<id>`), sin re-ejecutar el harness. */
  async loadRun(runId: string): Promise<boolean> {
    if (this.active()?.runId === runId) return true;
    const response = await fetch(
      `${this.apiBaseUrl}/harness/runs/${encodeURIComponent(runId)}`,
    ).catch(() => null);
    if (!response?.ok) return false;
    const payload = (await response.json()) as HarnessPayload;
    await this.show(runId, payload, payload.query?.text ?? '');
    return !!payload.globe?.takes.length;
  }

  async selectTake(index: number): Promise<void> {
    const active = this.active();
    const take = active?.globe.takes[index];
    if (!active || !take) return;
    this.takeIndex.set(index);
    this.loading.set(true);
    try {
      const [grid, objects] = await Promise.all([
        this.load<GlobeGrid>(active.runId, take.data),
        this.load<TerrainObjects>(active.runId, take.objects ?? null),
      ]);
      if (this.take() !== take) return;
      this.grid.set(grid);
      this.objects.set(objects);
      const layer = this.layer();
      if (layer === 'objects' ? !objects : !grid || !hasLayer(grid, layer)) {
        this.layer.set(objects ? 'objects' : 'classes');
      }
      this.refreshInspected();
    } finally {
      this.loading.set(false);
    }
  }

  toggleClass(id: number): void {
    this.hiddenClasses.update((set) => {
      const next = new Set(set);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  }

  /** Clic en el globo: valores de la celda y, si se tocó un objeto, sus datos. */
  inspect(lon: number, lat: number, object: ObjectProps | null = null): void {
    const grid = this.grid();
    const cell = grid ? cellAt(grid, lon, lat) : null;
    this.inspected.set(
      cell || object
        ? { lon, lat, classId: null, coDb: null, crossDb: null, ...cell, object }
        : null,
    );
  }

  fileUrl(path: string): string {
    const runId = this.active()?.runId;
    return runId ? runFileUrl(this.apiBaseUrl, runId, path) : '';
  }

  private refreshInspected(): void {
    const cell = this.inspected();
    if (cell) this.inspect(cell.lon, cell.lat);
  }

  private load<T>(runId: string, path: string | null): Promise<T | null> {
    if (!path) return Promise.resolve(null);
    const url = runFileUrl(this.apiBaseUrl, runId, path);
    let pending = this.cache.get(url) as Promise<T> | undefined;
    if (!pending) {
      pending = fetch(url).then((r) => {
        if (!r.ok) throw new Error(`No se pudo cargar ${path} (${r.status})`);
        return r.json() as Promise<T>;
      });
      pending.catch(() => this.cache.delete(url));
      this.cache.set(url, pending);
    }
    return pending.catch(() => null);
  }
}
