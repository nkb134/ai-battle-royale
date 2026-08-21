-- §4. WAL is required, or the live writer and the API reader will fight (§13).
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS models (
    id             TEXT PRIMARY KEY,
    provider       TEXT NOT NULL,
    model_string   TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    face_id        TEXT,
    palette        TEXT,
    voice          TEXT,
    tokens_per_sec REAL,
    active         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS matches (
    id           TEXT PRIMARY KEY,
    white        TEXT NOT NULL REFERENCES models(id),
    black        TEXT NOT NULL REFERENCES models(id),
    time_control TEXT NOT NULL,
    config_hash  TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    result       TEXT,
    termination  TEXT,
    ply_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS plies (
    match_id         TEXT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    ply              INTEGER NOT NULL,
    fen_before       TEXT NOT NULL,
    move_uci         TEXT,
    move_san         TEXT,
    legal            INTEGER NOT NULL,
    retry_count      INTEGER NOT NULL DEFAULT 0,
    cp_before        INTEGER,
    cp_after         INTEGER,
    cp_loss          INTEGER,
    classification   TEXT,
    clock_ms_before  INTEGER,
    clock_ms_after   INTEGER,
    elapsed_ms       INTEGER NOT NULL,
    reasoning_tokens INTEGER,
    token_budget     INTEGER NOT NULL,
    panic            INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, ply)
);

CREATE TABLE IF NOT EXISTS taunts (
    match_id TEXT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    ply      INTEGER NOT NULL,
    speaker  TEXT NOT NULL,
    text     TEXT NOT NULL,
    trigger  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ratings (
    model_id    TEXT NOT NULL REFERENCES models(id),
    config_hash TEXT NOT NULL,
    rating      REAL NOT NULL,
    rd          REAL NOT NULL,
    volatility  REAL NOT NULL,
    games       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (model_id, config_hash)
);

CREATE INDEX IF NOT EXISTS idx_plies_match ON plies(match_id);
CREATE INDEX IF NOT EXISTS idx_matches_config ON matches(config_hash);
