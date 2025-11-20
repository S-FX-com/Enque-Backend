import { Context as HonoContext, Next } from 'hono';
import { Env, Context } from '../types/env';
import { serverError } from '../utils/response';
import { createLogger } from '../utils/logger';
import { ZodError } from 'zod';

/**
 * Global error handling middleware
 * Catches all errors and returns standardized error responses
 */
export async function errorMiddleware(c: HonoContext<{ Bindings: Env; Variables: Context }>, next: Next) {
  try {
    await next();
  } catch (error) {
    const logger = createLogger(c.env.LOG_LEVEL || 'info');
    const requestId = c.get('requestId') || 'unknown';

    // Log the error
    logger.error('Request error', {
      requestId,
      error: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined,
    });

    // Handle Zod validation errors
    if (error instanceof ZodError) {
      return new Response(
        JSON.stringify({
          success: false,
          error: {
            code: 'VALIDATION_ERROR',
            message: 'Validation failed',
            details: error.errors.map((e) => ({
              path: e.path.join('.'),
              message: e.message,
            })),
          },
        }),
        {
          status: 422,
          headers: {
            'Content-Type': 'application/json',
            'X-Request-ID': requestId,
          },
        }
      );
    }

    // Handle generic errors
    const message = error instanceof Error ? error.message : 'An unexpected error occurred';

    return new Response(
      JSON.stringify({
        success: false,
        error: {
          code: 'INTERNAL_ERROR',
          message: c.env.ENVIRONMENT === 'production' ? 'Internal server error' : message,
        },
      }),
      {
        status: 500,
        headers: {
          'Content-Type': 'application/json',
          'X-Request-ID': requestId,
        },
      }
    );
  }
}
