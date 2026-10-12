import { HttpClient } from '@acme/http/client';
import { PageOf, request } from '@acme/http';
import { Item, Supplier } from './models';

export class ItemsApi {
  constructor(private http: HttpClient) {}

  load(id: number) {
    this.http.get<Item>(`/items/${id}`).subscribe(item => item.supplier.rating());
  }

  ratings(items: Item[]) {
    return items.map(i => i.supplier).filter(s => s.rating() > 3).map(s => s.name);
  }

  async firstRating(): Promise<number> {
    const page = await request<PageOf<Item>>('/items');
    return page.first().supplier.rating();
  }

  fetchOne(id: number) {
    return fetch(`/items/${id}`).then(r => r.json());
  }
}
