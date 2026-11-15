import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ALERT_HEX, SCENARIOS } from '../../../../core/alerts/stations.model';
import { HarnessService } from '../../../../core/services/harness.service';
import { StationsService } from '../../../../core/services/stations.service';

/**
 * Sistema de alertas de HidroGlobe: contadores por nivel, buscador, una tarjeta por estación
 * (tocar = volar y abrir su recuadro en el mapa) y escenarios históricos que el harness
 * puede analizar con radar. Smart (lee y escribe StationsService).
 */
@Component({
  selector: 'app-stations-panel',
  templateUrl: './stations-panel.component.html',
  styleUrl: './stations-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StationsPanelComponent {
  protected readonly st = inject(StationsService);
  protected readonly harness = inject(HarnessService);
  protected readonly hex = ALERT_HEX;
  protected readonly scenarios = SCENARIOS;
  protected readonly basins = [
    { value: 'TODAS', label: 'Todas las cuencas' },
    { value: 'Rocha', label: 'Río Rocha' },
    { value: 'Taquiña', label: 'Torrenteras Tunari' },
    { value: 'Albarrancho', label: 'Cuenca sur Albarrancho' },
    { value: 'Pasos', label: 'Pasos a desnivel' },
    { value: 'Chapare', label: 'Chapare / Trópico' },
  ];

  protected onSearch(event: Event): void {
    this.st.search.set((event.target as HTMLInputElement).value);
  }

  protected onBasin(event: Event): void {
    this.st.basin.set((event.target as HTMLSelectElement).value);
  }

  /** El harness analiza con radar NISAR / Sentinel-1 el evento histórico elegido. */
  protected analyze(question: string): void {
    void this.harness.ask(question);
  }
}
