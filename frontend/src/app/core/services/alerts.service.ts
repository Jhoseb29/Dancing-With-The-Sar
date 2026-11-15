import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { AlertsMessage, DistrictsFC, EvalPayload, RadarSchedule, RainPayload, RiskAlert } from '../alerts/alerts.model';
import { RuntimeConfigService } from '../config/runtime-config.service';

const MAX_ALERTS = 100;

/**
 * Alertas tempranas en vivo: snapshot + alertas nuevas por WebSocket (/api/alerts/ws),
 * distritos con su nivel vigente y la evaluación del harness (REST).
 */
@Injectable({ providedIn: 'root' })
export class AlertsService {
  private readonly apiBaseUrl = inject(RuntimeConfigService).value.apiBaseUrl;
  private socket: WebSocket | null = null;
  private retry = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private wanted = false;

  readonly connection = signal<'connecting' | 'open' | 'closed'>('closed');
  readonly alerts = signal<RiskAlert[]>([]);
  readonly districts = signal<DistrictsFC | null>(null);
  readonly evaluation = signal<EvalPayload | null>(null);
  readonly rain = signal<RainPayload | null>(null);
  readonly radar = signal<RadarSchedule | null>(null);
  /** Media hora que se ve en el mapa (índice en rain.slots); null = acumulado de 24 h. */
  readonly rainFrame = signal<number | null>(null);
  readonly rainPlaying = signal(false);
  /** Mostrar las columnas de lluvia en el mapa. */
  readonly rainVisible = signal(false); // Alertas usa el panel de estaciones: la grilla IMERG tapaba el mapa
  private rainTimer: ReturnType<typeof setInterval> | null = null;
  readonly selectedId = signal<string | null>(null);
  readonly selected = computed<RiskAlert | null>(() => this.alerts().find((a) => a.id === this.selectedId()) ?? this.alerts()[0] ?? null);

  /** Distrito elegido en el mapa o en la lista. */
  readonly selectedDistrictId = signal<string | null>(null);
  readonly selectedDistrict = computed(
    () => this.districts()?.features.find((f) => f.properties.id === this.selectedDistrictId())?.properties ?? null,
  );
  /** Alerta completa (indicadores, acciones) del distrito elegido, si llegó por el WebSocket. */
  readonly districtAlert = computed<RiskAlert | null>(() => {
    const id = this.selectedDistrict()?.estado?.datos?.alerta_id;
    return id ? (this.alerts().find((a) => a.id === id) ?? null) : null;
  });

  selectDistrict(id: string | null): void {
    this.selectedDistrictId.set(this.selectedDistrictId() === id ? null : id);
  }

  constructor() {
    inject(DestroyRef).onDestroy(() => this.disconnect());
  }

  /** Abre el WebSocket (reconecta solo) y carga distritos y evaluación. */
  connect(): void {
    this.wanted = true;
    void this.refresh();
    if (this.socket) return;
    const url = new URL(`${this.apiBaseUrl}/alerts/ws`, document.baseURI);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    this.connection.set('connecting');
    const socket = new WebSocket(url.href);
    this.socket = socket;
    socket.onopen = () => {
      this.retry = 0;
      this.connection.set('open');
    };
    socket.onmessage = (event) => this.onMessage(JSON.parse(String(event.data)) as AlertsMessage);
    socket.onclose = () => {
      this.socket = null;
      this.connection.set('closed');
      if (this.wanted) {
        this.retryTimer = setTimeout(() => this.connect(), Math.min(30_000, 1000 * 2 ** this.retry++));
      }
    };
  }

  /** Reproduce la lluvia media hora a media hora (vuelve al acumulado al terminar). */
  playRain(): void {
    const n = this.rain()?.slots.length ?? 0;
    if (!n) return;
    this.stopRain();
    this.rainPlaying.set(true);
    this.rainFrame.set(0);
    this.rainTimer = setInterval(() => {
      const next = (this.rainFrame() ?? -1) + 1;
      if (next >= n) {
        this.stopRain();
        this.rainFrame.set(null);
      } else {
        this.rainFrame.set(next);
      }
    }, 450);
  }

  stopRain(): void {
    if (this.rainTimer) clearInterval(this.rainTimer);
    this.rainTimer = null;
    this.rainPlaying.set(false);
  }

  disconnect(): void {
    this.stopRain();
    this.wanted = false;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.socket?.close();
    this.socket = null;
  }

  async refresh(): Promise<void> {
    const get = async <T>(path: string): Promise<T | null> => {
      const r = await fetch(`${this.apiBaseUrl}/alerts/${path}`).catch(() => null);
      return r?.ok ? ((await r.json()) as T) : null;
    };
    const [districts, evaluation, rain, radar] = await Promise.all([
      get<DistrictsFC>('districts'),
      get<EvalPayload>('eval'),
      get<RainPayload>('rain'),
      get<RadarSchedule>('radar'),
    ]);
    if (districts) this.districts.set(districts);
    if (evaluation) this.evaluation.set(evaluation);
    // El monitor escribe {"slots": []} cuando no pudo bajar IMERG (p. ej. Earthdata 403):
    // sin grilla ni pico no hay lluvia que mostrar, y los paneles asumen el payload completo.
    this.rain.set(isCompleteRain(rain) ? rain : null);
    if (radar) this.radar.set(radar);
  }

  private onMessage(msg: AlertsMessage): void {
    if (msg.type === 'snapshot') {
      this.alerts.set([...msg.alerts].reverse().slice(0, MAX_ALERTS));
    } else {
      this.alerts.update((list) => [msg.alert, ...list.filter((a) => a.id !== msg.alert.id)].slice(0, MAX_ALERTS));
      void this.refresh(); // el nivel vigente de los distritos pudo cambiar
    }
  }
}

function isCompleteRain(rain: RainPayload | null): rain is RainPayload {
  return (
    !!rain &&
    Array.isArray(rain.slots) &&
    Array.isArray(rain.lons) &&
    Array.isArray(rain.lats) &&
    Array.isArray(rain.acumulado_mm) &&
    Array.isArray(rain.productos) &&
    !!rain.pico
  );
}
