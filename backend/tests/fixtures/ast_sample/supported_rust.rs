use std::collections::HashMap;
use std::sync::Arc;

pub const MAX_RETRIES: u32 = 3;

pub trait CacheBackend {
    fn get_item(&self, key: &str) -> Option<String>;
}

pub struct MemoryCache {
    store: HashMap<String, String>,
    shared: Arc<String>,
}

impl MemoryCache {
    pub fn new() -> Self {
        Self {
            store: HashMap::new(),
            shared: Arc::new(String::from("default")),
        }
    }

    pub fn insert_item(&mut self, key: String, value: String) {
        let normalized = normalize_key(&key);
        self.store.insert(normalized, value);
    }
}

impl CacheBackend for MemoryCache {
    fn get_item(&self, key: &str) -> Option<String> {
        self.store.get(key).cloned()
    }
}

pub fn normalize_key(raw: &str) -> String {
    raw.trim().to_lowercase()
}
