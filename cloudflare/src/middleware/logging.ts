import { Context as HonoContext, Next } from 'hono';
import { Env, Context } from '../types/env';
import { generateId } from '../utils/crypto';
import { createLogger } from '../utils/logger';

/**
 * Request logging middleware
 * Logs all incoming requests with timing information
 */
export async function loggingMiddleware(c: HonoContext<{ Bindings: Env; Variables: Context }>, next: Next) {
  const requestId = generateId('req');
  const startTime = Date.now();

  // Set request ID and start time in context
  c.set('requestId', requestId);
  c.set('startTime', startTime);

  const logger = createLogger(c.env.LOG_LEVEL || 'info');

  // Log incoming request
  logger.info('Incoming request', {
    requestId,
    method: c.req.method,
    path: c.req.path,
    userAgent: c.req.header('user-agent'),
  });

  await next();

  // Log response
  const duration = Date.now() - startTime;
  logger.info('Request completed', {
    requestId,
    method: c.req.method,
    path: c.req.path,
    status: c.res.status,
    duration: `${duration}ms`,
  });

  // Add request ID to response headers
  c.res.headers.set('X-Request-ID', requestId);
}
