-- After5 Pipeline — free-stack schema (SQLite)

CREATE TABLE IF NOT EXISTS companies (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  domain          TEXT UNIQUE NOT NULL,
  name            TEXT,
  country         TEXT CHECK(country IN ('UK','UAE')) NOT NULL,
  icp             TEXT,
  source          TEXT,
  status          TEXT DEFAULT 'new',
  tech_score      INTEGER DEFAULT 0,
  seo_score       INTEGER DEFAULT 0,
  reviews_score   INTEGER DEFAULT 0,
  ads_score       INTEGER DEFAULT 0,
  hiring_score    INTEGER DEFAULT 0,
  sentiment_score INTEGER DEFAULT 0,
  total_score     INTEGER DEFAULT 0,
  priority        TEXT,
  signals         TEXT,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_country ON companies(country);

CREATE TABLE IF NOT EXISTS contacts (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id            INTEGER NOT NULL REFERENCES companies(id),
  first_name            TEXT,
  last_name             TEXT,
  email                 TEXT UNIQUE,
  email_verified        INTEGER DEFAULT 0,
  role                  TEXT,
  linkedin_url          TEXT,
  phone                 TEXT,
  ai_first_line         TEXT,
  signal_used           TEXT,
  ready_to_send         INTEGER DEFAULT 0,
  unsubscribed          INTEGER DEFAULT 0,
  current_sequence_day  INTEGER DEFAULT 0,
  last_sent_at          TIMESTAMP,
  next_send_day         INTEGER,
  created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);
CREATE INDEX IF NOT EXISTS idx_contacts_ready ON contacts(ready_to_send, unsubscribed);

CREATE TABLE IF NOT EXISTS sends (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id    INTEGER NOT NULL REFERENCES contacts(id),
  sequence_day  INTEGER NOT NULL,
  subject       TEXT,
  body          TEXT,
  sent_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  message_id    TEXT
);

CREATE INDEX IF NOT EXISTS idx_sends_contact ON sends(contact_id);

CREATE TABLE IF NOT EXISTS replies (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id      INTEGER REFERENCES contacts(id),
  raw_body        TEXT,
  classification  TEXT,
  sentiment       TEXT,
  needs_louis     INTEGER DEFAULT 0,
  louis_responded INTEGER DEFAULT 0,
  loom_sent       INTEGER DEFAULT 0,
  meeting_booked  INTEGER DEFAULT 0,
  slack_pinged_at TIMESTAMP,
  received_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_replies_contact ON replies(contact_id);
CREATE INDEX IF NOT EXISTS idx_replies_class ON replies(classification);

CREATE TABLE IF NOT EXISTS suppression (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  email       TEXT UNIQUE,
  domain      TEXT,
  reason      TEXT,
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
