import { PatchOp, PatchOrigin, PatchResult, ReportedState, SceneState } from './scene.model';
import type { SceneStore } from './scene.store';

export interface DwsSceneDevHook {
  get(): SceneState;
  reported(): ReportedState;
  patch(ops: PatchOp[], origin?: PatchOrigin, baseVersion?: number): Promise<PatchResult>;
  history(): readonly unknown[];
}

declare global {
  interface Window {
    dwsScene?: DwsSceneDevHook;
  }
}

/**
 * Solo en desarrollo: expone el shadow en `window.dwsScene` para simular al
 * agente desde la consola, p. ej.:
 *   dwsScene.patch([{ op: 'replace', path: '/route', value: 'basin' }], 'agent')
 */
export function installSceneDevHook(store: SceneStore): void {
  // `ngDevMode` es false en producción y el optimizador elimina todo este bloque.
  if (typeof ngDevMode !== 'undefined' && !ngDevMode) {
    return;
  }
  window.dwsScene = {
    get: () => store.state(),
    reported: () => store.reported(),
    patch: (ops, origin = 'agent', baseVersion) => store.patch({ origin, ops, baseVersion }),
    history: () => store.recentPatches(),
  };
}
