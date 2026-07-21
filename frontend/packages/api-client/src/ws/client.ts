/** WebSocket client with auto-reconnect and channel subscription. */

import type { Role, WSChannel, WSMessage } from '@robots/shared-types';

type MessageHandler = (data: Record<string, unknown>) => void;

function defaultWebSocketBase(): string {
  if (typeof window === 'undefined') return 'ws://127.0.0.1:8000/ws';
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws`;
}

const configuredWsBase = import.meta.env?.VITE_WS_BASE;
const WS_BASE = configuredWsBase
  ? configuredWsBase.startsWith('ws')
    ? configuredWsBase
    : `${typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${typeof window !== 'undefined' ? window.location.host : '127.0.0.1:8000'}${configuredWsBase}`
  : defaultWebSocketBase();

export class WSClient {
  private ws: WebSocket | null = null;
  private role: Role;
  private channels: Set<WSChannel>;
  private handlers: Map<WSChannel, Set<MessageHandler>> = new Map();
  private reconnectAttempts = 0;
  private maxReconnect = 10;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private closed = false;

  constructor(role: Role, channels: WSChannel[] = ['devices', 'tasks', 'alerts', 'events', 'estop', 'script']) {
    this.role = role;
    this.channels = new Set(channels);
  }

  connect(): void {
    this.closed = false;
    const channelStr = Array.from(this.channels).join(',');
    // 支持 token 认证
    const token = typeof localStorage !== 'undefined' ? localStorage.getItem('scheduler_token') : null;
    const url = `${WS_BASE}?channels=${channelStr}`;
    this.ws = token ? new WebSocket(url, [`jwt.${token}`]) : new WebSocket(url);

    this.ws.onopen = () => {
      console.log('[WS] connected');
      this.reconnectAttempts = 0;
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        const channel = msg.channel as WSChannel;
        const handlers = this.handlers.get(channel);
        if (handlers) {
          handlers.forEach((h) => h(msg.data));
        }
      } catch (e) {
        console.error('[WS] parse error', e);
      }
    };

    this.ws.onclose = () => {
      console.log('[WS] closed');
      if (!this.closed) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (e) => {
      console.error('[WS] error', e);
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnect) {
      console.warn('[WS] max reconnect attempts reached');
      return;
    }
    this.reconnectAttempts++;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 30000);
    console.log(`[WS] reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  subscribe(channel: WSChannel, handler: MessageHandler): () => void {
    if (!this.handlers.has(channel)) {
      this.handlers.set(channel, new Set());
    }
    this.handlers.get(channel)!.add(handler);
    // Send subscribe message to server
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'subscribe', channel }));
    }
    return () => {
      this.handlers.get(channel)?.delete(handler);
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'unsubscribe', channel }));
      }
    };
  }

  close(): void {
    this.closed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    this.ws?.close();
    this.ws = null;
  }
}

/** Create a singleton WS client. */
let _wsClient: WSClient | null = null;

export function getWSClient(role: Role, channels?: WSChannel[]): WSClient {
  if (!_wsClient) {
    _wsClient = new WSClient(role, channels);
    _wsClient.connect();
  }
  return _wsClient;
}

export function closeWSClient(): void {
  if (_wsClient) {
    _wsClient.close();
    _wsClient = null;
  }
}
