export interface Supplier {
  name: string;
  rating(): number;
}

export interface Item {
  id: number;
  code: string;
  supplier: Supplier;
}
