// Motor 3D (CesiumJS). TypeScript puro: no importa @angular/*.
// Se carga solo desde orbit-view mediante import() dinámico.
import {
  ArcType,
  CallbackPositionProperty,
  CallbackProperty,
  Cartesian2,
  Cartesian3,
  Color,
  CesiumWidget,
  ClockStep,
  Entity,
  ImageryLayer,
  JulianDate,
  LabelStyle,
  Rectangle,
  UrlTemplateImageryProvider,
  VerticalOrigin,
  WebMercatorTilingScheme,
} from 'cesium';
import { eciToEcf, gstime, propagate, twoline2satrec, SatRec } from 'satellite.js';
import type { Remote } from 'comlink';
import type { BBox } from '../config/runtime-config.model';
import type { EciSample, GeoSample, OrbitElements } from '../data-access/orbit.model';
import type { OrbitWorkerApi } from '../workers/orbit.api';

export interface SatelliteReadout {
  timeMs: number;
  lonDeg: number;
  latDeg: number;
  altitudeKm: number;
  speedKmS: number;
}

export interface GlobeEngineLabels {
  satellite: string;
  area: string;
}

export interface BasemapConfig {
  url: string;
  maxZoom: number;
  attribution?: string;
}

/** Paso de recorrido ya resuelto (bbox o punto). */
export type ResolvedTourStep =
  | { bbox: BBox; durationMs: number; pauseMs: number }
  | { lon: number; lat: number; altKm: number; durationMs: number; pauseMs: number };

export interface GlobeEngineOptions {
  container: HTMLElement;
  basemap: BasemapConfig;
  area: BBox;
  orbit: Remote<OrbitWorkerApi>;
  swathKm: number;
  labels: GlobeEngineLabels;
  onReadout: (readout: SatelliteReadout) => void;
  /** Cámara real tras cada movimiento. */
  onCamera: (camera: { lon: number; lat: number; altKm: number }) => void;
  /** El usuario tocó el globo (cancela recorridos). */
  onUserInteract: () => void;
}

const FONT = '700 12px Barlow, sans-serif';
const TRACK_REFRESH_SIM_MS = 5 * 60_000;
const SWATH_MINUTES = 25;

export class GlobeEngine {
  private readonly widget: CesiumWidget;
  private satrec: SatRec | null = null;
  private elements: OrbitElements | null = null;
  private ring: EciSample[] = [];
  private trackCenterMs = 0;
  private lastReadoutMs = 0;
  private refreshing = false;
  private destroyed = false;

  private readonly satelliteEntity: Entity;
  private readonly ringEntity: Entity;
  private readonly pastTrackEntity: Entity;
  private readonly futureTrackEntity: Entity;
  private readonly swathEntity: Entity;
  private pastTrack: Cartesian3[] = [];
  private futureTrack: Cartesian3[] = [];
  private swath: Cartesian3[] = [];
  private readonly removeTick: () => void;
  private readonly removeMoveEnd: () => void;
  private readonly interactionEvents = ['pointerdown', 'wheel', 'touchstart'] as const;
  private readonly onInteract = () => this.options.onUserInteract();
  private tourToken = 0;

