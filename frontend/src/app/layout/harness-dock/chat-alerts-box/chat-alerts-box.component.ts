import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { DistrictProps } from '../../../core/alerts/alerts.model';

export interface ChatAlertsSummary {
  counts: { level: string; n: number }[];
  top: DistrictProps;
  picked: DistrictProps | null;
}

/** Apartado de alertas dentro del chat: niveles vigentes y preguntas listas para explicarlos. Dumb. */
@Component({
  selector: 'app-chat-alerts-box',
  imports: [TranslocoPipe],
  templateUrl: './chat-alerts-box.component.html',
  styleUrl: './chat-alerts-box.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatAlertsBoxComponent {
  private readonly i18n = inject(TranslocoService);
  readonly summary = input.required<ChatAlertsSummary>();
  readonly busy = input(false);
  /** Pregunta a enviar al chat (clave i18n + parámetros). */
  readonly ask = output<{ key: string; params?: Record<string, unknown> }>();

  protected level(level: string | undefined): string {
    return this.i18n.translate(`risk.levels.${level ?? 'sin'}`).toLowerCase();
  }
}
