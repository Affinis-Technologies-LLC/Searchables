package com.shop.web;

import com.shop.model.Order;
import com.shop.service.OrderService;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/orders")
public class OrderController {
    private final OrderService service = new OrderService();

    @GetMapping("/{id}")
    public Order get(@PathVariable long id) {
        return service.load(id);
    }

    @PostMapping
    public void create(@RequestBody Order order) {
        service.place(order);
    }
}
