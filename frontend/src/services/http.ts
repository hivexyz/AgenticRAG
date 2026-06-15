import axios from 'axios';

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
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
