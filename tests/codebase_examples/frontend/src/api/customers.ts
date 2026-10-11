import { http } from './client';

export interface Customer { id: number; name: string }

export function fetchCustomer(id: number): Promise<Customer> {
  return http.get<Customer>(`/api/customers/${id}`);
}

export function registerCustomer(customer: Customer): Promise<Customer> {
  return http.post<Customer>('/api/customers', customer);
}
