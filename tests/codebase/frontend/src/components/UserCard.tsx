import React, { useEffect } from 'react';
import { fetchUser, User } from '@/api/users';
import * as users from '../api/users';
import { format } from '../util';

export default function UserCard({ id }: { id: number }) {
  useEffect(() => { fetchUser(id).then(show); }, [id]);
  users.createUser({ id });
  return <div>{format(id)}</div>;
}

function show(user: User) { console.log(user); }
