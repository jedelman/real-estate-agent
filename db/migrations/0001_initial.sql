-- Real Estate Agent — D1 schema
-- Migration 0001: initial tables

-- App config (key-value store for agent_id, env_id, session_id, etc.)
CREATE TABLE IF NOT EXISTS config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Buyer preferences (one row per customer_name; stored as JSON)
CREATE TABLE IF NOT EXISTS preferences (
    customer_name   TEXT PRIMARY KEY,
    data            TEXT NOT NULL,   -- JSON blob matching Preferences dataclass
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Properties the buyer has reacted to
CREATE TABLE IF NOT EXISTS saved_properties (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id     TEXT NOT NULL UNIQUE,
    address         TEXT,
    price           REAL,
    status          TEXT NOT NULL DEFAULT 'liked',   -- liked | disliked | touring | offered
    notes           TEXT NOT NULL DEFAULT '',
    agent_rationale TEXT NOT NULL DEFAULT '',
    saved_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Full reaction log (for future analytics / preference signals)
CREATE TABLE IF NOT EXISTS property_reactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT,
    address     TEXT NOT NULL,
    price       REAL,
    reaction    TEXT NOT NULL,   -- liked | disliked | touring
    notes       TEXT NOT NULL DEFAULT '',
    reacted_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
