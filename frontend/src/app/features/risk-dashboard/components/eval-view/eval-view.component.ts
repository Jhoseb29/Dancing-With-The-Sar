import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { EvalCase, EvalPayload } from '../../../../core/alerts/alerts.model';

const ORDER: EvalCase['resultado'][] = ['acierto', 'negativo_correcto', 'falsa_alarma', 'fallo', 'error'];

/** "¿Funciona?": emergencias detectadas, un punto por caso real y el puntaje por versión. Dumb. */
@Component({
  selector: 'app-eval-view',
  imports: [TranslocoPipe],
  templateUrl: './eval-view.component.html',
  styleUrl: './eval-view.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EvalViewComponent {
  readonly evaluation = input<EvalPayload | null>(null);

  protected readonly outcomes = ORDER.slice(0, 4);
  protected readonly summary = computed(() => this.evaluation()?.latest?.resumen ?? null);
  protected readonly cases = computed(() =>
    [...(this.evaluation()?.latest?.casos ?? [])].sort((a, b) => ORDER.indexOf(a.resultado) - ORDER.indexOf(b.resultado)),
  );
  protected readonly events = computed(() => {
    const t = this.summary()?.tabla ?? {};
    const found = t['acierto'] ?? 0;
    return { found, total: found + (t['fallo'] ?? 0), falseAlarms: t['falsa_alarma'] ?? 0 };
  });
  protected readonly versions = computed(() =>
    (this.evaluation()?.history ?? []).map((h, i) => ({ id: h.eval_id, label: `${i + 1}`, score: Math.round(h.puntaje) })),
  );
}
