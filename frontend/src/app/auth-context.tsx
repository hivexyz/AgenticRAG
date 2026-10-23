import { createContext, useContext } from 'react';
import type { AuthInfo } from '../services/auth';

export interface AuthContextValue {
  auth: AuthInfo;
  tenantId: string;
  reloadAuth: () => Promise<void>;
}

export const defaultAuthInfo: AuthInfo = {
  tenant_id: 'default',
  authenticated: false,
  api_key_name: 'anonymous',
  scopes: ['read', 'write'],
  can_write: true,
  auth_method: 'anonymous',
  subject: null,
};

export const AuthContext = createContext<AuthContextValue>({
  auth: defaultAuthInfo,
  tenantId: defaultAuthInfo.tenant_id,
  reloadAuth: async () => undefined,
});

export function useAuthContext() {
  return useContext(AuthContext);
}
