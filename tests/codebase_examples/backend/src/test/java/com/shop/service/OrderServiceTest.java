package com.shop.service;

import com.shop.model.Order;
import com.shop.repo.OrderRepository;

public class OrderServiceTest {
    private final OrderRepository repository = new OrderRepository();

    public void savesAnOrder() {
        Order order = new Order(7);
        repository.save(order);
        assert repository.find(7).isPresent();
    }
}
