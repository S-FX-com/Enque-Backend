import { Context as HonoContext, Next } from 'hono';
import { Env, Context } from '../types/env';

interface RateLimitConfig {
  maxRequests: number;
  windowMs: number;
  keyPrefix?: string;
}

/**
 * Rate limiting middleware using Cloudflare KV
 */
export function rateLimitMiddleware(config: RateLimitConfig) {
  return async (c: HonoContext<{ Bindings: Env; Variables: Context }>, next: Next) => {
    // Skip rate limiting if disabled
    if (!c.env.ENABLE_RATE_LIMITING) {
      return next();
    }

    const { maxRequests, windowMs, keyPrefix = 'ratelimit' } = config;

    // Get identifier (IP or user ID)
    const identifier = c.get('agent')?.id || c.req.header('CF-Connecting-IP') || 'anonymous';
    const key = `${keyPrefix}:${identifier}`;

    // Get current count from KV
    const currentData = await c.env.CACHE.get(key, 'json') as { count: number; resetAt: number } | null;

    const now = Date.now();

    if (currentData) {
      // Check if window has expired
      if (now > currentData.resetAt) {
        // Reset window
        await c.env.CACHE.put(
          key,
          JSON.stringify({ count: 1, resetAt: now + windowMs }),
          { expirationTtl: Math.ceil(windowMs / 1000) }
        );
      } else {
        // Check if limit exceeded
        if (currentData.count >= maxRequests) {
          const retryAfter = Math.ceil((currentData.resetAt - now) / 1000);

          return new Response(
            JSON.stringify({
              success: false,
              error: {
                code: 'RATE_LIMIT_EXCEEDED',
                message: 'Too many requests',
              },
            }),
            {
              status: 429,
              headers: {
                'Content-Type': 'application/json',
                'Retry-After': retryAfter.toString(),
                'X-RateLimit-Limit': maxRequests.toString(),
                'X-RateLimit-Remaining': '0',
                'X-RateLimit-Reset': currentData.resetAt.toString(),
              },
            }
          );
        }

        // Increment count
        await c.env.CACHE.put(
          key,
          JSON.stringify({ count: currentData.count + 1, resetAt: currentData.resetAt }),
          { expirationTtl: Math.ceil((currentData.resetAt - now) / 1000) }
        );

        // Add rate limit headers
        c.res.headers.set('X-RateLimit-Limit', maxRequests.toString());
        c.res.headers.set('X-RateLimit-Remaining', (maxRequests - currentData.count - 1).toString());
        c.res.headers.set('X-RateLimit-Reset', currentData.resetAt.toString());
      }
    } else {
      // First request in this window
      const resetAt = now + windowMs;
      await c.env.CACHE.put(
        key,
        JSON.stringify({ count: 1, resetAt }),
        { expirationTtl: Math.ceil(windowMs / 1000) }
      );

      c.res.headers.set('X-RateLimit-Limit', maxRequests.toString());
      c.res.headers.set('X-RateLimit-Remaining', (maxRequests - 1).toString());
      c.res.headers.set('X-RateLimit-Reset', resetAt.toString());
    }

    await next();
  };
}

/**
 * Predefined rate limit configurations
 */
export const RateLimits = {
  // Strict limit for auth endpoints (prevent brute force)
  auth: { maxRequests: 10, windowMs: 15 * 60 * 1000, keyPrefix: 'rl:auth' }, // 10 requests per 15 minutes

  // Standard API limit
  api: { maxRequests: 100, windowMs: 60 * 1000, keyPrefix: 'rl:api' }, // 100 requests per minute

  // Generous limit for read operations
  read: { maxRequests: 200, windowMs: 60 * 1000, keyPrefix: 'rl:read' }, // 200 requests per minute

  // Strict limit for write operations
  write: { maxRequests: 50, windowMs: 60 * 1000, keyPrefix: 'rl:write' }, // 50 requests per minute
};
