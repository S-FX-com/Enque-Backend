import { DurableObject } from 'cloudflare:workers';

export interface RealtimeMessage {
  type: string;
  payload: any;
  workspaceId?: string;
  agentId?: string;
  timestamp: number;
}

/**
 * Durable Object for real-time WebSocket connections
 * Handles ticket updates, comments, and other real-time events
 */
export class RealtimeHandler extends DurableObject {
  private sessions: Map<WebSocket, { agentId: string; workspaceId: string }>;

  constructor(state: DurableObjectState, env: any) {
    super(state, env);
    this.sessions = new Map();
  }

  /**
   * Handle HTTP requests (WebSocket upgrades)
   */
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    // Only allow WebSocket upgrade requests
    if (request.headers.get('Upgrade') !== 'websocket') {
      return new Response('Expected WebSocket', { status: 426 });
    }

    // Get agent and workspace from query params
    const agentId = url.searchParams.get('agentId');
    const workspaceId = url.searchParams.get('workspaceId');

    if (!agentId || !workspaceId) {
      return new Response('Missing agentId or workspaceId', { status: 400 });
    }

    // Create WebSocket pair
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    // Accept the WebSocket connection
    this.ctx.acceptWebSocket(server);

    // Store session info
    this.sessions.set(server, { agentId, workspaceId });

    // Send welcome message
    server.send(
      JSON.stringify({
        type: 'connected',
        payload: {
          message: 'Connected to Enque real-time server',
          workspaceId,
          agentId,
        },
        timestamp: Date.now(),
      })
    );

    return new Response(null, {
      status: 101,
      webSocket: client,
    });
  }

  /**
   * Handle incoming WebSocket messages
   */
  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    const session = this.sessions.get(ws);

    if (!session) {
      return;
    }

    try {
      if (typeof message === 'string') {
        const data: RealtimeMessage = JSON.parse(message);

        // Handle different message types
        switch (data.type) {
          case 'ping':
            ws.send(JSON.stringify({ type: 'pong', timestamp: Date.now() }));
            break;

          case 'subscribe':
            // Subscribe to specific channels (tickets, comments, etc.)
            ws.send(
              JSON.stringify({
                type: 'subscribed',
                payload: data.payload,
                timestamp: Date.now(),
              })
            );
            break;

          case 'broadcast':
            // Broadcast message to all clients in the same workspace
            this.broadcast(data, session.workspaceId);
            break;

          default:
            console.log('Unknown message type:', data.type);
        }
      }
    } catch (error) {
      console.error('Error processing WebSocket message:', error);
      ws.send(
        JSON.stringify({
          type: 'error',
          payload: { message: 'Failed to process message' },
          timestamp: Date.now(),
        })
      );
    }
  }

  /**
   * Handle WebSocket closure
   */
  async webSocketClose(ws: WebSocket, code: number, reason: string): Promise<void> {
    this.sessions.delete(ws);
    console.log(`WebSocket closed: ${code} ${reason}`);
  }

  /**
   * Handle WebSocket errors
   */
  async webSocketError(ws: WebSocket, error: Error): Promise<void> {
    console.error('WebSocket error:', error);
    this.sessions.delete(ws);
  }

  /**
   * Broadcast message to all clients in a workspace
   */
  private broadcast(message: RealtimeMessage, workspaceId: string): void {
    const messageStr = JSON.stringify({
      ...message,
      timestamp: Date.now(),
    });

    for (const [ws, session] of this.sessions.entries()) {
      if (session.workspaceId === workspaceId) {
        try {
          ws.send(messageStr);
        } catch (error) {
          console.error('Error broadcasting to client:', error);
          this.sessions.delete(ws);
        }
      }
    }
  }

  /**
   * Public method to send updates to clients (called from API)
   */
  async notifyClients(workspaceId: string, message: RealtimeMessage): Promise<void> {
    this.broadcast(message, workspaceId);
  }
}
