// Cliente WebSocket del agente. TypeScript puro: no importa @angular/*.
import type { ClientMessage, ServerMessage } from './agent-protocol';

export type ConnectionState = 'connecting' | 'open' | 'closed';

export interface AgentClientHandlers {
  onMessage: (message: ServerMessage) => void;
  onState: (state: ConnectionState) => void;
}

export class AgentClient {
  private socket: WebSocket | null = null;

  constructor(
    private readonly url: string,
    private readonly handlers: AgentClientHandlers,
  ) {}

  connect(onOpen: () => void): void {
    this.close();
    this.handlers.onState('connecting');
    const socket = new WebSocket(this.url);
    this.socket = socket;
    socket.onopen = () => {
      this.handlers.onState('open');
      onOpen();
    };
    socket.onmessage = (event) => {
      try {
        this.handlers.onMessage(JSON.parse(String(event.data)) as ServerMessage);
      } catch {
        // Mensaje no JSON: se ignora.
      }
    };
    socket.onclose = () => {
      if (this.socket === socket) {
        this.socket = null;
        this.handlers.onState('closed');
      }
    };
  }

  send(message: ClientMessage): boolean {
    if (this.socket?.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.socket.send(JSON.stringify(message));
    return true;
  }

  close(): void {
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }
}

/** URL absoluta ws(s):// a partir de la base de la API (p. ej. "/api"). */
export function agentSocketUrl(apiBaseUrl: string): string {
  const http = new URL(`${apiBaseUrl}/agent/session`, document.baseURI);
  http.protocol = http.protocol === 'https:' ? 'wss:' : 'ws:';
  return http.href;
}
