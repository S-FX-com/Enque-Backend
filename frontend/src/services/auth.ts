import { api } from './api';

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterData {
  email: string;
  displayName: string;
  password: string;
  workspaceName?: string;
  workspaceSubdomain?: string;
}

export interface AuthResponse {
  token: string;
  agent: {
    id: string;
    email: string;
    displayName: string;
    role: string;
    avatarUrl?: string;
  };
  workspaces?: any[];
  workspaceId?: string;
}

export interface MicrosoftAuthResponse {
  authUrl: string;
  state: string;
}

export interface Agent {
  id: string;
  email: string;
  displayName: string;
  role: string;
  avatarUrl?: string;
  authMethod: string;
  isActive: boolean;
  workspaces: Array<{
    id: string;
    name: string;
    subdomain: string;
    role: string;
  }>;
}

/**
 * Authentication Service
 */
export const authService = {
  /**
   * Login with email and password
   */
  async login(credentials: LoginCredentials): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/v1/auth/login', credentials);
    api.setAuthToken(response.token);
    return response;
  },

  /**
   * Register new agent and workspace
   */
  async register(data: RegisterData): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/v1/auth/register', data);
    api.setAuthToken(response.token);
    return response;
  },

  /**
   * Get Microsoft OAuth URL
   */
  async getMicrosoftAuthUrl(): Promise<MicrosoftAuthResponse> {
    return api.get<MicrosoftAuthResponse>('/v1/auth/microsoft');
  },

  /**
   * Handle Microsoft OAuth callback
   */
  async handleMicrosoftCallback(code: string, state?: string): Promise<AuthResponse> {
    const params = new URLSearchParams({ code });
    if (state) params.append('state', state);

    const response = await api.get<AuthResponse>(`/v1/auth/microsoft/callback?${params}`);
    api.setAuthToken(response.token);
    return response;
  },

  /**
   * Get current authenticated agent
   */
  async getCurrentAgent(): Promise<Agent> {
    return api.get<Agent>('/v1/auth/me');
  },

  /**
   * Logout
   */
  async logout(): Promise<void> {
    try {
      await api.post('/v1/auth/logout');
    } finally {
      api.clearAuthToken();
    }
  },

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    return !!api.getAuthToken();
  },
};
