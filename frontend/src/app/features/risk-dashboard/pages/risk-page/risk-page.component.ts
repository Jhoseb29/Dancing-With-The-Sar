import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { SceneStore } from '../../../../core/scene/scene.store';
import { AlertsService } from '../../../../core/services/alerts.service';
import { BasinsService } from '../../../../core/services/basins.service';
import { HarnessService } from '../../../../core/services/harness.service';
import { GeoEngineService } from '../../../../core/services/geo-engine.service';
import { StationsService } from '../../../../core/services/stations.service';
import { TanksService } from '../../../../core/services/tanks.service';
import { MapCanvasComponent } from '../../../../shared/components/map-canvas/map-canvas.component';
import { SidePanelComponent } from '../../../../shared/components/side-panel/side-panel.component';
import { EvalViewComponent } from '../../components/eval-view/eval-view.component';
import { HowItWorksComponent } from '../../components/how-it-works/how-it-works.component';
import { StationsPanelComponent } from '../../components/stations-panel/stations-panel.component';
import { PossibleEventsComponent } from '../../components/possible-events/possible-events.component';
import { TanksPanelComponent } from '../../components/tanks-panel/tanks-panel.component';

type Tab = 'now' | 'possible' | 'tanks' | 'how' | 'eval';

/** Alertas por distrito: mapa 3D (color = nivel, altura = riesgo) + panel corto. Smart. */
@Component({
  selector: 'app-risk-page',
  imports: [
    MapCanvasComponent,
    SidePanelComponent,
    TranslocoPipe,
    HowItWorksComponent,
    EvalViewComponent,
    StationsPanelComponent,
    PossibleEventsComponent,
    TanksPanelComponent,
  ],
  templateUrl: './risk-page.component.html',
  styleUrl: './risk-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RiskPageComponent {
  protected readonly map = inject(GeoEngineService);
  protected readonly scene = inject(SceneStore);
  protected readonly alerts = inject(AlertsService);
  protected readonly tanksSvc = inject(TanksService);
  private readonly stations = inject(StationsService);
  protected readonly tabs: Tab[] = ['now', 'possible', 'tanks', 'how', 'eval'];
  protected readonly tab = signal<Tab>('now');
  protected readonly districts = computed(() => (this.alerts.districts()?.features ?? []).map((f) => f.properties));
  private readonly basinsSvc = inject(BasinsService);
  private readonly router = inject(Router);
  private readonly harness = inject(HarnessService);
  private readonly i18n = inject(TranslocoService);
  /** Cuencas que bajan al distrito elegido. */
  protected readonly districtBasins = computed(() => {
    const id = this.alerts.selectedDistrictId();
    return id ? (this.basinsSvc.basins()?.features ?? []).map((f) => f.properties).filter((b) => b.distritos?.includes(id)) : [];
  });

  constructor() {
    this.alerts.connect();
    void this.basinsSvc.load();
    void this.stations.load();
    effect(() => {
      this.tanksSvc.mapActive.set(this.tab() === 'tanks');
    });
    inject(DestroyRef).onDestroy(() => {
      this.tanksSvc.mapActive.set(false);
      this.map.detach();
      this.alerts.disconnect();
      this.alerts.selectDistrict(null);
    });
  }

  protected selectTab(t: Tab): void {
    this.tab.set(t);
    if (t === 'tanks') void this.tanksSvc.load();
  }

  protected onTabKeydown(ev: KeyboardEvent, index: number): void {
    let next = -1;
    if (ev.key === 'ArrowRight') next = (index + 1) % this.tabs.length;
    else if (ev.key === 'ArrowLeft') next = (index - 1 + this.tabs.length) % this.tabs.length;
    else if (ev.key === 'Home') next = 0;
    else if (ev.key === 'End') next = this.tabs.length - 1;
    if (next < 0) return;
    ev.preventDefault();
    const targetTab = this.tabs[next];
    this.selectTab(targetTab);
    const btn = (ev.currentTarget as HTMLElement)?.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next];
    btn?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    btn?.focus();
  }

  protected onCanvasReady(container: HTMLElement): void {
    void this.map.attach(container);
  }

  protected setPanelOpen(open: boolean): void {
    void this.scene.set('/panels/layerPanel', open);
  }

  /** Mismo chat de toda la app: pregunta por qué este distrito tiene su nivel. */
  protected askAbout(): void {
    const d = this.alerts.selectedDistrict();
    if (!d) return;
    const nivel = this.i18n.translate(`risk.levels.${d.estado?.nivel ?? 'sin'}`).toLowerCase();
    this.harness.openWith(this.i18n.translate('harness.alertsBox.why', { id: d.id, nivel }));
  }

  /** Abre la cuenca en la vista Cuenca, ya seleccionada. */
  protected openBasin(id: string): void {
    this.basinsSvc.selectedId.set(id);
    void this.router.navigate(['/cuenca']);
  }

  protected pick(id: string | null): void {
    this.tab.set('now');
    this.alerts.selectDistrict(id);
  }
}
