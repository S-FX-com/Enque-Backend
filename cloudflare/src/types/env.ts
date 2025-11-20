/**
 * Cloudflare Workers Environment Bindings
 */
export interface Env {
  // D1 Database
  DB: D1Database;

  // R2 Storage
  STORAGE: R2Bucket;

  // KV Cache
  CACHE: KVNamespace;

  // Durable Objects
  REALTIME: DurableObjectNamespace;

  // Secrets (set via wrangler secret put)
  JWT_SECRET: string;
  MICROSOFT_CLIENT_ID: string;
  MICROSOFT_CLIENT_SECRET: string;
  MICROSOFT_TENANT_ID: string;
  DATABASE_ENCRYPTION_KEY: string;

  // Environment Variables
  ENVIRONMENT: 'staging' | 'production';
  FRONTEND_URL: string;
  API_BASE_URL: string;
  MICROSOFT_REDIRECT_URI: string;
  MICROSOFT_GRAPH_URL: string;
  MICROSOFT_SCOPE: string;
  EMAIL_SYNC_ENABLED: boolean;
  EMAIL_SYNC_BATCH_SIZE: number;
  ENABLE_RATE_LIMITING: boolean;
  LOG_LEVEL: 'debug' | 'info' | 'warn' | 'error';
}

/**
 * Context object passed through middleware
 */
export interface Context {
  // Authenticated agent
  agent?: {
    id: string;
    email: string;
    role: string;
    workspaceId?: string;
  };

  // Request metadata
  requestId: string;
  startTime: number;
}
