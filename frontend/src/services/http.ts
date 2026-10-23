import axios from 'axios';

const API_KEY_STORAGE_KEY = 'agenticrag_api_key';

export function getStoredApiKey() {
  const envKey = import.meta.env.VITE_API_KEY || '';
  if (typeof window === 'undefined') return envKey;
  return window.localStorage.getItem(API_KEY_STORAGE_KEY) || envKey;
}

export function setStoredApiKey(value: string) {
  if (typeof window === 'undefined') return;
  const normalized = value.trim();
  if (normalized) {
    window.localStorage.setItem(API_KEY_STORAGE_KEY, normalized);
  } else {
    window.localStorage.removeItem(API_KEY_STORAGE_KEY);
  }
}

export function getAuthHeaders(): Record<string, string> {
  const apiKey = getStoredApiKey();
  return apiKey ? { 'X-API-Key': apiKey } : {};
}

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
});

http.interceptors.request.use((config) => {
  const apiKey = getStoredApiKey();
  if (apiKey) {
    config.headers = config.headers || {};
    config.headers['X-API-Key'] = apiKey;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (import.meta.env.DEV) {
      console.error('[API ERROR]', {
        url: error?.config?.url,
        method: error?.config?.method,
        baseURL: error?.config?.baseURL,
        status: error?.response?.status,
        data: error?.response?.data,
        message: error?.message,
      });
    }
    return Promise.reject(error);
  },
);
