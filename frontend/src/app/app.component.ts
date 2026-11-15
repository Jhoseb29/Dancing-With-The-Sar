import { ChangeDetectionStrategy, Component } from '@angular/core';
import { MainShellComponent } from './layout/main-shell/main-shell.component';

@Component({
  selector: 'app-root',
  imports: [MainShellComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent {}
