import axios from 'axios';

export interface User { id: number }

export async function fetchUser(id: number): Promise<User> {
  const response = await axios.get(`/api/users/${id}`);
  return response.data;
}

export const createUser = (user: User) => axios.post('/api/users', user);

export function removeUser(id: number) {
  return fetch('/api/users/' + id + '/avatar', { method: 'DELETE' });
}
