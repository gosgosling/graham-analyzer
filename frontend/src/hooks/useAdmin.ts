import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../services/companies.api';

export interface AuthUser {
  id: number;
  email: string;
  name: string;
  role: 'user' | 'admin';
  email_verified: boolean;
  created_at: string | null;
  password_changed_at: string | null;
  consent_at: string | null;
}

export interface AuthMe {
  user: AuthUser | null;
  expires_at: string | null;
  mail_configured: boolean;
}

export const AUTH_KEY = ['auth-me'];

/**
 * Кто вошёл. Сервер знает это по cookie сессии; сам идентификатор сессии
 * скрипту недоступен (HttpOnly), поэтому спрашиваем. Прятать кнопки —
 * удобство, а не защита: решает всё равно сервер.
 */
export function useAuth(): { user: AuthUser | null; checking: boolean; me: AuthMe | undefined } {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: AUTH_KEY,
    queryFn: async () => (await api.get<AuthMe>('/auth/me')).data,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: true,
    retry: false,
  });
  useEffect(() => {
    const expired = () => queryClient.invalidateQueries({ queryKey: AUTH_KEY });
    window.addEventListener('ga-auth-expired', expired);
    // Ключ прежней схемы больше не нужен — убираем, если остался.
    try {
      window.localStorage.removeItem('ga.admin.token');
    } catch {
      // хранилище недоступно — и удалять нечего
    }
    return () => window.removeEventListener('ga-auth-expired', expired);
  }, [queryClient]);
  return { user: data?.user ?? null, checking: isLoading, me: data };
}

/** Вошёл ли администратор — для кнопок правки данных. */
export function useAdmin(): { isAdmin: boolean; checking: boolean; me: AuthMe | undefined } {
  const { user, checking, me } = useAuth();
  return { isAdmin: user?.role === 'admin', checking, me };
}

/** Текст ошибки из ответа сервера — или запасной. */
export function errorText(err: unknown, fallback = 'Сервер не ответил. Попробуйте ещё раз.'): string {
  const response = (err as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
  const detail = response?.data?.detail;
  if (typeof detail === 'string') return detail;
  // Ошибка проверки полей FastAPI: список — показываем общий текст.
  if (Array.isArray(detail)) return 'Проверьте поля формы.';
  return fallback;
}
