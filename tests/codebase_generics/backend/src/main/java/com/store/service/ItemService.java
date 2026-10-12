package com.store.service;

import com.store.model.Item;
import com.store.model.Supplier;
import com.store.repo.ItemRepository;
import com.store.repo.StoredItemRepository;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

public class ItemService {
    private final ItemRepository items;
    private final StoredItemRepository stored;
    private final Map<String, Item> byCode = new HashMap<>();

    public ItemService(ItemRepository items, StoredItemRepository stored) {
        this.items = items;
        this.stored = stored;
    }

    public String supplierName(long id) {
        return items.findById(id).orElseThrow().getSupplier().getName();
    }

    public String codeOf(String code) {
        return byCode.get(code).getCode();
    }

    public List<String> supplierNames() {
        return items.findAll().stream()
                .map(i -> i.getSupplier())
                .filter(s -> s.getName() != null)
                .map(s -> s.getName())
                .collect(Collectors.toList());
    }

    public void touch(long id) {
        items.findById(id).ifPresent(i -> i.getCode());
        items.findAll().forEach(i -> i.getId());
    }

    public long count() {
        return stored.count();
    }

    public String storedCode(long id) {
        return stored.findById(id).orElseThrow().getCode();
    }
}
