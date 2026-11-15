import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export type RiskIconName = 'lluvia' | 'suelo' | 'terreno' | 'radar' | 'aviso' | 'calma';

/** Íconos de línea de la vista de alertas (heredan el color del texto). Dumb. */
@Component({
  selector: 'app-risk-icon',
  templateUrl: './risk-icon.component.html',
  styleUrl: './risk-icon.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RiskIconComponent {
  readonly name = input.required<RiskIconName | string>();
}
