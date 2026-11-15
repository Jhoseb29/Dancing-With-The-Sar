import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { RiskPrediction } from '../../../../core/alerts/alerts.model';
import { AlertsService } from '../../../../core/services/alerts.service';

@Component({
  selector: 'app-possible-events',
  imports: [TranslocoPipe],
  templateUrl: './possible-events.component.html',
  styleUrl: './possible-events.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PossibleEventsComponent {
  protected readonly alerts = inject(AlertsService);

  protected pending(): RiskPrediction[] {
    return this.alerts.predictions().filter((prediction) => prediction.estado === 'pendiente');
  }

  protected closed(): RiskPrediction[] {
    return this.alerts.predictions().filter((prediction) => prediction.estado !== 'pendiente');
  }

  protected async confirm(prediction: RiskPrediction, occurred: boolean): Promise<void> {
    await this.alerts.confirmPrediction(prediction.id, occurred);
  }

  protected signal(prediction: RiskPrediction): string {
    const candidates = [
      { key: 'lluvia', value: prediction.componentes.disparo },
      { key: 'radar', value: prediction.componentes.evidencia_radar },
      { key: 'terreno', value: prediction.componentes.susceptibilidad },
    ].filter((item): item is { key: string; value: number } => item.value !== null);
    return candidates.sort((a, b) => b.value - a.value)[0]?.key ?? 'lluvia';
  }

  protected date(value: string): string {
    return new Date(value).toLocaleString();
  }
}
