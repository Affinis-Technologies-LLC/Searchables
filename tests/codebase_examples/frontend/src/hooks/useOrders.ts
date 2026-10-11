import { useEffect, useState } from 'react';
import { fetchOrders, Order } from '../api/orders';

export function useOrders(): Order[] {
  const [orders, setOrders] = useState<Order[]>([]);
  useEffect(() => {
    fetchOrders().then(setOrders);
  }, []);
  return orders;
}
