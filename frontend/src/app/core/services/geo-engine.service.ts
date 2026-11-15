import { EffectRef, Injectable, Injector, effect, inject, signal, untracked } from '@angular/core';
import { RuntimeConfigService } from '../config/runtime-config.service';
import { UiConfigService } from '../config/ui-config.service';
import {
  GamcFeature,
  gamcFeatureInfo,
  gamcTileUrl,
  sanitizeFeatureProperties,
} from '../data-access/gamc-wms.client';
import { FireDay, fetchFireDay } from '../data-access/fires.client';
import type {
  GeoEngine,
  MapClick,
  MapObjects,
  MapOverlay,
  MapRelief,
} from '../map-engine/geo-engine';
import { SceneStore } from '../scene/scene.store';
import { EventService } from './event.service';
import { HarnessGlobeService, ObjectProps } from './harness-globe.service';

/** Relieve 3D público (AWS Open Data · Terrain Tiles, Terrarium). Sin key. */
const RELIEF: MapRelief = {
  url: 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png',
  maxZoom: 15,
  exaggeration: 1.5,
  attribution: 'Relieve: AWS Terrain Tiles (Mapzen)',
};
/** Inclinación de la cámara al mostrar un análisis (deja ver relieve y objetos 3D). */
const ANALYSIS_PITCH = 55;
import { ensureStylesheet } from './lazy-stylesheet';

export interface MapView {
  lon: number;
  lat: number;
  zoom: number;
}

export interface FeatureInfoResult {
  presetId: string;
  features: GamcFeature[];
  error?: string;
}

export type FiresState =
  | { status: 'idle' }
  | { status: 'loading'; date: string }
  | { status: 'ready'; date: string; day: FireDay }
  | { status: 'unavailable' | 'error'; date: string; message: string };

export interface FeatureInfoState {
  lon: number;
  lat: number;
  loading: boolean;
  results: FeatureInfoResult[];
}

/**
 * Adaptador Angular ↔ motor 2.5D. Carga MapLibre con import() dinámico,
 * dibuja las capas del shadow (/layers), obedece /camera/placeId, reporta la
 * vista y el estado de cada capa, y consulta GetFeatureInfo al hacer clic.
 */
@Injectable({ providedIn: 'root' })
export class GeoEngineService {
  private readonly config = inject(RuntimeConfigService);
  private readonly ui = inject(UiConfigService);
  private readonly scene = inject(SceneStore);
  private readonly injector = inject(Injector);
  private readonly events = inject(EventService);
  private readonly analysis = inject(HarnessGlobeService);
  private engine: GeoEngine | null = null;
  private effects: EffectRef[] = [];

  readonly view = signal<MapView | null>(null);
  readonly ready = signal(false);
  readonly featureInfo = signal<FeatureInfoState | null>(null);
  readonly fires = signal<FiresState>({ status: 'idle' });
  private firesKey = '';

  async attach(container: HTMLElement): Promise<void> {
    this.detach();
    ensureStylesheet('maplibre/maplibre-gl.css');
    const { GeoEngine } = await import('../map-engine/geo-engine');

    const city = this.ui.place('cochabamba-city');
    const basin = this.ui.place('cochabamba-basin');
    if (!city || !basin) {
      throw new Error('places.json debe definir cochabamba-city y cochabamba-basin');
    }
    const placeId = this.scene.camera().placeId;
    const initial = (placeId && this.ui.place(placeId)?.bbox) || city.bbox;
    const basemap = this.ui.basemap();

    this.engine = new GeoEngine({
      container,
      basemap: { url: basemap.url, maxZoom: basemap.maxZoom, attribution: basemap.attribution },
      initialBBox: initial,
      outlines: { city: city.bbox, basin: basin.bbox },
      apiBaseUrl: this.config.value.apiBaseUrl,
      workerUrl: new URL('maplibre/maplibre-gl-worker.mjs', document.baseURI).href,
      onViewChange: (view) => {
        this.view.set(view);
        this.scene.reportCamera({ lon: view.lon, lat: view.lat, zoom: view.zoom });
      },
      onLayerStatus: (presetId, status) => this.scene.reportLayer(presetId, status),
      onClick: (click) => {
        if (this.scene.route() === 'insights') {
          this.analysis.inspect(click.lon, click.lat, click.analysisObject as ObjectProps | null);
        } else {
          void this.queryFeatureInfo(click);
        }
      },
      panelOpen: this.scene.panels().layerPanel,
    });
    this.ready.set(true);
    this.bindScene();
  }

