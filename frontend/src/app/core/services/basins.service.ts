import { Injectable, computed, inject, signal } from '@angular/core';
import { BasinsFC } from '../alerts/basins.model';
import { RuntimeConfigService } from '../config/runtime-config.service';

/** Cuencas torrenciales del Tunari como vectores con datos de terreno (y radar si hay). */
@Injectable({ providedIn: 'root' })
export class BasinsService {
  private readonly apiBaseUrl = inject(RuntimeConfigService).value.apiBaseUrl;
  private loading = false;

  readonly basins = signal<BasinsFC | null>(null);
  readonly selectedId = signal<string | null>(null);
  readonly selected = computed(
    () => this.basins()?.features.find((f) => f.properties.id === this.selectedId())?.properties ?? null,
  );

  /** Carga una sola vez (los datos cambian solo si se reconstruyen en el harness). */
  async load(): Promise<void> {
    if (this.basins() || this.loading) return;
    this.loading = true;
    const r = await fetch(`${this.apiBaseUrl}/alerts/basins`).catch(() => null);
    this.loading = false;
    if (r?.ok) this.basins.set((await r.json()) as BasinsFC);
  }

  select(id: string | null): void {
    this.selectedId.set(this.selectedId() === id ? null : id);
  }
}
