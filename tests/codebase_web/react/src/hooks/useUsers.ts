import { useEffect, useState } from 'react';

export interface User { id: number; name: string }

export function useUsers(): { users: User[]; reload: () => void } {
  const [users, setUsers] = useState<User[]>([]);
  const reload = () => fetch('/api/users').then((r) => r.json()).then(setUsers);
  useEffect(() => { reload(); }, []);
  return { users, reload };
}
