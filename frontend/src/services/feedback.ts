import { http } from './http';

export async function submitFeedback(payload: Record<string, unknown>) {
  const response = await http.post('/feedback/answers', payload);
  return response.data;
}
