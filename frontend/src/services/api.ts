import axios, { AxiosError, AxiosInstance } from 'axios';
import { config } from '../config';

/**
 * API Response format from backend
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
 * API Client class
 */
class APIClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: config.apiUrl,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Request interceptor - add auth token
    this.client.interceptors.request.use(
      (config) => {
        const token = localStorage.getItem('auth_token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Response interceptor - handle errors
    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError<ApiResponse>) => {
        if (error.response?.status === 401) {
          // Unauthorized - clear token and redirect to login
          localStorage.removeItem('auth_token');
          window.location.href = '/login';
        }
        return Promise.reject(error);
      }
    );
  }

  /**
   * GET request
   */
  async get<T>(url: string, params?: any): Promise<T> {
    const response = await this.client.get<ApiResponse<T>>(url, { params });

    if (!response.data.success) {
      throw new Error(response.data.error?.message || 'Request failed');
    }

    return response.data.data!;
  }

  /**
   * POST request
   */
  async post<T>(url: string, data?: any): Promise<T> {
    const response = await this.client.post<ApiResponse<T>>(url, data);

    if (!response.data.success) {
      throw new Error(response.data.error?.message || 'Request failed');
    }

    return response.data.data!;
  }

  /**
   * PATCH request
   */
  async patch<T>(url: string, data?: any): Promise<T> {
    const response = await this.client.patch<ApiResponse<T>>(url, data);

    if (!response.data.success) {
      throw new Error(response.data.error?.message || 'Request failed');
    }

    return response.data.data!;
  }

  /**
   * DELETE request
   */
  async delete<T>(url: string): Promise<T> {
    const response = await this.client.delete<ApiResponse<T>>(url);

    if (!response.data.success) {
      throw new Error(response.data.error?.message || 'Request failed');
    }

    return response.data.data!;
  }

  /**
   * Set authentication token
   */
  setAuthToken(token: string) {
    localStorage.setItem('auth_token', token);
  }

  /**
   * Clear authentication token
   */
  clearAuthToken() {
    localStorage.removeItem('auth_token');
  }

  /**
   * Get authentication token
   */
  getAuthToken(): string | null {
    return localStorage.getItem('auth_token');
  }
}

// Export singleton instance
export const api = new APIClient();