  fitPlace(placeId: string): void {
    const place = this.ui.place(placeId);
    if (place) {
      this.engine?.fitArea(place.bbox);
    }
  }

  clearFeatureInfo(): void {
    this.featureInfo.set(null);
  }

  detach(): void {
    this.effects.forEach((ref) => ref.destroy());
    this.effects = [];
    this.engine?.destroy();
    this.engine = null;
    this.ready.set(false);
    this.featureInfo.set(null);
    this.firesKey = '';
    this.fires.set({ status: 'idle' });
  }

  private bindScene(): void {
    const options = { injector: this.injector };
    this.effects.push(
      effect(() => {
        // Cada vista tiene sus capas: en eventos, las del evento (events.json);
        // en el resto, las capas GAMC del shadow (/layers). Así no se pisan.
        const route = this.scene.route();
        const event = this.scene.state().event;
        // En el análisis NISAR solo se ve el resultado del harness (sin capas municipales).
        const layers =
          route === 'events' && event
            ? this.events.layersFor(event.type)
            : route === 'insights'
              ? []
              : this.scene.layers().filter((l) => this.ui.layer(l.presetId)?.kind === 'gamc-wms');
        const date = this.scene.time().date;
        untracked(() => {
          const overlays = this.toOverlays(layers, date);
          this.scene.pruneReportedLayers(overlays.map((o) => o.presetId));
          this.engine?.setOverlays(overlays);
        });
      }, options),
      // Análisis NISAR: grilla coloreada en el navegador + puntos de cambio.
      effect(() => {
        const onAnalysis = this.scene.route() === 'insights';
        const overlay = onAnalysis ? this.analysis.overlay() : null;
        const objects = onAnalysis ? this.analysis.visibleObjects() : null;
        const columns = onAnalysis ? this.analysis.hotspotColumns() : null;
        const hotspots = onAnalysis ? this.analysis.visibleHotspots() : null;
        untracked(() => {
          this.engine?.setRelief(onAnalysis ? RELIEF : null);
          this.engine?.setAoi(onAnalysis ? (this.analysis.active()?.globe.bbox ?? null) : null);
          this.engine?.setChannels(onAnalysis ? this.analysis.channels() : null);
          this.engine?.setAnalysis(overlay);
          this.engine?.setObjects(objects as MapObjects | null);
          this.engine?.setColumns(columns as MapObjects | null);
          this.engine?.setHotspots(hotspots);
        });
      }, options),
      effect(() => {
        this.analysis.focusRequest();
        const bbox = this.analysis.active()?.globe.bbox;
        untracked(() => {
          if (bbox && this.scene.route() === 'insights') this.engine?.fitArea(bbox, ANALYSIS_PITCH);
        });
      }, options),
      effect(() => {
        const open = this.scene.panels().layerPanel;
        untracked(() => this.engine?.setPanelOpen(open));
      }, options),
      effect(() => {
        const event = this.scene.state().event;
        const date = this.scene.time().date;
        untracked(() => void this.syncFirePoints(event, date));
      }, options),
      effect(() => {
        const patch = this.scene.lastPatch();
        if (!patch || !patch.ops.some((op) => op.path === '/camera/placeId')) return;
        untracked(() => {
          const placeId = this.scene.camera().placeId;
          if (placeId) this.fitPlace(placeId);
        });
      }, options),
    );
  }

