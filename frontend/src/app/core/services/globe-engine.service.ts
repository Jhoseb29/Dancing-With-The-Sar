import { Injectable, Injector, effect, inject, signal, untracked, EffectRef } from '@angular/core';
import { RuntimeConfigService } from '../config/runtime-config.service';
import { UiConfigService } from '../config/ui-config.service';
import type { GlobeEngine, GlobeEngineLabels, ResolvedTourStep, SatelliteReadout } from '../globe-engine/globe-engine';
import { OrbitElements } from '../data-access/orbit.model';
import { SceneStore } from '../scene/scene.store';
import { ensureStylesheet } from './lazy-stylesheet';
import { OrbitService } from './orbit.service';

declare global {
  interface Window {
    CESIUM_BASE_URL?: string;
  }
}

/**
 * Adaptador Angular ↔ motor 3D. Carga Cesium con import() dinámico y obedece al
 * shadow: velocidad (/time/speed), seguimiento (/camera/follow), lugar
 * (/camera/placeId) y recorridos (/camera/tourId). Reporta la cámara real.
 */
@Injectable({ providedIn: 'root' })
export class GlobeEngineService {
  private readonly config = inject(RuntimeConfigService);
  private readonly ui = inject(UiConfigService);
  private readonly orbit = inject(OrbitService);
  private readonly scene = inject(SceneStore);
  private readonly injector = inject(Injector);
  private engine: GlobeEngine | null = null;
  private effects: EffectRef[] = [];

  readonly readout = signal<SatelliteReadout | null>(null);
  readonly ready = signal(false);

  async attach(container: HTMLElement, labels: GlobeEngineLabels): Promise<void> {
    this.detach();
    window.CESIUM_BASE_URL = new URL('cesium/', document.baseURI).href;
    ensureStylesheet('cesium/Widgets/CesiumWidget/CesiumWidget.css');

    const { GlobeEngine } = await import('../globe-engine/globe-engine');
    const cfg = this.config.value;
    const target = this.ui.place(cfg.orbit.targetPlaceId);
    if (!target) {
      throw new Error(`targetPlaceId "${cfg.orbit.targetPlaceId}" no existe en places.json`);
    }
    const basemap = this.ui.basemap();

    this.engine = new GlobeEngine({
      container,
      basemap: { url: basemap.url, maxZoom: basemap.maxZoom, attribution: basemap.attribution },
      area: target.bbox,
      orbit: this.orbit.computer(),
      swathKm: cfg.orbit.illustrativeSwathKm,
      labels,
      onReadout: (value) => this.readout.set(value),
      onCamera: (camera) => this.scene.reportCamera(camera),
      onUserInteract: () => this.onUserInteract(),
    });
    this.ready.set(true);
    this.bindScene();
  }

  async setOrbitElements(elements: OrbitElements): Promise<void> {
    await this.engine?.setOrbitElements(elements);
  }

  resetToNow(): void {
    this.engine?.resetToNow();
  }

  flyHome(): void {
    this.engine?.flyHome();
  }

  flyToArea(onComplete?: () => void): void {
    this.engine?.flyToArea(onComplete);
  }

  detach(): void {
    this.effects.forEach((ref) => ref.destroy());
    this.effects = [];
    this.engine?.destroy();
    this.engine = null;
    this.ready.set(false);
    this.readout.set(null);
    this.scene.reportTourStep(null);
  }

  private bindScene(): void {
    const options = { injector: this.injector };

    this.effects.push(
      effect(() => {
        const speed = this.scene.time().speed;
        untracked(() => this.engine?.setClockMultiplier(speed));
      }, options),
      effect(() => {
        const follow = this.scene.camera().follow;
        untracked(() => this.engine?.followSatellite(follow));
      }, options),
      // Comandos: cada parche que toca lugar o recorrido se ejecuta, aunque repita el valor.
      effect(() => {
        const patch = this.scene.lastPatch();
        if (!patch) return;
        untracked(() => {
          const camera = this.scene.camera();
          if (patch.ops.some((op) => op.path === '/camera/tourId') && camera.tourId) {
            void this.runTour(camera.tourId);
          } else if (patch.ops.some((op) => op.path === '/camera/placeId') && camera.placeId) {
            this.flyToPlace(camera.placeId);
          }
        });
      }, options),
    );

    // Estado inicial (p. ej. al abrir un enlace con ?place=…).
    const camera = this.scene.camera();
    if (camera.tourId) {
      void this.runTour(camera.tourId);
    } else if (camera.placeId) {
      this.flyToPlace(camera.placeId);
    }
  }

  private flyToPlace(placeId: string): void {
    const place = this.ui.place(placeId);
    if (place && this.engine) {
      this.engine.cancelTour();
      void this.engine.flyToBBox(place.bbox);
    }
  }

  private async runTour(tourId: string): Promise<void> {
    const tour = this.ui.tour(tourId);
    if (!tour || tour.engine !== 'globe' || !this.engine) {
      return;
    }
    const steps: ResolvedTourStep[] = tour.steps.flatMap((step): ResolvedTourStep[] => {
      const pauseMs = step.pauseMs ?? 0;
      if (step.placeId) {
        const place = this.ui.place(step.placeId);
        return place ? [{ bbox: place.bbox, durationMs: step.durationMs, pauseMs }] : [];
      }
      if (step.lon !== undefined && step.lat !== undefined) {
        return [{ lon: step.lon, lat: step.lat, altKm: step.altKm ?? 20000, durationMs: step.durationMs, pauseMs }];
      }
      return [];
    });
    const finished = await this.engine.runTour(steps, (index) => this.scene.reportTourStep(index));
    this.scene.reportTourStep(null);
    if (finished && this.scene.camera().tourId === tourId) {
      await this.scene.set('/camera/tourId', null);
    }
  }

  private onUserInteract(): void {
    if (this.scene.camera().tourId) {
      this.engine?.cancelTour();
      void this.scene.set('/camera/tourId', null);
    }
  }
}