  constructor(private readonly options: GlobeEngineOptions) {
    const { container, basemap } = options;

    this.widget = new CesiumWidget(container, {
      baseLayer: new ImageryLayer(
        new UrlTemplateImageryProvider({
          url: basemap.url,
          maximumLevel: basemap.maxZoom,
          tilingScheme: new WebMercatorTilingScheme(),
          credit: basemap.attribution,
        }),
      ),
      shouldAnimate: true,
    });

    const { scene, clock } = this.widget;
    scene.backgroundColor = Color.BLACK;
    scene.globe.baseColor = Color.BLACK;
    scene.globe.enableLighting = true;
    clock.currentTime = JulianDate.now();
    clock.clockStep = ClockStep.SYSTEM_CLOCK_MULTIPLIER;
    clock.multiplier = 1;
    clock.shouldAnimate = true;

    this.addArea();

    this.ringEntity = this.widget.entities.add({
      polyline: {
        positions: new CallbackProperty(() => this.ringInFixedFrame(), false),
        width: 1.5,
        arcType: ArcType.NONE,
        material: Color.fromCssColorString('#f0f0fa').withAlpha(0.55),
      },
    });

    this.pastTrackEntity = this.widget.entities.add({
      polyline: {
        positions: new CallbackProperty(() => this.pastTrack, false),
        width: 1,
        arcType: ArcType.GEODESIC,
        material: Color.fromCssColorString('#9a9aa3').withAlpha(0.45),
      },
    });

    this.futureTrackEntity = this.widget.entities.add({
      polyline: {
        positions: new CallbackProperty(() => this.futureTrack, false),
        width: 1.5,
        arcType: ArcType.GEODESIC,
        material: Color.fromCssColorString('#f0f0fa').withAlpha(0.8),
      },
    });

    this.swathEntity = this.widget.entities.add({
      corridor: {
        positions: new CallbackProperty(() => this.swath, false),
        width: options.swathKm * 1000,
        material: Color.fromCssColorString('#f0f0fa').withAlpha(0.08),
      },
    });

    this.satelliteEntity = this.widget.entities.add({
      position: new CallbackPositionProperty((time, result) => this.satellitePosition(time, result), false),
      point: {
        pixelSize: 9,
        color: Color.fromCssColorString('#f0f0fa'),
        outlineColor: Color.BLACK,
        outlineWidth: 2,
      },
      label: {
        text: options.labels.satellite,
        font: FONT,
        fillColor: Color.fromCssColorString('#f0f0fa'),
        outlineColor: Color.BLACK,
        outlineWidth: 3,
        style: LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: VerticalOrigin.BOTTOM,
        pixelOffset: new Cartesian2(0, -14),
      },
    });

    this.removeTick = clock.onTick.addEventListener(() => this.onTick());
    this.removeMoveEnd = scene.camera.moveEnd.addEventListener(() => {
      const carto = scene.camera.positionCartographic;
      options.onCamera({
        lon: (carto.longitude * 180) / Math.PI,
        lat: (carto.latitude * 180) / Math.PI,
        altKm: carto.height / 1000,
      });
    });
    for (const type of this.interactionEvents) {
      scene.canvas.addEventListener(type, this.onInteract, { passive: true });
    }

    const [minLon, minLat, maxLon, maxLat] = options.area;
    scene.camera.setView({
      destination: Cartesian3.fromDegrees((minLon + maxLon) / 2, (minLat + maxLat) / 2, 22_000_000),
    });
  }

  async setOrbitElements(elements: OrbitElements): Promise<void> {
    this.elements = elements;
    this.satrec = twoline2satrec(elements.line1, elements.line2);
    await this.refreshTracks(this.simTimeMs());
  }

  setClockMultiplier(multiplier: number): void {
    this.widget.clock.multiplier = multiplier;
  }

  resetToNow(): void {
    this.widget.clock.currentTime = JulianDate.now();
    this.widget.clock.multiplier = 1;
    void this.refreshTracks(this.simTimeMs());
  }

  followSatellite(follow: boolean): void {
    this.widget.trackedEntity = follow ? this.satelliteEntity : undefined;
  }

  flyToArea(onComplete?: () => void): void {
    this.widget.trackedEntity = undefined;
    const [minLon, minLat, maxLon, maxLat] = this.options.area;
    this.widget.camera.flyTo({
      destination: Rectangle.fromDegrees(minLon - 0.6, minLat - 0.6, maxLon + 0.6, maxLat + 0.6),
      duration: 3,
      complete: onComplete,
    });
  }

  flyToBBox(bbox: BBox, durationMs = 2500): Promise<void> {
    this.widget.trackedEntity = undefined;
    const [minLon, minLat, maxLon, maxLat] = bbox;
    return new Promise((resolve) => {
      this.widget.camera.flyTo({
        destination: Rectangle.fromDegrees(minLon, minLat, maxLon, maxLat),
        duration: durationMs / 1000,
        complete: () => resolve(),
        cancel: () => resolve(),
      });
    });
  }

  flyToPoint(lon: number, lat: number, altKm: number, durationMs = 2500): Promise<void> {
    this.widget.trackedEntity = undefined;
    return new Promise((resolve) => {
      this.widget.camera.flyTo({
        destination: Cartesian3.fromDegrees(lon, lat, altKm * 1000),
        duration: durationMs / 1000,
        complete: () => resolve(),
        cancel: () => resolve(),
      });
    });
  }

  /** Ejecuta un recorrido. Devuelve false si se canceló. */
  async runTour(steps: ResolvedTourStep[], onStep: (index: number) => void): Promise<boolean> {
    const token = ++this.tourToken;
    for (let i = 0; i < steps.length; i++) {
      if (token !== this.tourToken || this.destroyed) {
        return false;
      }
      onStep(i);
      const step = steps[i];
      if ('bbox' in step) {
        await this.flyToBBox(step.bbox, step.durationMs);
      } else {
        await this.flyToPoint(step.lon, step.lat, step.altKm, step.durationMs);
      }
      if (step.pauseMs > 0) {
        await new Promise((r) => setTimeout(r, step.pauseMs));
      }
    }
    return token === this.tourToken && !this.destroyed;
  }

  cancelTour(): void {
    this.tourToken++;
    this.widget.camera.cancelFlight();
  }

  flyHome(): void {
    this.widget.trackedEntity = undefined;
    const [minLon, minLat, maxLon, maxLat] = this.options.area;
    this.widget.camera.flyTo({
      destination: Cartesian3.fromDegrees((minLon + maxLon) / 2, (minLat + maxLat) / 2, 22_000_000),
      duration: 2,
    });
  }

