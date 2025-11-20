import { create } from 'zustand';
import { authService, Agent } from '../services/auth';

interface AuthState {
  agent: Agent | null;
  isLoading: boolean;
  error: string | null;

  // Actions
  login: (email: string, password: string) => Promise<void>;
  register: (data: any) => Promise<void>;
  logout: () => Promise<void>;
  fetchCurrentAgent: () => Promise<void>;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  agent: null,
  isLoading: false,
  error: null,

  login: async (email: string, password: string) => {
    set({ isLoading: true, error: null });
    try {
      const response = await authService.login({ email, password });
      const agent = await authService.getCurrentAgent();
      set({ agent, isLoading: false });
    } catch (error: any) {
      set({ error: error.message || 'Login failed', isLoading: false });
      throw error;
    }
  },

  register: async (data: any) => {
    set({ isLoading: true, error: null });
    try {
      const response = await authService.register(data);
      const agent = await authService.getCurrentAgent();
      set({ agent, isLoading: false });
    } catch (error: any) {
      set({ error: error.message || 'Registration failed', isLoading: false });
      throw error;
    }
  },

  logout: async () => {
    set({ isLoading: true });
    try {
      await authService.logout();
      set({ agent: null, isLoading: false });
    } catch (error: any) {
      set({ isLoading: false });
    }
  },

  fetchCurrentAgent: async () => {
    if (!authService.isAuthenticated()) {
      set({ agent: null });
      return;
    }

    set({ isLoading: true });
    try {
      const agent = await authService.getCurrentAgent();
      set({ agent, isLoading: false });
    } catch (error: any) {
      set({ agent: null, isLoading: false });
    }
  },

  clearError: () => set({ error: null }),
}));
