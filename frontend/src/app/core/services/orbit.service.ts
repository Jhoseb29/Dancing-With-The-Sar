import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { Remote, wrap } from 'comlink';
import { bboxCenter } from '../config/runtime-config.model';
import { RuntimeConfigService } from '../config/runtime-config.service';
import { UiConfigService } from '../config/ui-config.service';
import { fetchOrbitElements } from '../data-access/orbit.client';
import { OrbitElements, OrbitPass } from '../data-access/orbit.model';
import { OrbitWorkerApi } from '../workers/orbit.api';

export type OrbitStatus = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Estado orbital de NISAR para toda la app (barra superior y orbit-view).
 * El TLE viene del gateway; los cálculos pesados van al worker orbital.
 */
@Injectable({ providedIn: 'root' })
export class OrbitService {
  private readonly config = inject(RuntimeConfigService);
  private readonly ui = inject(UiConfigService);
  private readonly destroyRef = inject(DestroyRef);

  private worker: Worker | null = null;
  private remote: Remote<OrbitWorkerApi> | null = null;
  private refreshTimer: ReturnType<typeof setTimeout> | null = null;

  readonly status = signal<OrbitStatus>('idle');
  readonly error = signal<string | null>(null);
  readonly elements = signal<OrbitElements | null>(null);
  readonly passes = signal<OrbitPass[]>([]);

  readonly nextPass = computed(() => this.passes()[0] ?? null);

  readonly tleAgeDays = computed(() => {
    const elements = this.elements();
    return elements ? (Date.now() - Date.parse(elements.epoch)) / 86_400_000 : null;
  });

  readonly isTleStale = computed(() => {
    const age = this.tleAgeDays();
    return age !== null && age > this.config.value.orbit.staleTleDays;
  });

  constructor() {
    this.destroyRef.onDestroy(() => {
      if (this.refreshTimer) {
        clearTimeout(this.refreshTimer);
      }
      this.worker?.terminate();
    });
  }

  /** Idempotente: la primera llamada carga el TLE y calcula los pasos. */
  ensureLoaded(): void {
    if (this.status() === 'idle' || this.status() === 'error') {
      void this.load();
    }
  }

  /** Proxy del worker orbital para el motor 3D. */
  computer(): Remote<OrbitWorkerApi> {
    if (!this.remote) {
      this.worker = new Worker(new URL('../workers/orbit.worker', import.meta.url), { type: 'module' });
      this.remote = wrap<OrbitWorkerApi>(this.worker);
    }
    return this.remote;
  }

  private async load(): Promise<void> {
    const cfg = this.config.value;
    this.status.set('loading');
    this.error.set(null);
    try {
      const elements = await fetchOrbitElements(cfg.apiBaseUrl, cfg.orbit.tleCacheHours);
      this.elements.set(elements);
      await this.refreshPasses();
      this.status.set('ready');
    } catch (err) {
      this.status.set('error');
      this.error.set(err instanceof Error ? err.message : String(err));
    }
  }

  private async refreshPasses(): Promise<void> {
    const elements = this.elements();
    if (!elements) {
      return;
    }
    const cfg = this.config.value;
    const place = this.ui.place(cfg.orbit.targetPlaceId);
    if (!place) {
      throw new Error(`runtime-config: targetPlaceId "${cfg.orbit.targetPlaceId}" no existe en places.json`);
    }
    const target = bboxCenter(place.bbox);
    const passes = await this.computer().passes(
      elements.line1,
      elements.line2,
      Date.now(),
      cfg.orbit.passSearchHours,
      target,
      cfg.orbit.passMaxGroundDistanceKm,
    );
    this.passes.set(passes);

    // Recalcular cuando ocurra el próximo paso.
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
    }
    const next = passes[0];
    const delay = next ? Math.max(60_000, next.timeMs - Date.now() + 60_000) : 3_600_000;
    this.refreshTimer = setTimeout(() => void this.refreshPasses(), Math.min(delay, 2_147_000_000));
  }
}
