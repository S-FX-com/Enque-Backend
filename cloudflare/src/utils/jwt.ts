import { SignJWT, jwtVerify } from 'jose';

export interface JWTPayload {
  sub: string; // Agent ID
  email: string;
  role: string;
  workspaceId?: string;
  iat?: number;
  exp?: number;
}

/**
 * Create a JWT token
 */
export async function createToken(payload: JWTPayload, secret: string, expiresIn: string = '7d'): Promise<string> {
  const encoder = new TextEncoder();
  const secretKey = encoder.encode(secret);

  // Convert expiresIn to seconds
  const expiration = parseExpiresIn(expiresIn);

  const token = await new SignJWT({ ...payload })
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .setIssuedAt()
    .setExpirationTime(Math.floor(Date.now() / 1000) + expiration)
    .sign(secretKey);

  return token;
}

/**
 * Verify and decode a JWT token
 */
export async function verifyToken(token: string, secret: string): Promise<JWTPayload> {
  const encoder = new TextEncoder();
  const secretKey = encoder.encode(secret);

  try {
    const { payload } = await jwtVerify(token, secretKey);
    return payload as JWTPayload;
  } catch (error) {
    throw new Error('Invalid or expired token');
  }
}

/**
 * Parse expiresIn string to seconds
 */
function parseExpiresIn(expiresIn: string): number {
  const units: Record<string, number> = {
    s: 1,
    m: 60,
    h: 3600,
    d: 86400,
    w: 604800,
  };

  const match = expiresIn.match(/^(\d+)([smhdw])$/);
  if (!match) {
    throw new Error('Invalid expiresIn format');
  }

  const [, value, unit] = match;
  return parseInt(value) * units[unit];
}

/**
 * Extract token from Authorization header
 */
export function extractBearerToken(authHeader: string | null): string | null {
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return null;
  }

  return authHeader.substring(7);
}
