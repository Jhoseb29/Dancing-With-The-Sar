import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { HarnessHttpError, runFileUrl, streamAsk, HarnessSensor } from '../harness/harness-client';
import { HarnessEvent, HarnessMedia, HarnessPayload } from '../harness/harness.model';
import { RuntimeConfigService } from '../config/runtime-config.service';
import { AlertsService } from './alerts.service';
import { HarnessGlobeService } from './harness-globe.service';
import { VoiceService } from './voice.service';

export interface HarnessTurn {
  id: number;
  question: string;
  state: 'running' | 'done' | 'error';
  /** 0..1 según los eventos del harness. */
  progress: number;
  /** Mensajes de progreso en orden ("Buscando pasadas…", "Leyendo imagen 1/2…"). */
  steps: string[];
  runId: string | null;
  payload: HarnessPayload | null;
  errorCode: string | null;
  errorMessage: string | null;
}

/**
 * Adaptador Angular ↔ harness NISAR. Cada pregunta es un turno: se muestra el
 * progreso en vivo y, al terminar, el payload (chat corto, lección, mapas).
 */
@Injectable({ providedIn: 'root' })
export class HarnessService {
  private readonly apiBaseUrl = inject(RuntimeConfigService).value.apiBaseUrl;
  private readonly globe = inject(HarnessGlobeService);
  private readonly voice = inject(VoiceService);
  private readonly router = inject(Router);
  private readonly alerts = inject(AlertsService);
  private abort: AbortController | null = null;
  private nextId = 1;

  readonly turns = signal<HarnessTurn[]>([]);
  readonly busy = computed(() => this.turns().some((t) => t.state === 'running'));
  /** El chat es uno solo para toda la app: cualquier vista puede abrirlo con una pregunta. */
  readonly dockOpen = signal(false);
  /** Satélite elegido para aprender y navegar (la pregunta también puede nombrarlo). */
  readonly sensor = signal<HarnessSensor>('auto');

  constructor() {
    inject(DestroyRef).onDestroy(() => this.abort?.abort());
  }

  async ask(question: string): Promise<void> {
    const text = question.trim();
    if (!text || this.busy()) {
      return;
    }
    const id = this.nextId++;
    this.turns.update((turns) => [
      ...turns.slice(-19),
      {
        id,
        question: text,
        state: 'running',
        progress: 0,
        steps: [],
        runId: null,
        payload: null,
        errorCode: null,
        errorMessage: null,
      },
    ]);


    this.abort = new AbortController();
    try {
      await streamAsk(this.apiBaseUrl, text, (event) => this.onEvent(id, event), this.abort.signal, this.sensor());
      this.present(id);
      this.update(id, (t) =>
        t.state === 'running' ? { ...t, state: 'error', errorCode: 'harness_failed' } : t,
      );
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === 'AbortError';
      const code = err instanceof HarnessHttpError ? err.code : aborted ? 'cancelled' : 'network';
      this.update(id, (t) => ({
        ...t,
        state: 'error',
        errorCode: code,
        errorMessage: err instanceof Error ? err.message : null,
      }));
    } finally {
      this.abort = null;
    }
  }

  /** Abre el chat y, si se da, pregunta (p. ej. desde la ficha de un distrito). */
  openWith(question?: string): void {
    this.dockOpen.set(true);
    if (question) void this.ask(question);
  }

  /** Lleva una respuesta sobre alertas al mapa de alertas, con su distrito elegido. */
  showAlerts(turn: HarnessTurn): void {
    const focus = turn.payload?.alerts?.focus ?? [];
    void this.router.navigate(['/riesgo']).then(() => this.alerts.selectedDistrictId.set(focus[0] ?? null));
  }

  cancel(): void {
    this.abort?.abort();
  }

  /** Lleva un turno terminado al globo (vista de análisis): encuadra el área y muestra las tomas. */
  showOnGlobe(turn: HarnessTurn): void {
    if (turn.runId && turn.payload?.globe?.takes.length) {
      void this.globe.show(turn.runId, turn.payload, turn.question);
    }
  }

  fileUrl(turn: HarnessTurn, media: HarnessMedia): string {
    return turn.runId ? runFileUrl(this.apiBaseUrl, turn.runId, media.path) : '';
  }

  private onEvent(id: number, event: HarnessEvent): void {
    this.update(id, (turn) => {
      const next: HarnessTurn = { ...turn, runId: event.run_id ?? turn.runId };
      if (typeof event.progress === 'number') {
        next.progress = Math.max(turn.progress, event.progress);
      }
      switch (event.stage) {
        case 'result':
          return event.payload
            ? { ...next, state: 'done', progress: 1, payload: event.payload }
            : {
                ...next,
                state: 'error',
                errorCode: 'harness_failed',
                errorMessage: turn.steps.at(-1) ?? null,
              };
        case 'error':
          return {
            ...next,
            state: 'error',
            errorCode: event.code ?? 'harness_failed',
            errorMessage: event.message,
          };
        case 'done':
          return next; // el payload llega en el evento `result`
        default:
          return { ...next, steps: [...turn.steps, event.message].slice(-8) };
      }
    });
  }

  /** Al terminar: como hacía el agente, mostrar el resultado en el globo y (opcional) leerlo. */
  private present(id: number): void {
    const turn = this.turns().find((t) => t.id === id);
    if (turn?.state !== 'done' || !turn.payload) return;
    if (turn.payload.mode === 'alertas') {
      this.showAlerts(turn);
    } else {
      this.showOnGlobe(turn);
    }
    void this.voice.speak(turn.payload.chat?.message ?? '');
  }

  private update(id: number, fn: (turn: HarnessTurn) => HarnessTurn): void {
    this.turns.update((turns) => turns.map((t) => (t.id === id ? fn(t) : t)));
  }
}
