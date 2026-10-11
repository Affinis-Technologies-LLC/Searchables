import { useCallback, useState } from 'react';
import { useUsers, User } from '../hooks/useUsers';
import UserCard from './UserCard';

export function UserList() {
  const { users, reload } = useUsers();
  const [chosen, setChosen] = useState<User | null>(null);
  const select = useCallback((user: User) => setChosen(user), []);
  return (
    <section>
      {users.map((user) => <UserCard key={user.id} user={user} onSelect={select} />)}
      {chosen && <p>{chosen.name}</p>}
      <button onClick={reload}>Reload</button>
    </section>
  );
}
