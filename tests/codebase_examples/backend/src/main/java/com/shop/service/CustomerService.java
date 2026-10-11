package com.shop.service;

import com.shop.model.Customer;
import com.shop.repo.CustomerRepository;

public class CustomerService {
    private final CustomerRepository repository = new CustomerRepository();
    private final Audit audit = new Audit();

    public void register(Customer customer) {
        repository.save(customer);
        audit.record("register", customer.getId());
    }

    public Customer lookup(long id) {
        return repository.find(id).orElse(new Customer(id));
    }
}
