CREATE TABLE IF NOT EXISTS board (slug TEXT PRIMARY KEY, name TEXT, key_hash TEXT, best INT, at INT);
CREATE TABLE IF NOT EXISTS daily (date TEXT, key_hash TEXT, name TEXT, score REAL, spots TEXT, at INT, PRIMARY KEY (date, key_hash));
CREATE INDEX IF NOT EXISTS daily_score ON daily(date, score);
