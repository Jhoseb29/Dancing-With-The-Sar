import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { SceneStore } from '../../core/scene/scene.store';
import { AgentService } from '../../core/services/agent.service';
import { VoiceService } from '../../core/services/voice.service';

/** Panel conversacional del agente (OpenSpec 08). Abierto/cerrado según /panels/agentDock. */
@Component({
  selector: 'app-agent-dock',
  imports: [TranslocoPipe],
  templateUrl: './agent-dock.component.html',
  styleUrl: './agent-dock.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentDockComponent {
  protected readonly scene = inject(SceneStore);
  protected readonly agent = inject(AgentService);
  protected readonly voice = inject(VoiceService);
  protected readonly askPrivacy = signal(false);

  protected readonly open = computed(() => this.scene.panels().agentDock === 'open');
  protected readonly draft = signal('');
  protected readonly busy = computed(() => ['transcribing', 'thinking', 'acting'].includes(this.agent.status()));

  private readonly log = viewChild<ElementRef<HTMLElement>>('log');
  private readonly input = viewChild<ElementRef<HTMLTextAreaElement>>('input');

  constructor() {
    // Abrir el panel (usuario o agente) abre la sesión; el agente saluda.
    effect(() => {
      if (this.open()) {
        untracked(() => {
          this.agent.connect();
          setTimeout(() => this.input()?.nativeElement.focus(), 0);
        });
      }
    });

    // Mantener la transcripción al final.
    effect(() => {
      this.agent.transcript();
      this.agent.status();
      untracked(() => setTimeout(() => {
        const el = this.log()?.nativeElement;
        if (el) el.scrollTop = el.scrollHeight;
      }, 0));
    });
  }

  protected toggle(): void {
    void this.scene.set('/panels/agentDock', this.open() ? 'closed' : 'open');
  }

  protected send(): void {
    if (this.busy()) {
      return;
    }
    this.voice.interrupt();
    this.agent.sendText(this.draft());
    this.draft.set('');
    // El binding [value] puede no ver el cambio si no hubo detección entre teclear y enviar.
    const el = this.input()?.nativeElement;
    if (el) el.value = '';
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    } else if (event.key === 'Escape') {
      this.toggle();
    }
  }

  protected onMic(): void {
    if (!this.voice.privacyAcknowledged() && !this.voice.listening()) {
      this.askPrivacy.set(true);
      return;
    }
    this.voice.toggleListening();
  }

  protected acceptPrivacy(): void {
    this.askPrivacy.set(false);
    this.voice.acknowledgePrivacy();
    this.voice.toggleListening();
  }

  protected retry(): void {
    this.agent.disconnect();
    this.agent.connect();
  }
}
