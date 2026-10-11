import React from 'react';
import type { User } from '../hooks/useUsers';

interface Props { user: User; onSelect: (user: User) => void }

export function UserCard({ user, onSelect }: Props) {
  return <button onClick={() => onSelect(user)}>{user.name}</button>;
}

export default React.memo(UserCard);
