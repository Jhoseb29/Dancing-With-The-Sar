import { Injectable, computed, inject, signal } from '@angular/core';
import { UiConfigService } from '../config/ui-config.service';
import { applyOps, pathsOverlap } from './json-patch';
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
import { validateSceneForAgent } from './scene-validator';

const HISTORY_LIMIT = 50;

/**
 * Shadow de la UI: estado deseado (SceneState) + estado reportado.
 * Toda modificación entra por `patch()`; nadie muta el estado directamente.
 */
@Injectable({ providedIn: 'root' })
export class SceneStore {
  private readonly config = inject(UiConfigService);

  private readonly _state = signal<SceneState>(initialScene());
  private readonly _reported = signal<ReportedState>({ route: null, camera: null, layers: {}, tourStep: null });
  private readonly _lastPatch = signal<AppliedPatch | null>(null);
  /** Última versión en la que el usuario (o la URL) cambió cada ruta. */
  private readonly userTouched = new Map<string, number>();
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

  /** Aplica un parche. Los de origen `agent` se validan contra el schema y la configuración. */
  async patch(patch: ScenePatch): Promise<PatchResult> {
    const current = this._state();

    if (patch.origin === 'agent' && patch.baseVersion !== undefined && patch.baseVersion < current.version) {
      const conflict = patch.ops.find((op) =>
        [...this.userTouched.entries()].some(([path, v]) => v > (patch.baseVersion as number) && pathsOverlap(path, op.path)),
      );
      if (conflict) {
        return { ok: false, reason: `Conflicto: el usuario cambió ${conflict.path} después de la versión ${patch.baseVersion}` };
      }
    }

    let next: SceneState;
    try {
      next = applyOps(current, patch.ops);
    } catch (err) {
      return { ok: false, reason: err instanceof Error ? err.message : String(err) };
    }

    if (patch.origin === 'agent') {
      const error = await validateSceneForAgent(next, this.config.value);
      if (error) {
        return { ok: false, reason: error };
      }
      if (this._state() !== current) {
        return { ok: false, reason: 'El estado cambió mientras se validaba; reintentar con la versión nueva' };
      }
    }

    const version = current.version + 1;
    this._state.set({ ...next, version });
    if (patch.origin !== 'agent') {
      patch.ops.forEach((op) => this.userTouched.set(op.path, version));
    }
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
  toggleLayer(presetId: string, visible: boolean, origin: PatchOrigin = 'user'): Promise<PatchResult> {
    const index = this._state().layers.findIndex((l) => l.presetId === presetId);
    if (index >= 0) {
      return this.patch({ origin, ops: [{ op: 'replace', path: `/layers/${index}/visible`, value: visible }] });
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

  reportLayer(presetId: string, status: LayerStatus): void {
    this._reported.update((r) => (r.layers[presetId] === status ? r : { ...r, layers: { ...r.layers, [presetId]: status } }));
  }

  reportTourStep(step: number | null): void {
    this._reported.update((r) => ({ ...r, tourStep: step }));
  }

  recentPatches(): readonly AppliedPatch[] {
    return this.history;
  }
}

export type { PatchOp };
