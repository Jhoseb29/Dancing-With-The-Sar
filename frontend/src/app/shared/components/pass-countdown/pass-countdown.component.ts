import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, input, signal } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { OrbitPass } from '../../../core/data-access/orbit.model';
import { OrbitStatus } from '../../../core/services/orbit.service';

/** Widget de la barra superior: cuenta regresiva al próximo paso de NISAR. Dumb. */
@Component({
  selector: 'app-pass-countdown',
  imports: [TranslocoPipe],
  templateUrl: './pass-countdown.component.html',
  styleUrl: './pass-countdown.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PassCountdownComponent {
  readonly pass = input<OrbitPass | null>(null);
  readonly status = input<OrbitStatus>('idle');

  private readonly now = signal(Date.now());

  readonly remaining = computed(() => {
    const pass = this.pass();
    if (!pass) {
      return null;
    }
    const totalSeconds = Math.max(0, Math.floor((pass.timeMs - this.now()) / 1000));
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    return `T−${pad(h)}:${pad(m)}:${pad(s)}`;
  });

  constructor() {
    const timer = setInterval(() => this.now.set(Date.now()), 1000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }
}

function pad(value: number): string {
  return value.toString().padStart(2, '0');
}
