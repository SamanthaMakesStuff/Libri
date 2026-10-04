CREATE TABLE books (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT NOT NULL,
  norm_title TEXT,
  norm_author TEXT,
  isbn TEXT,
  published_year INTEGER,
  page_count INTEGER,
  genres TEXT,
  tropes TEXT,
  tags TEXT,
  pacing TEXT,
  spice_level TEXT,
  focus TEXT,
  content_warnings TEXT,
  status TEXT DEFAULT 'catalogued',
  source TEXT DEFAULT 'catalog'
);

CREATE TABLE users (
  id TEXT PRIMARY KEY,
  display_name TEXT,
  email TEXT,
  oauth_provider TEXT,
  oauth_sub TEXT,
  avatar_url TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_users_email ON users(email);
CREATE UNIQUE INDEX idx_users_oauth ON users(oauth_provider, oauth_sub);

CREATE TABLE user_books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  book_id TEXT,
  raw_title TEXT,
  raw_author TEXT,
  shelf TEXT,
  user_rating REAL,
  user_review_text TEXT,
  date_read TEXT,
  date_added TEXT,
  match_status TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id),
  FOREIGN KEY(book_id) REFERENCES books(id)
);

CREATE TABLE pending_books (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT,
  raw_title TEXT NOT NULL,
  raw_author TEXT,
  isbn TEXT,
  seen_count INTEGER DEFAULT 1,
  first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
  status TEXT DEFAULT 'new'
);
CREATE INDEX idx_pending_user ON pending_books(user_id);

CREATE TABLE recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  book_id TEXT NOT NULL,
  session_id TEXT,
  score REAL,
  score_breakdown TEXT,
  served_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id),
  FOREIGN KEY(book_id) REFERENCES books(id)
);

CREATE TABLE feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  recommendation_id INTEGER NOT NULL,
  user_id TEXT NOT NULL,
  rating TEXT,
  reason_tags TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(recommendation_id) REFERENCES recommendations(id),
  FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE user_taste_profile (
  user_id TEXT PRIMARY KEY,
  genre_weights TEXT,
  trope_weights TEXT,
  tag_weights TEXT,
  pacing_pref TEXT,
  spice_pref TEXT,
  focus_pref TEXT,
  hard_excludes TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

-- per-user recommendation cache (avoids rescoring the whole catalog per request)
CREATE TABLE rec_cache (
  user_id TEXT NOT NULL,
  window  TEXT NOT NULL,
  filters TEXT NOT NULL DEFAULT '',
  payload TEXT,
  computed_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, window, filters)
);

CREATE INDEX idx_user_books_user ON user_books(user_id);
CREATE INDEX idx_user_books_book ON user_books(book_id);
CREATE INDEX idx_recommendations_user ON recommendations(user_id);
CREATE INDEX idx_feedback_recommendation ON feedback(recommendation_id);
