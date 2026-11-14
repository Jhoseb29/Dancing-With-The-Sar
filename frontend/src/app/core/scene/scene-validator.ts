import type { ValidateFunction } from 'ajv';
import type { UiConfig } from '../config/ui-config.model';
import type { SceneState } from './scene.model';

let validatorPromise: Promise<ValidateFunction> | null = null;

/**
 * Valida un SceneState completo contra scene-state.schema.json (copiado como
 * asset desde backend/shared/schemas). Ajv se carga de forma diferida: solo se
 * descarga cuando llega el primer parche de origen `agent`.
 */
export async function validateSceneForAgent(state: SceneState, config: UiConfig): Promise<string | null> {
  const validate = await loadValidator();
  if (!validate(state)) {
    const first = validate.errors?.[0];
    return `Schema: ${first?.instancePath || '/'} ${first?.message ?? 'inválido'}`;
  }

  // Integridad referencial contra la configuración JSON.
  if (!config.routes.some((r) => r.id === state.route)) {
    return `Ruta desconocida: ${state.route}`;
  }
  if (state.camera.placeId && !config.places.some((p) => p.id === state.camera.placeId)) {
    return `Lugar desconocido: ${state.camera.placeId}`;
  }
  if (state.search.selectedPlaceId && !config.places.some((p) => p.id === state.search.selectedPlaceId)) {
    return `Lugar desconocido: ${state.search.selectedPlaceId}`;
  }
  if (state.camera.tourId && !config.tours.some((t) => t.id === state.camera.tourId)) {
    return `Recorrido desconocido: ${state.camera.tourId}`;
  }
  const unknownLayer = state.layers.find((l) => !config.layers.some((c) => c.id === l.presetId));
  if (unknownLayer) {
    return `Capa desconocida: ${unknownLayer.presetId}`;
  }
  if (state.event) {
    const event = config.events.find((e) => e.id === state.event?.type);
    if (!event) {
      return `Evento desconocido: ${state.event.type}`;
    }
    if (!event.available) {
      return `El evento ${event.id} no tiene datos disponibles todavía`;
    }
    if (!config.places.some((p) => p.id === state.event?.placeId)) {
      return `Lugar desconocido: ${state.event.placeId}`;
    }
    if (state.event.start > state.event.end) {
      return 'El rango del evento es inválido (inicio posterior al fin)';
    }
    if (state.time.date && (state.time.date < state.event.start || state.time.date > state.event.end)) {
      return `La fecha ${state.time.date} está fuera del rango del evento`;
    }
  }
  if (state.time.date && state.time.date > new Date().toISOString().slice(0, 10)) {
    return `La fecha ${state.time.date} es futura`;
  }
  return null;
}

function loadValidator(): Promise<ValidateFunction> {
  validatorPromise ??= (async () => {
    const [{ default: Ajv }, schema] = await Promise.all([
      import('ajv'),
      fetch('assets/schemas/scene-state.schema.json').then((r) => r.json() as Promise<object>),
    ]);
    const ajv = new Ajv({ strict: false, validateFormats: false, allErrors: false });
    return ajv.compile(schema);
  })();
  return validatorPromise;
}
