-- SQLite schema for user tracks and recommendations

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT UNIQUE,
    display_name TEXT,
    access_token TEXT,
    refresh_token TEXT,
    expires_at INTEGER
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT,
    name TEXT,
    artist TEXT,
    album TEXT,
    album_cover TEXT,
    user_id INTEGER,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT,
    name TEXT,
    artist TEXT,
    album_cover TEXT,
    user_id INTEGER,
    playlist_id TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
