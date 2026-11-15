import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { SceneStore } from '../../../../core/scene/scene.store';
import { AlertsService } from '../../../../core/services/alerts.service';
import { BasinsService } from '../../../../core/services/basins.service';
import { GeoEngineService } from '../../../../core/services/geo-engine.service';
import { StationsService } from '../../../../core/services/stations.service';
import { MapCanvasComponent } from '../../../../shared/components/map-canvas/map-canvas.component';
import { SidePanelComponent } from '../../../../shared/components/side-panel/side-panel.component';
import { EvalViewComponent } from '../../components/eval-view/eval-view.component';
import { HowItWorksComponent } from '../../components/how-it-works/how-it-works.component';
import { StationsPanelComponent } from '../../components/stations-panel/stations-panel.component';

type Tab = 'now' | 'how' | 'eval';

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
  ],
  templateUrl: './risk-page.component.html',
  styleUrl: './risk-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RiskPageComponent {
  protected readonly map = inject(GeoEngineService);
  protected readonly scene = inject(SceneStore);
  protected readonly alerts = inject(AlertsService);
  private readonly stations = inject(StationsService);
  protected readonly tabs: Tab[] = ['now', 'how', 'eval'];
  protected readonly tab = signal<Tab>('now');
  protected readonly districts = computed(() => (this.alerts.districts()?.features ?? []).map((f) => f.properties));
  private readonly basinsSvc = inject(BasinsService);
  private readonly router = inject(Router);
  /** Cuencas que bajan al distrito elegido. */
  protected readonly districtBasins = computed(() => {
    const id = this.alerts.selectedDistrictId();
    return id ? (this.basinsSvc.basins()?.features ?? []).map((f) => f.properties).filter((b) => b.distritos?.includes(id)) : [];
  });

  constructor() {
    this.alerts.connect();
    void this.basinsSvc.load();
    void this.stations.load();
    inject(DestroyRef).onDestroy(() => {
      this.map.detach();
      this.alerts.disconnect();
      this.alerts.selectDistrict(null);
    });
  }

  protected onCanvasReady(container: HTMLElement): void {
    void this.map.attach(container);
  }

  protected setPanelOpen(open: boolean): void {
    void this.scene.set('/panels/layerPanel', open);
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
