import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { RiskIconComponent } from '../risk-icon/risk-icon.component';

/** "¿Cómo sabemos?": las 4 pistas, el resultado y qué significa cada color. Dumb. */
@Component({
  selector: 'app-how-it-works',
  imports: [TranslocoPipe, RiskIconComponent],
  templateUrl: './how-it-works.component.html',
  styleUrl: './how-it-works.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HowItWorksComponent {
  protected readonly clues = ['lluvia', 'suelo', 'terreno', 'radar'];
  protected readonly levels = ['verde', 'amarillo', 'naranja', 'rojo'];
}
