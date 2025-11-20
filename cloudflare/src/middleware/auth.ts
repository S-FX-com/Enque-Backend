import { Context as HonoContext, Next } from 'hono';
import { Env, Context } from '../types/env';
import { extractBearerToken, verifyToken } from '../utils/jwt';
import { unauthorized } from '../utils/response';

/**
 * Authentication middleware
 * Verifies JWT token and attaches agent info to context
 */
export async function authMiddleware(c: HonoContext<{ Bindings: Env; Variables: Context }>, next: Next) {
  const authHeader = c.req.header('Authorization');
  const token = extractBearerToken(authHeader);

  if (!token) {
    return unauthorized('Missing authentication token');
  }

  try {
    const payload = await verifyToken(token, c.env.JWT_SECRET);

    // Attach agent info to context
    c.set('agent', {
      id: payload.sub,
      email: payload.email,
      role: payload.role,
      workspaceId: payload.workspaceId,
    });

    await next();
  } catch (error) {
    return unauthorized('Invalid or expired token');
  }
}

/**
 * Optional authentication middleware
 * Attaches agent info if token is present, but doesn't fail if missing
 */
export async function optionalAuthMiddleware(c: HonoContext<{ Bindings: Env; Variables: Context }>, next: Next) {
  const authHeader = c.req.header('Authorization');
  const token = extractBearerToken(authHeader);

  if (token) {
    try {
      const payload = await verifyToken(token, c.env.JWT_SECRET);
      c.set('agent', {
        id: payload.sub,
        email: payload.email,
        role: payload.role,
        workspaceId: payload.workspaceId,
      });
    } catch (error) {
      // Silently fail for optional auth
    }
  }

  await next();
}

/**
 * Role-based access control middleware
 * Requires specific role(s) to access route
 */
export function requireRole(...roles: string[]) {
  return async (c: HonoContext<{ Bindings: Env; Variables: Context }>, next: Next) => {
    const agent = c.get('agent');

    if (!agent) {
      return unauthorized('Authentication required');
    }

    if (!roles.includes(agent.role)) {
      return new Response(
        JSON.stringify({
          success: false,
          error: {
            code: 'FORBIDDEN',
            message: 'Insufficient permissions',
          },
        }),
        {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    }

    await next();
  };
}
