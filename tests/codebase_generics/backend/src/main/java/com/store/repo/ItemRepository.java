package com.store.repo;

import com.store.model.Item;
import java.util.List;

public interface ItemRepository extends BaseRepository<Item, Long> {
    List<Item> findByCode(String code);
}
