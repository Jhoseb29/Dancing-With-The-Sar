/**
 * Shadow de la UI (OpenSpec 07). Contrato: backend/shared/schemas/scene-state.schema.json
 * y scene-patch.schema.json. Mantener ambos alineados.
 */

export type AppLang = 'es' | 'en';
export const AVAILABLE_LANGS: readonly AppLang[] = ['es', 'en'];

export type RouteId =
  'orbit' | 'basin' | 'events' | 'temporal' | 'risk' | 'insights' | 'provenance';

export interface SceneEvent {
  type: string;
  placeId: string;
  start: string;
  end: string;
}

export interface LayerState {
  presetId: string;
  visible: boolean;
  opacity: number;
}

export interface SceneState {
  version: number;
  route: RouteId;
  lang: AppLang;
  camera: { placeId: string | null; tourId: string | null; follow: boolean };
  time: {
    mode: 'live' | 'range';
    start: string | null;
    end: string | null;
    date: string | null;
    speed: number;
  };
  event: SceneEvent | null;
  layers: LayerState[];
  search: { query: string; selectedPlaceId: string | null };
  panels: { layerPanel: boolean };
}

export type PatchOrigin = 'user' | 'url';

export interface PatchOp {
  op: 'replace' | 'add' | 'remove';
  path: string;
  value?: unknown;
}

export interface ScenePatch {
  origin: PatchOrigin;
  baseVersion?: number;
  ops: PatchOp[];
}

export type PatchResult = { ok: true; version: number } | { ok: false; reason: string };

/** Evento emitido por cada parche aplicado (los adaptadores reaccionan a comandos). */
export interface AppliedPatch {
  version: number;
  origin: PatchOrigin;
  ops: PatchOp[];
}

export type LayerStatus = 'loading' | 'ready' | 'error';

/** Estado reportado por los motores: lo que la pantalla muestra de verdad. */
export interface ReportedState {
  route: RouteId | null;
  camera: { lon: number; lat: number; altKm?: number; zoom?: number } | null;
  layers: Record<string, LayerStatus>;
  tourStep: number | null;
}

/** Igual que el `pattern` de scene-patch.schema.json. */
export const PATCHABLE_PATH =
  /^\/(route|lang|camera\/(placeId|tourId|follow)|time\/(mode|start|end|date|speed)|event(\/(type|placeId|start|end))?|layers(\/(\d+|-)(\/(presetId|visible|opacity))?)?|search\/(query|selectedPlaceId)|panels\/layerPanel)$/;

export const ROUTE_IDS: readonly RouteId[] = [
  'orbit',
  'basin',
  'events',
  'temporal',
  'risk',
  'insights',
  'provenance',
];

export function isAppLang(value: unknown): value is AppLang {
  return typeof value === 'string' && (AVAILABLE_LANGS as readonly string[]).includes(value);
}

export function initialScene(): SceneState {
  return {
    version: 0,
    route: 'orbit',
    lang: 'es',
    camera: { placeId: null, tourId: null, follow: false },
    time: { mode: 'live', start: null, end: null, date: null, speed: 1 },
    event: null,
    layers: [{ presetId: 'basin-susceptibility', visible: true, opacity: 0.72 }],
    search: { query: '', selectedPlaceId: null },
    panels: { layerPanel: true },
  };
}
