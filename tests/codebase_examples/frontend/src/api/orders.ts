import { http } from './client';

export interface Order { id: number; status: string }

export function fetchOrder(id: number): Promise<Order> {
  return http.get<Order>(`/api/orders/${id}`);
}

export function fetchOrders(): Promise<Order[]> {
  return http.get<Order[]>('/api/orders');
}

export function createOrder(order: Order): Promise<Order> {
  return http.post<Order>('/api/orders', order);
}
