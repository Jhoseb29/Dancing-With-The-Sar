import { Injectable, computed, inject, signal } from '@angular/core';
import { RuntimeConfigService } from '../config/runtime-config.service';
import {
  TankNetworkResponse,
  TankRole,
  analyzeTankNetwork,
  fetchTankNetwork,
} from '../data-access/tanks.client';

export type TankFilter = 'all' | TankRole;

/**
 * Red estratégica de tanques de cosecha de lluvia: estado compartido entre el panel
 * de Alertas (`/riesgo`) y el motor cartográfico 3D MapLibre.
 */
@Injectable({ providedIn: 'root' })
export class TanksService {
  private readonly apiBaseUrl = inject(RuntimeConfigService).value.apiBaseUrl;
  private loadingPromise: Promise<void> | null = null;

  readonly network = signal<TankNetworkResponse | null>(null);
  readonly loading = signal(false);
  readonly analyzing = signal(false);
  readonly error = signal<string | null>(null);
  readonly roleFilter = signal<TankFilter>('all');
  readonly selectedTankId = signal<string | null>(null);
  /** Sincroniza nodos y enlaces de sequía/incendios sobre el mapa en `/riesgo`. */
  readonly mapActive = signal(false);
  readonly focusRequest = signal(0);

  readonly filteredTanks = computed(() => {
    const net = this.network();
    if (!net) return [];
    const role = this.roleFilter();
    return role === 'all' ? net.tanks : net.tanks.filter((t) => t.role === role);
  });

  readonly selectedTank = computed(() => {
    const net = this.network();
    const id = this.selectedTankId();
    if (!net || !id) return null;
    return net.tanks.find((t) => t.id === id) ?? null;
  });

  load(refresh = false): Promise<void> {
    if (!refresh && this.network()) return Promise.resolve();
    if (!refresh && this.loadingPromise) return this.loadingPromise;
    this.loading.set(true);
    this.error.set(null);
    const p = fetchTankNetwork(this.apiBaseUrl, refresh)
      .then((res) => {
        this.network.set(res);
        if (!this.selectedTankId() && res.tanks.length > 0) {
          this.selectedTankId.set(res.tanks[0].id);
        }
      })
      .catch((err: unknown) => {
        this.error.set(err instanceof Error ? err.message : 'Error cargando red de tanques');
      })
      .finally(() => {
        this.loading.set(false);
        this.loadingPromise = null;
      });
    this.loadingPromise = p;
    return p;
  }

  selectTank(id: string | null): void {
    const next = this.selectedTankId() === id ? null : id;
    this.selectedTankId.set(next);
    if (next) {
      this.focusRequest.update((n) => n + 1);
    }
  }

  async runAnalysis(focus: string | null, lang: 'es' | 'en'): Promise<void> {
    if (this.analyzing()) return;
    this.analyzing.set(true);
    this.error.set(null);
    try {
      const res = await analyzeTankNetwork(this.apiBaseUrl, focus, lang);
      this.network.set(res);
      if (res.tanks.length > 0 && !this.selectedTankId()) {
        this.selectedTankId.set(res.tanks[0].id);
      }
    } catch (err: unknown) {
      this.error.set(err instanceof Error ? err.message : 'Error analizando red');
    } finally {
      this.analyzing.set(false);
    }
  }
}
