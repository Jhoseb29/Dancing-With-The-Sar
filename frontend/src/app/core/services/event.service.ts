import { Injectable, inject } from '@angular/core';
import { UiConfigService } from '../config/ui-config.service';
import { EventConfig } from '../config/ui-config.model';
import { LayerState, PatchOp, PatchResult } from '../scene/scene.model';
import { SceneStore } from '../scene/scene.store';

const DAY_MS = 86_400_000;

export function isoDay(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

export function addDays(day: string, delta: number): string {
  return isoDay(Date.parse(`${day}T00:00:00Z`) + delta * DAY_MS);
}

/**
 * Lógica de eventos (OpenSpec 09): traduce "mostrar evento X en lugar Y" a un
 * parche del shadow. El backend (`show_event`) genera exactamente las mismas operaciones.
 */
@Injectable({ providedIn: 'root' })
export class EventService {
  private readonly ui = inject(UiConfigService);
  private readonly scene = inject(SceneStore);

  /** Rango por defecto: últimos 30 días, o alrededor de una fecha con cobertura verificada. */
  defaultRange(event: EventConfig, placeId: string): { start: string; end: string; date: string } {
    const yesterday = isoDay(Date.now() - DAY_MS);
    const dates = this.verifiedDates(event, placeId);
    if (dates.length) {
      // Rango que cubre todas las pasadas verificadas; se muestra la más reciente.
      const latest = dates[0];
      const earliest = dates[dates.length - 1];
      return { start: earliest, end: yesterday, date: latest };
    }
    return { start: addDays(yesterday, -30), end: yesterday, date: yesterday };
  }

  /** Fechas con cobertura verificada para el lugar (más reciente primero). */
  verifiedDates(event: EventConfig, placeId: string): string[] {
    return (event.verifiedDates ?? [])
      .filter((v) => v.placeId === placeId)
      .map((v) => v.date)
      .sort()
      .reverse();
  }

  buildOps(eventId: string, placeId: string, start: string, end: string, date: string): PatchOp[] {
    if (!this.ui.event(eventId)) {
      return [];
    }
    // Las capas del evento no van a /layers (son de la cuenca): salen de events.json (layersFor).
    return [
      { op: 'replace', path: '/route', value: 'events' },
      { op: 'replace', path: '/event', value: { type: eventId, placeId, start, end } },
      { op: 'replace', path: '/time/mode', value: 'range' },
      { op: 'replace', path: '/time/start', value: start },
      { op: 'replace', path: '/time/end', value: end },
      { op: 'replace', path: '/time/date', value: date },
      { op: 'replace', path: '/camera/tourId', value: null },
      { op: 'replace', path: '/camera/placeId', value: placeId },
      { op: 'replace', path: '/search/selectedPlaceId', value: placeId },
    ];
  }

  /** Capas de imagen de un evento (events.json): la primera opaca, el resto semitransparentes. */
  layersFor(eventId: string): LayerState[] {
    return (this.ui.event(eventId)?.layers ?? []).map((presetId, index) => ({
      presetId,
      visible: true,
      opacity: index === 0 ? 1 : 0.85,
    }));
  }

  show(eventId: string, placeId?: string): Promise<PatchResult> {
    const event = this.ui.event(eventId);
    if (!event || !event.available) {
      return Promise.resolve({ ok: false, reason: 'Evento no disponible' });
    }
    const place = placeId ?? this.scene.state().event?.placeId ?? event.defaultPlaceId;
    const range = this.defaultRange(event, place);
    return this.scene.patch({ origin: 'user', ops: this.buildOps(eventId, place, range.start, range.end, range.date) });
  }

  changePlace(placeId: string): Promise<PatchResult> {
    const current = this.scene.state().event;
    if (!current) {
      return Promise.resolve({ ok: false, reason: 'Sin evento activo' });
    }
    return this.scene.patch({
      origin: 'user',
      ops: [
        { op: 'replace', path: '/event/placeId', value: placeId },
        { op: 'replace', path: '/camera/placeId', value: placeId },
        { op: 'replace', path: '/search/selectedPlaceId', value: placeId },
      ],
    });
  }

  setDate(date: string): Promise<PatchResult> {
    const event = this.scene.state().event;
    let day = date;
    if (event) {
      day = day < event.start ? event.start : day > event.end ? event.end : day;
    }
    return this.scene.set('/time/date', day);
  }

  stepDate(delta: number): Promise<PatchResult> {
    const current = this.scene.time().date;
    return current ? this.setDate(addDays(current, delta)) : Promise.resolve({ ok: false, reason: 'Sin fecha' });
  }
}
