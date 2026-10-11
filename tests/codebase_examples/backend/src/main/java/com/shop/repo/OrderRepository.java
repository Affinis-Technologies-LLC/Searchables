package com.shop.repo;

import com.shop.model.Order;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

public class OrderRepository implements Repository {
    private final List<Order> orders = new ArrayList<>();

    public Optional<Order> find(long id) {
        return orders.stream().filter(o -> o.getId() == id).findFirst();
    }

    public void save(Order order) {
        orders.add(order);
    }

    public void save(Order order, boolean flush) {
        orders.add(order);
    }

    public List<Order> all() {
        return orders;
    }

    @Override
    public int count() { return orders.size(); }
}
