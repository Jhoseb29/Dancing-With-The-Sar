import { DestroyRef, Injectable, inject, signal } from '@angular/core';
import { AgentClient, ConnectionState, agentSocketUrl } from '../agent/agent-client';
import { AgentStatus, ServerMessage } from '../agent/agent-protocol';
import { RuntimeConfigService } from '../config/runtime-config.service';
import { SceneStore } from '../scene/scene.store';

export interface TranscriptEntry {
  id: number;
  role: 'user' | 'agent' | 'system';
  text: string;
  timeMs: number;
}

/**
 * Adaptador Angular ↔ agente (OpenSpec 08). Mantiene la transcripción como Signals,
 * aplica los parches del agente en el shadow (origen `agent`) y devuelve el resultado.
 */
@Injectable({ providedIn: 'root' })
export class AgentService {
  private readonly scene = inject(SceneStore);
  private readonly apiBaseUrl = inject(RuntimeConfigService).value.apiBaseUrl;
  private client: AgentClient | null = null;
  private nextId = 1;

  readonly connection = signal<ConnectionState>('closed');
  readonly status = signal<AgentStatus>('idle');
  readonly activeTool = signal<string | null>(null);
  readonly transcript = signal<TranscriptEntry[]>([]);
  readonly error = signal<{ code: string; message: string } | null>(null);

  constructor() {
    inject(DestroyRef).onDestroy(() => this.client?.close());
  }

  /** Abre la sesión si no está abierta (el agente saluda al conectar). */
  connect(): void {
    if (this.connection() !== 'closed') {
      return;
    }
    this.error.set(null);
    this.client = new AgentClient(agentSocketUrl(this.apiBaseUrl), {
      onMessage: (message) => void this.onMessage(message),
      onState: (state) => {
        this.connection.set(state);
        if (state === 'closed') {
          this.status.set('idle');
          this.activeTool.set(null);
        }
      },
    });
    this.client.connect(() => {
      this.client?.send({
        type: 'session.start',
        lang: this.scene.lang(),
        scene: this.scene.state(),
        reported: this.scene.reported(),
      });
    });
  }

  disconnect(): void {
    this.client?.close();
    this.client = null;
  }

  sendText(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) {
      return;
    }
    this.error.set(null);
    this.append('user', trimmed);
    const sent = this.client?.send({
      type: 'user.text',
      text: trimmed,
      scene: this.scene.state(),
      reported: this.scene.reported(),
    });
    if (!sent) {
      this.error.set({ code: 'disconnected', message: '' });
    }
  }

  /** Voz grabada: el backend la transcribe y responde `user.transcript`. */
  sendAudio(data: string, mime: string): boolean {
    this.error.set(null);
    const sent = this.client?.send({
      type: 'user.audio',
      mime,
      data,
      scene: this.scene.state(),
      reported: this.scene.reported(),
    });
    if (!sent) {
      this.error.set({ code: 'disconnected', message: '' });
    }
    return !!sent;
  }

  interrupt(): void {
    this.client?.send({ type: 'user.interrupt' });
  }

  private async onMessage(message: ServerMessage): Promise<void> {
    switch (message.type) {
      case 'agent.status':
        this.status.set(message.status);
        this.activeTool.set(message.status === 'acting' ? (message.tool ?? null) : null);
        break;
      case 'agent.text':
        this.append('agent', message.text);
        break;
      case 'user.transcript':
        this.append('user', message.text);
        break;
      case 'scene.patch': {
        const result = await this.scene.patch({ origin: 'agent', baseVersion: message.baseVersion, ops: message.ops });
        // Dar tiempo a los motores para reportar (navegación, cámara) antes de responder.
        await new Promise((resolve) => setTimeout(resolve, 400));
        this.client?.send({
          type: 'scene.patch.result',
          patchId: message.patchId,
          ok: result.ok,
          reason: result.ok ? undefined : result.reason,
          version: this.scene.state().version,
          scene: this.scene.state(),
          reported: this.scene.reported(),
        });
        break;
      }
      case 'agent.turn.end':
        this.activeTool.set(null);
        break;
      case 'error':
        this.error.set({ code: message.code, message: message.message });
        break;
    }
  }

  private append(role: TranscriptEntry['role'], text: string): void {
    this.transcript.update((entries) => [...entries.slice(-49), { id: this.nextId++, role, text, timeMs: Date.now() }]);
  }
}