  private toOverlays(layers: ReturnType<SceneStore['layers']>, date: string | null): MapOverlay[] {
    const apiBaseUrl = this.config.value.apiBaseUrl;
    return layers.flatMap((layer): MapOverlay[] => {
      const preset = this.ui.layer(layer.presetId);
      if (!preset || !preset.engines.includes('map')) {
        return [];
      }
      if (preset.kind === 'gamc-wms') {
        const tiles = new URL(
          gamcTileUrl(apiBaseUrl, preset.serviceId),
          document.baseURI,
        ).href.replace('%7Bbbox-epsg-3857%7D', '{bbox-epsg-3857}');
        return [
          {
            presetId: preset.id,
            tiles,
            visible: layer.visible,
            opacity: layer.opacity,
            attribution: preset.attribution,
          },
        ];
      }
      if (preset.kind === 'gibs-wmts') {
        const day = date ?? preset.coverageTo ?? yesterday();
        return [
          {
            presetId: preset.id,
            tiles: preset.url.replace('{Time}', day),
            maxZoom: preset.maxZoom,
            visible: layer.visible,
            opacity: layer.opacity,
            attribution: preset.attribution,
          },
        ];
      }
      return [];
    });
  }

  /** Focos FIRMS del día para eventos que los piden (events.json → points: 'firms'). */
  private async syncFirePoints(
    event: ReturnType<SceneStore['state']>['event'],
    date: string | null,
  ): Promise<void> {
    const preset = event ? this.ui.event(event.type) : undefined;
    if (!event || !date || preset?.points !== 'firms') {
      this.firesKey = '';
      this.fires.set({ status: 'idle' });
      this.engine?.setPoints(null);
      return;
    }
    const key = `${event.placeId}|${date}`;
    if (key === this.firesKey) {
      return;
    }
    this.firesKey = key;
    this.fires.set({ status: 'loading', date });
    const result = await fetchFireDay(this.config.value.apiBaseUrl, event.placeId, date);
    if (key !== this.firesKey) {
      return;
    }
    if (result.ok) {
      this.fires.set({ status: 'ready', date, day: result.day });
      this.engine?.setPoints(result.day.geojson);
    } else {
      this.fires.set({
        status: result.code === 'firms_not_configured' ? 'unavailable' : 'error',
        date,
        message: result.message,
      });
      this.engine?.setPoints(null);
    }
  }

  private async queryFeatureInfo(click: MapClick): Promise<void> {
    const targets = this.scene
      .layers()
      .filter((l) => {
        const preset = this.ui.layer(l.presetId);
        return l.visible && preset?.kind === 'gamc-wms' && preset.featureInfo;
      })
      .flatMap((l) => {
        const preset = this.ui.layer(l.presetId);
        return preset?.kind === 'gamc-wms'
          ? [{ presetId: preset.id, serviceId: preset.serviceId }]
          : [];
      });
    if (targets.length === 0) {
      return;
    }
    this.featureInfo.set({ lon: click.lon, lat: click.lat, loading: true, results: [] });
    const apiBaseUrl = this.config.value.apiBaseUrl;
    const results = await Promise.all(
      targets.map(async (layer): Promise<FeatureInfoResult> => {
        try {
          const preset = this.ui.layer(layer.presetId);
          const allowed = preset?.kind === 'gamc-wms' ? preset.featureInfoFields : undefined;
          const features = (await gamcFeatureInfo(apiBaseUrl, layer.serviceId, click)).map(
            (feature) => ({
              ...feature,
              properties: sanitizeFeatureProperties(feature.properties, allowed),
            }),
          );
          return { presetId: layer.presetId, features };
        } catch (err) {
          return {
            presetId: layer.presetId,
            features: [],
            error: err instanceof Error ? err.message : String(err),
          };
        }
      }),
    );
    this.featureInfo.set({ lon: click.lon, lat: click.lat, loading: false, results });
  }
}

function yesterday(): string {
  return new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
}
