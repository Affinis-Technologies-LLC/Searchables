package com.shop.repo;

import com.shop.model.Customer;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

public class CustomerRepository implements Repository {
    private final List<Customer> customers = new ArrayList<>();

    public Optional<Customer> find(long id) {
        return customers.stream().filter(c -> c.getId() == id).findFirst();
    }

    public void save(Customer customer) {
        customers.add(customer);
    }

    @Override
    public int count() { return customers.size(); }
}
