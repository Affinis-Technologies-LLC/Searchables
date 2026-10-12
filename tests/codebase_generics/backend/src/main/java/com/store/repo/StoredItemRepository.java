package com.store.repo;

import com.store.model.Item;
import org.springframework.data.jpa.repository.JpaRepository;

public interface StoredItemRepository extends JpaRepository<Item, Long> {
}
