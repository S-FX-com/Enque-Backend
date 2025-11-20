/**
 * Application configuration
 */

const getApiUrl = () => {
  // In development, use proxy
  if (import.meta.env.DEV) {
    return '/api';
  }

  // In production, use environment variable or default
  return import.meta.env.VITE_API_URL || 'https://stg.enque.cc';
};

export const config = {
  apiUrl: getApiUrl(),
  wsUrl: import.meta.env.VITE_WS_URL || 'wss://stg.enque.cc',
  appName: 'Enque',
  version: '1.0.0',
} as const;
