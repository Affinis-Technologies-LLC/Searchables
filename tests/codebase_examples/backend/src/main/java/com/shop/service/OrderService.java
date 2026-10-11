package com.shop.service;

import com.shop.model.Order;
import com.shop.repo.OrderRepository;
import java.util.List;

public class OrderService {
    private final OrderRepository repository = new OrderRepository();
    private final Audit audit = new Audit();

    public void place(Order order) {
        validate(order);
        repository.save(order);
        audit.record("place", order.getId());
    }

    public Order load(long id) {
        return repository.find(id).orElseThrow(() -> new IllegalArgumentException("no order " + id));
    }

    public void cancel(long id) {
        Order order = repository.find(id).orElse(null);
        if (order != null) {
            order.setStatus("cancelled");
            repository.save(order, true);
            audit.record("cancel", id);
        }
    }

    public List<Order> open() {
        return repository.all();
    }

    private void validate(Order order) {
        if (order.getId() <= 0) {
            throw new IllegalArgumentException("bad id");
        }
    }
}
