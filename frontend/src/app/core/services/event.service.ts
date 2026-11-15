import { Injectable, inject } from '@angular/core';
import { UiConfigService } from '../config/ui-config.service';
import { EventConfig } from '../config/ui-config.model';
import { LayerState, PatchOp, PatchResult } from '../scene/scene.model';
import { SceneStore } from '../scene/scene.store';

const DAY_MS = 86_400_000;
const DEFAULT_MIN_DATE = '2018-04-01';
const MAX_FIRMS_RANGE_DAYS = 731;
const ISO_DAY_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

interface PlainDateLike {
  toString(): string;
  add(duration: { days: number }): PlainDateLike;
  since(other: PlainDateLike, options: { largestUnit: 'day' }): { days: number };
}

interface TemporalLike {
  Now: { plainDateISO(): PlainDateLike };
  PlainDate: { from(value: string): PlainDateLike };
}

function getTemporal(): TemporalLike | undefined {
  return (globalThis as { Temporal?: TemporalLike }).Temporal;
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

function parseIsoParts(day: string): [number, number, number] | null {
  const m = ISO_DAY_RE.exec(day);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const dom = Number(m[3]);
  const utc = new Date(Date.UTC(year, month - 1, dom));
  if (utc.getUTCFullYear() !== year || utc.getUTCMonth() !== month - 1 || utc.getUTCDate() !== dom) {
    return null;
  }
  return [year, month, dom];
}

/** Valida que la cadena sea una fecha calendario real YYYY-MM-DD. */
export function isIsoDate(value: string): boolean {
  return parseIsoParts(value) !== null;
}

/** Fecha calendario local de hoy (YYYY-MM-DD) sin deriva UTC; usa Temporal si existe. */
export function todayIso(): string {
  const temporal = getTemporal();
  if (temporal) {
    return temporal.Now.plainDateISO().toString();
  }
  const now = new Date();
  return `${now.getFullYear()}-${pad2(now.getMonth() + 1)}-${pad2(now.getDate())}`;
}

export function isoDay(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** Suma o resta días calendario sin deriva por zona horaria. */
export function addDays(day: string, delta: number): string {
  const temporal = getTemporal();
  if (temporal && isIsoDate(day)) {
    return temporal.PlainDate.from(day).add({ days: delta }).toString();
  }
  const parts = parseIsoParts(day);
  if (!parts) return day;
  const [y, m, d] = parts;
  return new Date(Date.UTC(y, m - 1, d + delta)).toISOString().slice(0, 10);
}

/** Diferencia en días calendario (`end - start`). */
export function diffDays(start: string, end: string): number {
  const temporal = getTemporal();
  if (temporal && isIsoDate(start) && isIsoDate(end)) {
    return temporal.PlainDate.from(end).since(temporal.PlainDate.from(start), { largestUnit: 'day' }).days;
  }
  const a = parseIsoParts(start);
  const b = parseIsoParts(end);
  if (!a || !b) return 0;
  return Math.round((Date.UTC(b[0], b[1] - 1, b[2]) - Date.UTC(a[0], a[1] - 1, a[2])) / DAY_MS);
}

function clampIso(day: string, min: string, max: string): string {
  return day < min ? min : day > max ? max : day;
}

export interface EventDateBounds {
  min: string;
  max: string;
  maxSpanDays: number | null;
}

export type RangeAdjustment = 'order' | 'max_span' | null;

export interface RangeUpdateResult {
  ok: boolean;
  start: string;
  end: string;
  date: string;
  adjusted: RangeAdjustment;
}

/**
 * Lógica de eventos (OpenSpec 09): traduce "mostrar evento X en lugar Y" a un
 * parche del shadow. El backend (`show_event`) genera exactamente las mismas operaciones.
 */
@Injectable({ providedIn: 'root' })
export class EventService {
  private readonly ui = inject(UiConfigService);
  private readonly scene = inject(SceneStore);

  /** Límites calendario reales del evento (cobertura de capas hasta hoy). */
  boundsFor(event?: EventConfig): EventDateBounds {
    const max = todayIso();
    const coverageStarts = (event?.layers ?? [])
      .map((id) => this.ui.layer(id))
      .map((layer) => (layer && 'coverageFrom' in layer ? layer.coverageFrom : undefined))
      .filter((d): d is string => Boolean(d && isIsoDate(d)));
    const minCandidate = coverageStarts.length ? coverageStarts.sort()[0] : DEFAULT_MIN_DATE;
    return {
      min: minCandidate > max ? max : minCandidate,
      max,
      maxSpanDays: event?.stats === 'firms' ? MAX_FIRMS_RANGE_DAYS : null,
    };
  }

  /** Rango por defecto: últimos 30 días, o alrededor de una fecha con cobertura verificada. */
  defaultRange(event: EventConfig, placeId: string): { start: string; end: string; date: string } {
    const yesterday = addDays(todayIso(), -1);
    const dates = this.verifiedDates(event, placeId);
    if (dates.length) {
      // Rango que cubre todas las pasadas verificadas; se muestra la más reciente.
      const latest = dates[0];
      const earliest = dates[dates.length - 1];
      return { start: earliest, end: yesterday < latest ? latest : yesterday, date: latest };
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

  /** Selecciona cualquier fecha válida; si sale del rango actual, ajusta el rango para incluirla. */
  async setDate(date: string): Promise<PatchResult> {
    if (!isIsoDate(date)) {
      return { ok: false, reason: 'Fecha inválida' };
    }
    const event = this.scene.state().event;
    const config = event ? this.ui.event(event.type) : undefined;
    const bounds = this.boundsFor(config);
    const day = clampIso(date, bounds.min, bounds.max);
    if (!event) {
      return this.scene.set('/time/date', day);
    }
    if (day >= event.start && day <= event.end) {
      return this.scene.set('/time/date', day);
    }
    let start = day < event.start ? day : event.start;
    let end = day > event.end ? day : event.end;
    if (bounds.maxSpanDays && diffDays(start, end) + 1 > bounds.maxSpanDays) {
      if (day < event.start) {
        end = clampIso(addDays(start, bounds.maxSpanDays - 1), start, bounds.max);
      } else {
        start = clampIso(addDays(end, -(bounds.maxSpanDays - 1)), bounds.min, end);
      }
    }
    return this.patchRange(start, end, day);
  }

  /** Actualiza el rango [start, end] validando orden, límites y tope de 2 años en FIRMS. */
  async setRange(rawStart: string, rawEnd: string, edited: 'start' | 'end'): Promise<RangeUpdateResult> {
    const event = this.scene.state().event;
    const config = event ? this.ui.event(event.type) : undefined;
    const bounds = this.boundsFor(config);
    const currentDate = this.scene.time().date ?? bounds.max;
    if (!event || !isIsoDate(rawStart) || !isIsoDate(rawEnd)) {
      return {
        ok: false,
        start: event?.start ?? bounds.min,
        end: event?.end ?? bounds.max,
        date: currentDate,
        adjusted: null,
      };
    }

    let start = clampIso(rawStart, bounds.min, bounds.max);
    let end = clampIso(rawEnd, bounds.min, bounds.max);
    let adjusted: RangeAdjustment = null;

    if (start > end) {
      adjusted = 'order';
      if (edited === 'start') {
        end = start;
      } else {
        start = end;
      }
    }

    if (bounds.maxSpanDays && diffDays(start, end) + 1 > bounds.maxSpanDays) {
      adjusted = 'max_span';
      if (edited === 'start') {
        end = clampIso(addDays(start, bounds.maxSpanDays - 1), start, bounds.max);
      } else {
        start = clampIso(addDays(end, -(bounds.maxSpanDays - 1)), bounds.min, end);
      }
    }

    const nextDate = clampIso(currentDate, start, end);
    const res = await this.patchRange(start, end, nextDate);
    return { ok: res.ok, start, end, date: nextDate, adjusted };
  }

  stepDate(delta: number): Promise<PatchResult> {
    const current = this.scene.time().date;
    return current ? this.setDate(addDays(current, delta)) : Promise.resolve({ ok: false, reason: 'Sin fecha' });
  }

  private patchRange(start: string, end: string, date: string): Promise<PatchResult> {
    return this.scene.patch({
      origin: 'user',
      ops: [
        { op: 'replace', path: '/event/start', value: start },
        { op: 'replace', path: '/event/end', value: end },
        { op: 'replace', path: '/time/start', value: start },
        { op: 'replace', path: '/time/end', value: end },
        { op: 'replace', path: '/time/date', value: date },
      ],
    });
  }
}