  destroy(): void {
    if (this.destroyed) {
      return;
    }
    this.destroyed = true;
    this.tourToken++;
    this.removeTick();
    this.removeMoveEnd();
    for (const type of this.interactionEvents) {
      this.widget.scene.canvas.removeEventListener(type, this.onInteract);
    }
    this.widget.destroy();
  }

  private simTimeMs(): number {
    return JulianDate.toDate(this.widget.clock.currentTime).getTime();
  }

  private satellitePosition(time: JulianDate | undefined, result?: Cartesian3): Cartesian3 | undefined {
    if (!this.satrec) {
      return undefined;
    }
    const date = time ? JulianDate.toDate(time) : new Date();
    const state = propagate(this.satrec, date);
    if (!state) {
      return undefined;
    }
    const ecf = eciToEcf(state.position, gstime(date));
    return Cartesian3.fromElements(ecf.x * 1000, ecf.y * 1000, ecf.z * 1000, result);
  }

  /** El anillo orbital es fijo en el espacio inercial; se rota con el GMST del instante actual. */
  private ringInFixedFrame(): Cartesian3[] {
    if (this.ring.length === 0) {
      return [];
    }
    const g = gstime(JulianDate.toDate(this.widget.clock.currentTime));
    const cos = Math.cos(g);
    const sin = Math.sin(g);
    return this.ring.map(([x, y, z]) => new Cartesian3((x * cos + y * sin) * 1000, (-x * sin + y * cos) * 1000, z * 1000));
  }

  private onTick(): void {
    if (!this.satrec || this.destroyed) {
      return;
    }
    const simMs = this.simTimeMs();

    if (Math.abs(simMs - this.trackCenterMs) > TRACK_REFRESH_SIM_MS) {
      void this.refreshTracks(simMs);
    }

    const realNow = performance.now();
    if (realNow - this.lastReadoutMs < 1000) {
      return;
    }
    this.lastReadoutMs = realNow;
    const date = new Date(simMs);
    const state = propagate(this.satrec, date);
    if (!state) {
      return;
    }
    const position = this.satellitePosition(this.widget.clock.currentTime);
    if (!position) {
      return;
    }
    const carto = this.widget.scene.globe.ellipsoid.cartesianToCartographic(position);
    const { x, y, z } = state.velocity;
    this.options.onReadout({
      timeMs: simMs,
      lonDeg: (carto.longitude * 180) / Math.PI,
      latDeg: (carto.latitude * 180) / Math.PI,
      altitudeKm: carto.height / 1000,
      speedKmS: Math.sqrt(x * x + y * y + z * z),
    });
  }

  private async refreshTracks(centerMs: number): Promise<void> {
    if (!this.elements || this.refreshing) {
      return;
    }
    this.refreshing = true;
    this.trackCenterMs = centerMs;
    try {
      const { line1, line2 } = this.elements;
      const orbit = this.options.orbit;
      const periodMs = (await orbit.periodMinutes(line1, line2)) * 60_000;
      const [ring, past, future, swath] = await Promise.all([
        orbit.orbitRing(line1, line2, centerMs, 240),
        orbit.groundTrack(line1, line2, centerMs - periodMs, centerMs, 30),
        orbit.groundTrack(line1, line2, centerMs, centerMs + periodMs, 30),
        orbit.groundTrack(line1, line2, centerMs, centerMs + SWATH_MINUTES * 60_000, 30),
      ]);
      if (this.destroyed) {
        return;
      }
      this.ring = ring;
      this.pastTrack = toCartesians(past);
      this.futureTrack = toCartesians(future);
      this.swath = toCartesians(swath);
    } finally {
      this.refreshing = false;
    }
  }

  private addArea(): void {
    const [minLon, minLat, maxLon, maxLat] = this.options.area;
    this.widget.entities.add({
      rectangle: {
        coordinates: Rectangle.fromDegrees(minLon, minLat, maxLon, maxLat),
        material: Color.fromCssColorString('#f0f0fa').withAlpha(0.12),
        outline: true,
        outlineColor: Color.fromCssColorString('#f0f0fa'),
        height: 0,
      },
    });
    this.widget.entities.add({
      position: Cartesian3.fromDegrees((minLon + maxLon) / 2, maxLat),
      label: {
        text: this.options.labels.area,
        font: FONT,
        fillColor: Color.fromCssColorString('#f0f0fa'),
        outlineColor: Color.BLACK,
        outlineWidth: 3,
        style: LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: VerticalOrigin.BOTTOM,
        pixelOffset: new Cartesian2(0, -6),
      },
    });
  }
}

function toCartesians(samples: GeoSample[]): Cartesian3[] {
  return samples.map(([lon, lat]) => Cartesian3.fromDegrees(lon, lat, 0));
}
