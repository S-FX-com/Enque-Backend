import { Context as HonoContext, Next } from 'hono';
import { cors as honoCors } from 'hono/cors';
import { Env } from '../types/env';

/**
 * CORS middleware configuration
 */
export function corsMiddleware() {
  return honoCors({
    origin: (origin) => {
      // Allow all enque.cc subdomains
      if (origin.endsWith('.enque.cc') || origin === 'https://app.enque.cc' || origin === 'https://stg.enque.cc') {
        return origin;
      }

      // Allow localhost for development
      if (origin.startsWith('http://localhost:') || origin.startsWith('http://127.0.0.1:')) {
        return origin;
      }

      return 'https://app.enque.cc'; // Default fallback
    },
    credentials: true,
    allowMethods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    allowHeaders: ['Content-Type', 'Authorization', 'X-Requested-With'],
    exposeHeaders: ['Content-Length', 'X-Request-ID'],
    maxAge: 86400, // 24 hours
  });
}
