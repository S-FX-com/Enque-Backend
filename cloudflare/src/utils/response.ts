/**
 * Standard API Response Format
 */
export interface ApiResponse<T = any> {
  success: boolean;
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: any;
  };
  meta?: {
    page?: number;
    limit?: number;
    total?: number;
    [key: string]: any;
  };
}

/**
 * Create a success response
 */
export function success<T>(data: T, meta?: ApiResponse['meta']): Response {
  const response: ApiResponse<T> = {
    success: true,
    data,
  };

  if (meta) {
    response.meta = meta;
  }

  return new Response(JSON.stringify(response), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

/**
 * Create an error response
 */
export function error(
  message: string,
  code: string = 'ERROR',
  status: number = 400,
  details?: any
): Response {
  const response: ApiResponse = {
    success: false,
    error: {
      code,
      message,
      details,
    },
  };

  return new Response(JSON.stringify(response), {
    status,
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

/**
 * Create a 404 Not Found response
 */
export function notFound(message: string = 'Resource not found'): Response {
  return error(message, 'NOT_FOUND', 404);
}

/**
 * Create a 401 Unauthorized response
 */
export function unauthorized(message: string = 'Unauthorized'): Response {
  return error(message, 'UNAUTHORIZED', 401);
}

/**
 * Create a 403 Forbidden response
 */
export function forbidden(message: string = 'Forbidden'): Response {
  return error(message, 'FORBIDDEN', 403);
}

/**
 * Create a 422 Validation Error response
 */
export function validationError(details: any): Response {
  return error('Validation failed', 'VALIDATION_ERROR', 422, details);
}

/**
 * Create a 500 Internal Server Error response
 */
export function serverError(message: string = 'Internal server error'): Response {
  return error(message, 'INTERNAL_ERROR', 500);
}

/**
 * Create a 201 Created response
 */
export function created<T>(data: T): Response {
  const response: ApiResponse<T> = {
    success: true,
    data,
  };

  return new Response(JSON.stringify(response), {
    status: 201,
    headers: {
      'Content-Type': 'application/json',
    },
  });
}

/**
 * Create a 204 No Content response
 */
export function noContent(): Response {
  return new Response(null, {
    status: 204,
  });
}
