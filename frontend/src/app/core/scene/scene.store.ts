import { Injectable, computed, inject, signal } from '@angular/core';
import { UiConfigService } from '../config/ui-config.service';
import { applyOps } from './json-patch';
import {
  AppliedPatch,
  LayerState,
  LayerStatus,
  PatchOp,
  PatchOrigin,
  PatchResult,
  ReportedState,
  SceneState,
  ScenePatch,
  initialScene,
} from './scene.model';

const HISTORY_LIMIT = 50;

/**
 * Shadow de la UI: estado deseado (SceneState) + estado reportado.
 * Toda modificación entra por `patch()`; nadie muta el estado directamente.
 */
@Injectable({ providedIn: 'root' })
export class SceneStore {
  private readonly config = inject(UiConfigService);

  private readonly _state = signal<SceneState>(initialScene());
  private readonly _reported = signal<ReportedState>({
    route: null,
    camera: null,
    layers: {},
    tourStep: null,
  });
  private readonly _lastPatch = signal<AppliedPatch | null>(null);
  private readonly history: AppliedPatch[] = [];

  readonly state = this._state.asReadonly();
  readonly reported = this._reported.asReadonly();
  /** Último parche aplicado: los adaptadores lo usan para ejecutar comandos (volar, recorridos). */
  readonly lastPatch = this._lastPatch.asReadonly();

  readonly route = computed(() => this._state().route);
  readonly lang = computed(() => this._state().lang);
  readonly camera = computed(() => this._state().camera);
  readonly time = computed(() => this._state().time);
  readonly layers = computed(() => this._state().layers);
  readonly search = computed(() => this._state().search);
  readonly panels = computed(() => this._state().panels);

  /** Aplica un parche (usuario o URL). */
  async patch(patch: ScenePatch): Promise<PatchResult> {
    const current = this._state();

    let next: SceneState;
    try {
      next = applyOps(current, patch.ops);
    } catch (err) {
      return { ok: false, reason: err instanceof Error ? err.message : String(err) };
    }

    const version = current.version + 1;
    this._state.set({ ...next, version });
    const applied: AppliedPatch = { version, origin: patch.origin, ops: patch.ops };
    this.history.push(applied);
    if (this.history.length > HISTORY_LIMIT) {
      this.history.shift();
    }
    this._lastPatch.set(applied);
    return { ok: true, version };
  }

  /** Atajo para código tipado de la UI (origen `user`). */
  set(path: string, value: unknown, origin: PatchOrigin = 'user'): Promise<PatchResult> {
    return this.patch({ origin, ops: [{ op: 'replace', path, value }] });
  }

  /** Activa/desactiva una capa (agrega la entrada si no existe). */
  toggleLayer(
    presetId: string,
    visible: boolean,
    origin: PatchOrigin = 'user',
  ): Promise<PatchResult> {
    const index = this._state().layers.findIndex((l) => l.presetId === presetId);
    if (index >= 0) {
      return this.patch({
        origin,
        ops: [{ op: 'replace', path: `/layers/${index}/visible`, value: visible }],
      });
    }
    const preset = this.config.layer(presetId);
    const opacity = preset && preset.kind === 'gamc-wms' ? preset.defaultOpacity : 1;
    const entry: LayerState = { presetId, visible, opacity };
    return this.patch({ origin, ops: [{ op: 'add', path: '/layers/-', value: entry }] });
  }

  /** Reemplaza todas las capas (p. ej. desde la URL). */
  replaceLayers(layers: LayerState[], origin: PatchOrigin): Promise<PatchResult> {
    return this.patch({ origin, ops: [{ op: 'replace', path: '/layers', value: layers }] });
  }

  reportRoute(route: ReportedState['route']): void {
    this._reported.update((r) => ({ ...r, route }));
  }

  reportCamera(camera: ReportedState['camera']): void {
    this._reported.update((r) => ({ ...r, camera }));
  }

  /** Quita del estado reportado las capas que el motor ya no dibuja. */
  pruneReportedLayers(keep: readonly string[]): void {
    this._reported.update((r) => {
      const stale = Object.keys(r.layers).filter((id) => !keep.includes(id));
      if (stale.length === 0) return r;
      const layers = { ...r.layers };
      stale.forEach((id) => delete layers[id]);
      return { ...r, layers };
    });
  }

  reportLayer(presetId: string, status: LayerStatus): void {
    this._reported.update((r) =>
      r.layers[presetId] === status ? r : { ...r, layers: { ...r.layers, [presetId]: status } },
    );
  }

  reportTourStep(step: number | null): void {
    this._reported.update((r) => ({ ...r, tourStep: step }));
  }

  recentPatches(): readonly AppliedPatch[] {
    return this.history;
  }
}

export type { PatchOp };
