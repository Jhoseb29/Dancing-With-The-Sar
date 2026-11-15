import { EffectRef, Injectable, Injector, effect, inject, signal, untracked } from '@angular/core';
import { DETAIL_IMAGERY } from '../config/detail-imagery';
import { ALERT_HEX, RED_DISTRICTS, Station } from '../alerts/stations.model';
import type { Feature, FeatureCollection, LineString, Point, Polygon } from 'geojson';
import type { RainPayload } from '../alerts/alerts.model';
import type { StrategicTankNode, TankNetworkResponse, TankRole } from '../data-access/tanks.client';
import type { BBox } from '../config/runtime-config.model';
import { RuntimeConfigService } from '../config/runtime-config.service';
import { UiConfigService } from '../config/ui-config.service';
import {
  GamcFeature,
  gamcFeatureInfo,
  gamcTileUrl,
  sanitizeFeatureProperties,
} from '../data-access/gamc-wms.client';
import { FireDay, fetchFireDay } from '../data-access/fires.client';
import { BasinPointDiagnostics, fetchBasinPoint } from '../data-access/basin-risk.client';
import type {
  GeoEngine,
  MapClick,
  MapObjects,
  MapOverlay,
  MapRelief,
  ZoneGroup,
  ZoneOverlay,
} from '../map-engine/geo-engine';
import { SceneStore } from '../scene/scene.store';
import { EventService } from './event.service';
import { AlertsService } from './alerts.service';
import { BasinsService } from './basins.service';
import { StationsService } from './stations.service';
import { TanksService } from './tanks.service';
import { BASIN_TYPE_HEX, LEVEL_HEX, NO_DATA_HEX } from '../alerts/zone-colors';
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
/** En alertas, inclinación suficiente para leer la altura de los bloques de riesgo. */
const RISK_PITCH = 50;
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
  private readonly alerts = inject(AlertsService);
  private readonly stations = inject(StationsService);
  private readonly tanks = inject(TanksService);
  private attachedAt = 0;
  private readonly basins = inject(BasinsService);
  private engine: GeoEngine | null = null;
  private effects: EffectRef[] = [];
  /** Última elección encuadrada por grupo de zonas. */
  private readonly framed = new Map<ZoneGroup, string>();

  readonly view = signal<MapView | null>(null);
  readonly ready = signal(false);
  readonly featureInfo = signal<FeatureInfoState | null>(null);
  readonly pointDem = signal<BasinPointDiagnostics | null>(null);
  readonly pointDemLoading = signal(false);
  readonly terrain3d = signal(false);
  readonly nisarDate = signal<string>('2026-10-25');
  readonly operaDate = signal<string>('2026-11-13');
  readonly imergDate = signal<string>('2026-11-13');
  readonly sarBeforeDate = signal<string>('2026-10-13');
  readonly sarAfterDate = signal<string>('2026-10-25');
  readonly fires = signal<FiresState>({ status: 'idle' });
  private firesKey = '';
  private pendingZoneOverlays: ZoneOverlay[] | null = null;

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
    const route = this.scene.route();
    const fallbackBox = route === 'basin' || route === 'risk' ? basin.bbox : city.bbox;
    const initial = (placeId && placeId !== 'bolivia' ? this.ui.place(placeId)?.bbox : undefined) || fallbackBox;
    const basemap = this.ui.basemap();

    this.engine = new GeoEngine({
      container,
      basemap: { url: basemap.url, maxZoom: basemap.maxZoom, attribution: basemap.attribution },
      detailImagery: DETAIL_IMAGERY,
      initialBBox: initial,
      outlines: { city: city.bbox, basin: basin.bbox },
      apiBaseUrl: this.config.value.apiBaseUrl,
      workerUrl: new URL('maplibre/maplibre-gl-worker.mjs', document.baseURI).href,
      onViewChange: (view) => {
        this.view.set(view);
        this.scene.reportCamera({ lon: view.lon, lat: view.lat, zoom: view.zoom });
      },
      onLayerStatus: (presetId, status) => this.scene.reportLayer(presetId, status),
      onZone: (group, id) => (group === 'districts' ? this.alerts.selectDistrict(id) : this.basins.select(id)),
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
    this.attachedAt = performance.now();
    this.bindScene();
    if (this.pendingZoneOverlays) {
      this.engine.setZoneOutlines(this.pendingZoneOverlays);
    }
  }

  fitPlace(placeId: string): void {
    const place = this.ui.place(placeId);
    if (place) {
      this.engine?.fitArea(place.bbox);
    }
  }

  fitBBox(bbox: BBox): void {
    this.engine?.fitArea(bbox);
  }

  setTerrain3d(enabled: boolean): void {
    this.terrain3d.set(enabled);
  }

  setNisarDate(date: string): void {
    this.nisarDate.set(date);
  }

  setOperaDate(date: string): void {
    this.operaDate.set(date);
  }

  setImergDate(date: string): void {
    this.imergDate.set(date);
  }

  setSarDates(before: string, after: string): void {
    this.sarBeforeDate.set(before);
    this.sarAfterDate.set(after);
  }

  setZoneOverlays(zones: ZoneOverlay[] | null): void {
    this.pendingZoneOverlays = zones;
    this.engine?.setZoneOutlines(zones);
  }

  clearFeatureInfo(): void {
    this.featureInfo.set(null);
    this.pointDem.set(null);
  }

  detach(): void {
    this.effects.forEach((ref) => ref.destroy());
    this.effects = [];
    this.engine?.destroy();
    this.engine = null;
    this.ready.set(false);
    this.featureInfo.set(null);
    this.pointDem.set(null);
    this.pointDemLoading.set(false);
    this.pendingZoneOverlays = null;
    this.firesKey = '';
    this.fires.set({ status: 'idle' });
  }

  private bindScene(): void {
    const options = { injector: this.injector };
    this.effects.push(
      effect(() => {
        // En eventos: capas de events.json; en cuenca/riesgo: capas del shadow (/layers) incluyendo GAMC, DEM y NISAR.
        const route = this.scene.route();
        const event = this.scene.state().event;
        // En el análisis NISAR y en alertas solo se ven sus propios datos (sin imágenes municipales).
        const layers =
          route === 'events' && event
            ? this.events.layersFor(event.type)
            : route === 'insights' || route === 'risk'
              ? []
              : this.scene.layers().filter((l) => {
                  const kind = this.ui.layer(l.presetId)?.kind;
                  return kind === 'gamc-wms' || kind === 'xyz-tile' || kind === 'gibs-wmts';
                });
        const eventDate = route === 'events' ? this.scene.time().date : null;
        const nisar = this.nisarDate();
        const opera = this.operaDate();
        const imerg = this.imergDate();
        const sarBefore = this.sarBeforeDate();
        const sarAfter = this.sarAfterDate();
        untracked(() => {
          const overlays = this.toOverlays(layers, eventDate, route, { nisar, opera, imerg, sarBefore, sarAfter });
          this.scene.pruneReportedLayers(overlays.map((o) => o.presetId));
          this.engine?.setOverlays(overlays);
        });
      }, options),
      // Alertas: distritos en 3D (color = nivel, altura = riesgo); se ocultan en la pestaña Tanques.
      effect(() => {
        const showDistricts = this.scene.route() === 'risk' && !this.tanks.mapActive();
        const districts = showDistricts ? this.alerts.districts() : null;
        const selected = showDistricts ? this.alerts.selectedDistrictId() : null;
        untracked(() => {
          this.engine?.setZones(
            'districts',
            districts && {
              type: 'FeatureCollection',
              features: districts.features.map((f) => ({
                ...f,
                properties: {
                  id: f.properties.id,
                  label: f.properties.id,
                  centro: f.properties.centro,
                  color: RED_DISTRICTS.has(f.properties.id) ? ALERT_HEX.ROJA : '#f0f0fa',
                  height: 0,
                },
              })),
            },
            selected,
          );
          if (!showDistricts) {
            this.framed.delete('districts');
            return;
          }
          this.frameZones('districts', districts?.features.map((f) => f.properties) ?? [], selected);
        });
      }, options),
      // Alertas (sistema HidroGlobe): estaciones con su recuadro, torrenteras y mancha (ocultas en Tanques).
      effect(() => {
        const showStations = this.scene.route() === 'risk' && !this.tanks.mapActive();
        const stations = showStations ? this.stations.filtered() : [];
        untracked(() =>
          this.engine?.setStations(
            stations.length
              ? {
                  type: 'FeatureCollection',
                  features: stations.map((st) => ({
                    type: 'Feature',
                    geometry: { type: 'Point', coordinates: [st.lon, st.lat] },
                    properties: { id: st.id, nombre: st.nombre, color: st.color, popup: stationPopup(st) },
                  })),
                }
              : null,
          ),
        );
      }, options),
      effect(() => {
        const showHazard = this.scene.route() === 'risk' && !this.tanks.mapActive();
        const flood = showHazard ? this.stations.scenario() : null;
        const channels = showHazard ? this.stations.torrenteras() : null;
        const view = this.stations.scenarioView();
        this.stations.scenarioRequest();
        untracked(() => {
          this.engine?.setHazard(flood, channels);
          if (showHazard && flood && view) {
            const wait = Math.max(0, 2500 - (performance.now() - this.attachedAt));
            setTimeout(() => this.engine?.flyToPoint(view.lon, view.lat, view.zoom), wait);
          }
        });
      }, options),
      // Tarjeta de estación tocada en el panel: volar a ella y abrir su recuadro.
      effect(() => {
        const request = this.stations.focusRequest();
        const id = this.stations.focusedId();
        if (request && id) {
          // Recién abierto el mapa, el encuadre inicial de los distritos pisaría el vuelo: esperar.
          const wait = Math.max(0, 2500 - (performance.now() - this.attachedAt));
          untracked(() => setTimeout(() => this.engine?.openStation(id), wait));
        }
      }, options),
      // Alertas: lluvia IMERG como columnas (acumulado 24 h o la media hora elegida).
      effect(() => {
        const onRisk = this.scene.route() === 'risk' && this.alerts.rainVisible();
        const rain = onRisk ? this.alerts.rain() : null;
        const frame = this.alerts.rainFrame();
        untracked(() => this.engine?.setRain(rain ? rainCells(rain, frame) : null));
      }, options),
      // Red estratégica de tanques (sequía + incendios FIRMS) activa en la pestaña Tanques de Alertas.
      effect(() => {
        const active = this.scene.route() === 'risk' && this.tanks.mapActive();
        const net = active ? this.tanks.network() : null;
        const filtered = active ? this.tanks.filteredTanks() : [];
        const selectedId = active ? this.tanks.selectedTankId() : null;
        untracked(() => {
          if (!active || !net) {
            this.engine?.setTankNetwork(null, null, null);
            return;
          }
          const built = buildTankMapLayers(net, filtered, selectedId);
          this.engine?.setTankNetwork(built.tanks, built.links, built.targets, (id) => this.tanks.selectTank(id));
        });
      }, options),
      effect(() => {
        const req = this.tanks.focusRequest();
        const id = this.tanks.selectedTankId();
        const active = this.scene.route() === 'risk' && this.tanks.mapActive();
        if (req && id && active) {
          const wait = Math.max(0, 600 - (performance.now() - this.attachedAt));
          untracked(() => setTimeout(() => this.engine?.openTank(id), wait));
        }
      }, options),
      // Cuenca: cuencas torrenciales como polígonos coloreados por tipo (Melton), con etiqueta.
      effect(() => {
        const onBasin = this.scene.route() === 'basin';
        const basins = onBasin ? this.basins.basins() : null;
        const selected = onBasin ? this.basins.selectedId() : null;
        untracked(() => {
          this.engine?.setZones(
            'basins',
            basins && {
              type: 'FeatureCollection',
              features: basins.features.map((f) => ({
                ...f,
                properties: {
                  id: f.properties.id,
                  label: f.properties.nombre,
                  centro: f.properties.centro,
                  color: BASIN_TYPE_HEX[f.properties.tipo] ?? NO_DATA_HEX,
                },
              })),
            },
            selected,
          );
          if (onBasin) this.frameZones('basins', basins?.features.map((f) => f.properties) ?? [], selected, false);
          else this.framed.delete('basins');
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
          // relieve 3D también bajo los bloques de alerta
          const route = this.scene.route();
          this.engine?.setRelief(onAnalysis || route === 'risk' || route === 'basin' ? RELIEF : null);
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
        const enabled = this.terrain3d();
        const url = tileTemplateUrl(`${this.config.value.apiBaseUrl}/basin/tiles/terrain/{z}/{x}/{y}.png`);
        untracked(() => this.engine?.setTerrainEnabled(enabled, url));
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

  /**
   * Encuadra la zona elegida (inclinada, para ver relieve) o todas las zonas; solo cuando cambia
   * la elección, no en cada actualización de datos.
   */
  private frameZones(group: ZoneGroup, zones: { id: string; bbox: number[] }[], selectedId: string | null, all = true): void {
    const key = selectedId ?? (all ? '*' : '');
    if (!zones.length || this.framed.get(group) === key) return;
    this.framed.set(group, key);
    const pick = zones.find((z) => z.id === selectedId);
    if (pick) {
      this.engine?.fitArea(pick.bbox as BBox, RISK_PITCH);
    } else if (all) {
      const b = zones.map((z) => z.bbox);
      this.engine?.fitArea(
        [
          Math.min(...b.map((x) => x[0])),
          Math.min(...b.map((x) => x[1])),
          Math.max(...b.map((x) => x[2])),
          Math.max(...b.map((x) => x[3])),
        ],
        RISK_PITCH,
      );
    }
  }

  private toOverlays(
    layers: ReturnType<SceneStore['layers']>,
    eventDate: string | null,
    route: ReturnType<SceneStore['route']> = this.scene.route(),
    dates: { nisar: string; opera: string; imerg: string; sarBefore: string; sarAfter: string } = {
      nisar: this.nisarDate(),
      opera: this.operaDate(),
      imerg: this.imergDate(),
      sarBefore: this.sarBeforeDate(),
      sarAfter: this.sarAfterDate(),
    },
  ): MapOverlay[] {
    const apiBaseUrl = this.config.value.apiBaseUrl;
    const scope = route === 'events' ? 'all' : 'basin';
    return layers.flatMap((layer): MapOverlay[] => {
      const preset = this.ui.layer(layer.presetId);
      if (!preset || !preset.engines.includes('map')) {
        return [];
      }
      if (preset.kind === 'gamc-wms') {
        const tiles = tileTemplateUrl(gamcTileUrl(apiBaseUrl, preset.serviceId));
        return [{ presetId: preset.id, tiles, visible: layer.visible, opacity: layer.opacity, attribution: preset.attribution }];
      }
      if (preset.kind === 'gibs-wmts') {
        let day = eventDate ?? preset.coverageTo ?? yesterday();
        if (!eventDate) {
          if (preset.id === 'gibs-nisar-gcov') day = dates.nisar;
          else if (preset.id === 'gibs-opera-dswx-s1') day = dates.opera;
          else if (preset.id === 'gibs-imerg-precip') day = dates.imerg;
        }
        let tiles = preset.url.replace('{Time}', day);
        let maxZoom = preset.maxZoom;
        if (preset.id === 'gibs-opera-dswx-s1') {
          tiles = tileTemplateUrl(`/api/basin/tiles/opera-dswx/${day}/{z}/{x}/{y}.png?scope=${scope}`);
        } else if (scope === 'basin' && preset.id === 'gibs-nisar-gcov') {
          tiles = tileTemplateUrl(`/api/basin/tiles/nisar-basin/${day}/{z}/{x}/{y}.png?scope=basin`);
        } else if (scope === 'basin' && preset.id === 'gibs-imerg-precip') {
          tiles = tileTemplateUrl(`/api/basin/tiles/imerg-basin/${day}/{z}/{x}/{y}.png?scope=basin`);
          maxZoom = 12;
        }
        return [
          {
            presetId: preset.id,
            tiles,
            maxZoom,
            visible: layer.visible,
            opacity: layer.opacity ?? preset.defaultOpacity ?? 0.85,
            attribution: preset.attribution,
          },
        ];
      }
      if (preset.kind === 'xyz-tile') {
        const rawUrl =
          preset.id === 'basin-sar-change'
            ? preset.url.replace('{before}', dates.sarBefore).replace('{after}', dates.sarAfter)
            : preset.url;
        const tiles = tileTemplateUrl(rawUrl);
        return [
          {
            presetId: preset.id,
            tiles,
            maxZoom: preset.maxZoom,
            visible: layer.visible,
            opacity: layer.opacity ?? preset.defaultOpacity ?? 0.8,
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
    const apiBaseUrl = this.config.value.apiBaseUrl;
    const targets = this.scene.layers().filter((l) => {
      const preset = this.ui.layer(l.presetId);
      return l.visible && preset?.kind === 'gamc-wms' && preset.featureInfo;
    }).flatMap((l) => {
      const preset = this.ui.layer(l.presetId);
      return preset?.kind === 'gamc-wms' ? [{ presetId: preset.id, serviceId: preset.serviceId }] : [];
    });

    const route = this.scene.route();
    const askDem = route === 'basin' || route === 'risk';
    if (askDem) {
      this.pointDemLoading.set(true);
      void fetchBasinPoint(apiBaseUrl, click.lon, click.lat)
        .then((diag) => this.pointDem.set(diag))
        .catch(() => this.pointDem.set(null))
        .finally(() => this.pointDemLoading.set(false));
    }

    if (targets.length === 0) {
      if (askDem) {
        this.featureInfo.set({ lon: click.lon, lat: click.lat, loading: false, results: [] });
      }
      return;
    }
    this.featureInfo.set({ lon: click.lon, lat: click.lat, loading: true, results: [] });
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

/** Rampa de DATOS de lluvia (celeste → azul → violeta) sobre 0..1. */
const RAIN_RAMP = ['#9fd3ff', '#3a8dff', '#1f3fd1', '#8a2be2'];

function rainColor(t: number): string {
  return RAIN_RAMP[Math.min(RAIN_RAMP.length - 1, Math.floor(Math.max(0, t) * RAIN_RAMP.length))];
}

/**
 * Celdas IMERG → barras finas (22 % de la celda) con `h` (m) y `c` (color). Escalas distintas:
 * media hora en mm/h (20 mm/h = tope) o acumulado 24 h en mm (60 mm = tope), máx. ~1,2 km de alto.
 */
function rainCells(rain: RainPayload, frame: number | null): FeatureCollection<Polygon, { mm: number; h: number; c: string }> {
  const total = frame === null;
  const grid = total ? rain.acumulado_mm : rain.slots[frame]?.mm_h;
  const top = total ? 60 : 20;
  const half = (rain.celda_grados * 0.22) / 2;
  const features: Feature<Polygon, { mm: number; h: number; c: string }>[] = [];
  rain.lons.forEach((lon, i) =>
    rain.lats.forEach((lat, j) => {
      const mm = grid?.[i]?.[j];
      if (mm === null || mm === undefined || mm < 0.2) return;
      const t = Math.min(1, mm / top);
      features.push({
        type: 'Feature',
        properties: { mm, h: 80 + t * 1200, c: rainColor(t) },
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [lon - half, lat - half],
              [lon + half, lat - half],
              [lon + half, lat + half],
              [lon - half, lat + half],
              [lon - half, lat - half],
            ],
          ],
        },
      });
    }),
  );
  return { type: 'FeatureCollection', features };
}

function yesterday(): string {
  return new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
}

/** HTML del recuadro de una estación (todo el texto se escapa). */
function stationPopup(st: Station): string {
  const esc = (v: unknown) =>
    String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
  const margen =
    st.falta_desborde > 0
      ? `<b>${esc(st.falta_desborde)} m</b>`
      : `<b style="color:${ALERT_HEX.ROJA}">DESBORDADO (${esc(Math.abs(st.falta_desborde))} m)</b>`;
  return `
    <div class="dws-popup-head">
      <strong>${esc(st.nombre)}</strong>
      <span class="dws-popup-tag" style="border-color:${st.color};color:${st.color}">${esc(st.alerta)}</span>
    </div>
    <div><b>Cauce / Río:</b> ${esc(st.rio)}</div>
    <div class="muted">${esc(st.cuenca)} (${esc(st.zona)})</div>
    <div class="dws-popup-box">
      <div>Nivel actual: <b>${esc(st.nivel_actual)} m</b> / Umbral: <b>${esc(st.nivel_roja)} m</b></div>
      <div>Margen desborde: ${margen}</div>
      <div>Prob. GloFAS: <b>${esc(st.glofas_prob_desborde)} %</b> | Lluvia 24 h: <b>${esc(st.precipitacion_24h)} mm</b></div>
      <div>Humedad del suelo: <b>${esc(st.humedad_suelo_pct)} %</b></div>
    </div>
    <div class="muted"><b>Tendencia GAMC:</b> ${esc(st.tendencia)}</div>
  `;
}

/** Resuelve URL relativa contra baseURI preservando marcadores de tesela sin codificar. */
function tileTemplateUrl(path: string): string {
  return new URL(path, document.baseURI).href.replace(/%7B(z|x|y|bbox-epsg-3857)%7D/gi, '{$1}');
}

const TANK_ROLE_COLOR: Record<TankRole, string> = {
  dual: '#38bdf8',
  drought: '#eab308',
  fire: '#fb7185',
};

function escHtml(v: unknown): string {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
}

function tankPopup(t: StrategicTankNode): string {
  const dr = t.nearby_drought_targets[0];
  const fr = t.nearby_fire_targets[0];
  const color = TANK_ROLE_COLOR[t.role];
  const drLine = dr
    ? `<div>Sequía cercana: <b>${escHtml(dr.name_es)}</b> (${dr.distance_km} km · Δ${dr.elevation_diff_m} m)</div>`
    : '';
  const frLine = fr
    ? `<div>Incendios FIRMS: <b>${escHtml(fr.zone_label)}</b> (${fr.distance_km} km · ${fr.hotspots_count} focos)</div>`
    : '';
  return `
    <div class="dws-popup-head">
      <strong>${escHtml(t.id)} · ${escHtml(t.name_es)}</strong>
      <span class="dws-popup-tag" style="border-color:${color};color:${color}">${escHtml(t.role.toUpperCase())}</span>
    </div>
    <div class="muted">${escHtml(t.subbasin_name_es)} · ${t.elevation_m} m s.n.m. (${t.slope_deg}°)</div>
    <div class="dws-popup-box">
      <div>Reserva propuesta: <b>${t.recommended_capacity_m3} m³</b> · Cosecha 30 d: <b>${t.harvest_30d_m3} m³</b></div>
      <div>Lluvia 30 d: <b>${t.rain_30d_mm} mm</b> · Días secos (60 d): <b>${t.dry_days_60d}</b></div>
      ${drLine}
      ${frLine}
    </div>
  `;
}

function buildTankMapLayers(
  net: TankNetworkResponse,
  filtered: StrategicTankNode[],
  selectedId: string | null,
): {
  tanks: FeatureCollection<Point, { id: string; label: string; color: string; selected: boolean; popup: string }>;
  links: FeatureCollection<LineString, { tankId: string; kind: 'drought' | 'fire'; selected: boolean }>;
  targets: FeatureCollection<Point, { id: string; label: string; kind: 'drought' | 'fire'; radius: number }>;
} {
  const linkFeatures: Feature<LineString, { tankId: string; kind: 'drought' | 'fire'; selected: boolean }>[] = [];
  const tankFeatures: Feature<Point, { id: string; label: string; color: string; selected: boolean; popup: string }>[] = [];

  for (const t of filtered) {
    const selected = t.id === selectedId;
    tankFeatures.push({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [t.lon, t.lat] },
      properties: {
        id: t.id,
        label: `${t.id} · ${t.recommended_capacity_m3} m³`,
        color: TANK_ROLE_COLOR[t.role],
        selected,
        popup: tankPopup(t),
      },
    });
    for (const dt of t.nearby_drought_targets) {
      linkFeatures.push({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: [[t.lon, t.lat], [dt.lon, dt.lat]] },
        properties: { tankId: t.id, kind: 'drought', selected },
      });
    }
    for (const ft of t.nearby_fire_targets) {
      linkFeatures.push({
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: [[t.lon, t.lat], [ft.lon, ft.lat]] },
        properties: { tankId: t.id, kind: 'fire', selected },
      });
    }
  }

  const targetFeatures: Feature<Point, { id: string; label: string; kind: 'drought' | 'fire'; radius: number }>[] = [
    ...net.drought_targets.map((dt) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [dt.lon, dt.lat] as [number, number] },
      properties: { id: dt.id, label: `Sequía · ${dt.id}`, kind: 'drought' as const, radius: 6 },
    })),
    ...net.fire_clusters.map((fc) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [fc.lon, fc.lat] as [number, number] },
      properties: {
        id: fc.id,
        label: `${fc.hotspots_count} focos`,
        kind: 'fire' as const,
        radius: Math.min(11, 5 + Math.round(fc.hotspots_count / 6)),
      },
    })),
  ];

  return {
    tanks: { type: 'FeatureCollection', features: tankFeatures },
    links: { type: 'FeatureCollection', features: linkFeatures },
    targets: { type: 'FeatureCollection', features: targetFeatures },
  };
}
