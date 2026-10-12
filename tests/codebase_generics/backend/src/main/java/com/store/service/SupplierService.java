package com.store.service;

import com.store.model.Supplier;

public class SupplierService extends BaseService<Supplier> {
    @Override
    protected Supplier load(long id) { return new Supplier(); }

    public String nameOf(long id) {
        return load(id).getName();
    }
}
