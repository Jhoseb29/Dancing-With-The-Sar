import type { PatchOp, ReportedState, SceneState } from '../scene/scene.model';

/** Mensajes del WebSocket /api/agent/session — backend/shared/schemas/agent-message.schema.json. */

export type ClientMessage =
  | { type: 'session.start'; lang: 'es' | 'en'; scene: SceneState; reported: ReportedState }
  | { type: 'user.text'; text: string; scene: SceneState; reported: ReportedState }
  | { type: 'user.audio'; mime: string; data: string; scene: SceneState; reported: ReportedState }
  | {
      type: 'scene.patch.result';
      patchId: string;
      ok: boolean;
      reason?: string;
      version?: number;
      scene: SceneState;
      reported: ReportedState;
    }
  | { type: 'user.interrupt' };

export type AgentStatus = 'ready' | 'transcribing' | 'thinking' | 'acting' | 'idle';

export type ServerMessage =
  | { type: 'agent.status'; status: AgentStatus; tool?: string }
  | { type: 'agent.text'; turnId: string; text: string }
  | { type: 'user.transcript'; text: string }
  | { type: 'scene.patch'; patchId: string; baseVersion: number; ops: PatchOp[] }
  | { type: 'agent.turn.end'; turnId: string }
  | {
      type: 'error';
      code:
        | 'llm_not_configured'
        | 'llm_error'
        | 'rate_limited'
        | 'too_long'
        | 'bad_message'
        | 'no_speech'
        | 'stt_error'
        | 'audio_too_large';
      message: string;
    };
