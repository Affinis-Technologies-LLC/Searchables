import { Item } from './models';

export class Widget<T> {
  constructor(private current: T) {}

  value(): T {
    return this.current;
  }
}

export class ItemWidget extends Widget<Item> {
  rating() {
    return this.value().supplier.rating();
  }
}
