import { http } from './http';

export interface AuthInfo {
  tenant_id: string;
  authenticated: boolean;
  api_key_name: string;
  scopes: string[];
  can_write: boolean;
  auth_method: string;
  subject?: string | null;
}

export async function fetchAuthMe() {
  const response = await http.get<AuthInfo>('/auth/me');
  return response.data;
}
