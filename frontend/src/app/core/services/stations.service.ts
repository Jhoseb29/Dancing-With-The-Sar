import { Injectable, computed, signal } from '@angular/core';
import { ALERT_ORDER, FloodScenario, SCENARIOS, Station, StationAlert, Torrenteras } from '../alerts/stations.model';

const BASE = 'assets/data/hidroglobe';

/**
 * Sistema de alertas de HidroGlobe: estaciones con su nivel de alerta, red de torrenteras y
 * escenarios de inundación. Compartido por la vista Alertas, el mapa y el globo.
 */
@Injectable({ providedIn: 'root' })
export class StationsService {
  private loading: Promise<void> | null = null;

  readonly stations = signal<Station[]>([]);
  readonly torrenteras = signal<Torrenteras | null>(null);
  readonly scenarios = signal<Record<string, FloodScenario>>({});
  readonly search = signal('');
  readonly basin = signal('TODAS');
  readonly scenarioKey = signal<string | null>(null);
  /** Estación elegida: el mapa vuela a ella y abre su recuadro (el contador repite el mismo id). */
  readonly focusedId = signal<string | null>(null);
  readonly focusRequest = signal(0);
  /** Sube cuando el agente pide un escenario: el mapa vuelve a volar aunque ya estuviera elegido. */
  readonly scenarioRequest = signal(0);

  readonly filtered = computed(() => {
    const text = this.search().toLowerCase();
    const basin = this.basin().toLowerCase();
    return this.stations().filter((st) => {
      const matchText = [st.nombre, st.rio, st.zona].some((v) => v.toLowerCase().includes(text));
      const matchBasin =
        basin === 'todas' || st.cuenca.toLowerCase().includes(basin) || st.nombre.toLowerCase().includes(basin);
      return matchText && matchBasin;
    });
  });
  readonly counts = computed(() => {
    const out: Record<StationAlert, number> = { ROJA: 0, NARANJA: 0, AMARILLA: 0, VERDE: 0 };
    this.stations().forEach((s) => out[s.alerta]++);
    return out;
  });
  readonly worst = computed<StationAlert>(
    () => ALERT_ORDER[Math.max(0, ...this.stations().map((s) => ALERT_ORDER.indexOf(s.alerta)))],
  );
  readonly scenario = computed(() => {
    const key = this.scenarioKey();
    return key ? (this.scenarios()[key] ?? null) : null;
  });
  readonly scenarioView = computed(() => SCENARIOS.find((s) => s.key === this.scenarioKey()) ?? null);

  /** Carga una sola vez; llamadas simultáneas esperan la misma descarga. */
  load(): Promise<void> {
    this.loading ??= this.fetchAll();
    return this.loading;
  }

  private async fetchAll(): Promise<void> {
    const get = async <T>(file: string): Promise<T | null> => {
      const r = await fetch(new URL(`${BASE}/${file}`, document.baseURI)).catch(() => null);
      return r?.ok ? ((await r.json()) as T) : null;
    };
    const [stations, torrenteras, scenarios] = await Promise.all([
      get<Station[]>('estaciones_cochabamba.json'),
      get<Torrenteras>('torrenteras_cochabamba.json'),
      get<Record<string, FloodScenario>>('flood_scenarios_cochabamba.json'),
    ]);
    if (stations) this.stations.set(stations);
    if (torrenteras) this.torrenteras.set(torrenteras);
    if (scenarios) this.scenarios.set(scenarios);
    if (!stations) this.loading = null; // reintentar la próxima vez
  }

  focus(id: string): void {
    // Si un filtro la ocultaba, se limpia para que aparezca en la lista y en el mapa.
    if (!this.filtered().some((s) => s.id === id)) {
      this.search.set('');
      this.basin.set('TODAS');
    }
    this.focusedId.set(id);
    this.focusRequest.update((n) => n + 1);
  }

  /** Muestra un escenario (sin alternar: el agente siempre lo deja visible). */
  showScenario(key: string): void {
    this.scenarioKey.set(key);
    this.scenarioRequest.update((n) => n + 1);
  }

  selectScenario(key: string | null): void {
    this.scenarioKey.set(this.scenarioKey() === key ? null : key);
  }
}
