import { SidePanelComponent } from '../../../../shared/components/side-panel/side-panel.component';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { RuntimeConfigService } from '../../../../core/config/runtime-config.service';
import { UiConfigService } from '../../../../core/config/ui-config.service';
import { FireStats, fetchFireStats } from '../../../../core/data-access/fires.client';
import { SceneStore } from '../../../../core/scene/scene.store';
import { EventService } from '../../../../core/services/event.service';
import { GeoEngineService } from '../../../../core/services/geo-engine.service';
import { MapCanvasComponent } from '../../../../shared/components/map-canvas/map-canvas.component';

type StatsState =
  | { status: 'none' }
  | { status: 'loading' }
  | { status: 'ready'; stats: FireStats }
  | { status: 'unavailable' | 'rate_limited' | 'error'; message: string };

/** Explorador de eventos (OpenSpec 09): imágenes NASA por tipo de evento y día. Smart. */
@Component({
  selector: 'app-event-explorer-page',
  imports: [MapCanvasComponent, SidePanelComponent, TranslocoPipe],
  templateUrl: './event-explorer-page.component.html',
  styleUrl: './event-explorer-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EventExplorerPageComponent {
  protected readonly map = inject(GeoEngineService);
  protected readonly scene = inject(SceneStore);
  private readonly ui = inject(UiConfigService);
  private readonly events = inject(EventService);
  private readonly apiBaseUrl = inject(RuntimeConfigService).value.apiBaseUrl;

  protected readonly eventTypes = this.ui.value.events;
  protected readonly placeIds = ['bolivia', 'cochabamba-basin', 'cochabamba-city'];
  protected readonly stats = signal<StatsState>({ status: 'none' });

  protected readonly active = computed(() => {
    const event = this.scene.state().event;
    return event ? { state: event, config: this.ui.event(event.type) } : null;
  });

  protected readonly eventLayers = computed(() =>
    (this.active()?.config?.layers ?? [])
      .map((id) => this.ui.layer(id))
      .filter((p) => p?.kind === 'gibs-wmts')
      .map((p) => p as Extract<typeof p, { kind: 'gibs-wmts' }>),
  );

  /** Días con cobertura verificada (events.json) dentro del rango del evento activo. */
  protected readonly verifiedDays = computed(() => {
    const a = this.active();
    if (!a?.config) return [];
    return this.events
      .verifiedDates(a.config, a.state.placeId)
      .filter((d) => d >= a.state.start && d <= a.state.end);
  });

  protected readonly maxMonthly = computed(() => {
    const s = this.stats();
    return s.status === 'ready' ? Math.max(1, ...s.stats.monthly.map((m) => m.count)) : 1;
  });

  private statsKey = '';

  constructor() {
    inject(DestroyRef).onDestroy(() => this.map.detach());

    // Sin evento activo: mostrar inundaciones en la cuenca por defecto.
    if (!this.scene.state().event) {
      void this.events.show('flood');
    }

    effect(() => {
      const active = this.active();
      untracked(() => void this.loadStats(active?.state ?? null, active?.config?.stats));
    });
  }

  protected onCanvasReady(container: HTMLElement): void {
    void this.map.attach(container);
  }

  protected selectEvent(id: string): void {
    void this.events.show(id);
  }

  protected selectPlace(placeId: string): void {
    void this.events.changePlace(placeId);
  }

  protected step(delta: number): void {
    void this.events.stepDate(delta);
  }

  protected setDate(value: string): void {
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      void this.events.setDate(value);
    }
  }

  protected name(text: { es: string; en: string } | undefined): string {
    return text ? text[this.scene.lang()] : '';
  }

  protected placeName(placeId: string): string {
    return this.name(this.ui.place(placeId)?.name);
  }

  protected layerStatus(presetId: string): string | undefined {
    return this.scene.reported().layers[presetId];
  }

  private async loadStats(event: { placeId: string; start: string; end: string } | null, source?: 'firms'): Promise<void> {
    if (!event || source !== 'firms') {
      this.statsKey = '';
      this.stats.set({ status: 'none' });
      return;
    }
    const key = `${event.placeId}|${event.start}|${event.end}`;
    if (key === this.statsKey) return;
    this.statsKey = key;
    this.stats.set({ status: 'loading' });
    const result = await fetchFireStats(this.apiBaseUrl, event.placeId, event.start, event.end);
    if (key !== this.statsKey) return;
    if (result.ok) {
      this.stats.set({ status: 'ready', stats: result.day });
    } else {
      const status = result.code === 'firms_not_configured' ? 'unavailable' : result.code === 'firms_rate_limited' ? 'rate_limited' : 'error';
      this.stats.set({ status, message: result.message });
    }
  }

  /** Ocultar o mostrar el panel (flag /panels/layerPanel del shadow). */
  protected setPanelOpen(open: boolean): void {
    void this.scene.set('/panels/layerPanel', open);
  }

}
