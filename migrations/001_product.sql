
CREATE SCHEMA IF NOT EXISTS flowrank;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='flowrank_runtime') THEN
  CREATE ROLE flowrank_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
 END IF;
END $$;
SET search_path TO flowrank,pg_catalog;

CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, created DOUBLE PRECISION NOT NULL, expires DOUBLE PRECISION NOT NULL,
 variant TEXT NOT NULL, personalized INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS videos (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, topic TEXT NOT NULL, caption TEXT NOT NULL,
 creator TEXT NOT NULL, media_url TEXT NOT NULL, poster_url TEXT NOT NULL, duration DOUBLE PRECISION NOT NULL,
 quality DOUBLE PRECISION NOT NULL, popularity DOUBLE PRECISION NOT NULL, created DOUBLE PRECISION NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','approved','blocked')), source TEXT NOT NULL, license TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS impressions (
 id TEXT PRIMARY KEY, token_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
 video INTEGER NOT NULL REFERENCES videos(id), created DOUBLE PRECISION NOT NULL, variant TEXT NOT NULL,
 position INTEGER NOT NULL, features TEXT NOT NULL, score DOUBLE PRECISION NOT NULL,
 UNIQUE(id, token_hash, video)
);
CREATE TABLE IF NOT EXISTS feedback (
 event_id TEXT NOT NULL, token_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
 impression TEXT NOT NULL, video INTEGER NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('watch','like','skip','report')),
 watch DOUBLE PRECISION NOT NULL CHECK(watch >= 0 AND watch <= 1), created DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(token_hash,event_id), UNIQUE(token_hash,impression,kind),
 FOREIGN KEY(impression,token_hash,video) REFERENCES impressions(id,token_hash,video) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS rate_limits (key TEXT PRIMARY KEY, bucket INTEGER NOT NULL, hits INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS feedback_user_time ON feedback(token_hash,created);
CREATE INDEX IF NOT EXISTS impressions_user_time ON impressions(token_hash,created);
CREATE INDEX IF NOT EXISTS videos_eligible ON videos(status,topic,created);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires);

GRANT USAGE ON SCHEMA flowrank TO flowrank_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA flowrank TO flowrank_runtime;
REVOKE ALL ON SCHEMA flowrank FROM PUBLIC,anon,authenticated;

ALTER TABLE flowrank.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE flowrank.sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY guest_ownership ON flowrank.sessions TO flowrank_runtime
 USING (token_hash = current_setting('app.session_hash',true))
 WITH CHECK (token_hash = current_setting('app.session_hash',true));

ALTER TABLE flowrank.impressions ENABLE ROW LEVEL SECURITY;
ALTER TABLE flowrank.impressions FORCE ROW LEVEL SECURITY;
CREATE POLICY guest_ownership ON flowrank.impressions TO flowrank_runtime
 USING (token_hash = current_setting('app.session_hash',true))
 WITH CHECK (token_hash = current_setting('app.session_hash',true));

ALTER TABLE flowrank.feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE flowrank.feedback FORCE ROW LEVEL SECURITY;
CREATE POLICY guest_ownership ON flowrank.feedback TO flowrank_runtime
 USING (token_hash = current_setting('app.session_hash',true))
 WITH CHECK (token_hash = current_setting('app.session_hash',true));

ALTER TABLE flowrank.videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE flowrank.videos FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON flowrank.videos TO flowrank_runtime USING(true) WITH CHECK(true);

ALTER TABLE flowrank.rate_limits ENABLE ROW LEVEL SECURITY;
ALTER TABLE flowrank.rate_limits FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON flowrank.rate_limits TO flowrank_runtime USING(true) WITH CHECK(true);

CREATE POLICY expired_session_read ON flowrank.sessions FOR SELECT TO flowrank_runtime
 USING (expires < extract(epoch from now()));
CREATE POLICY expired_session_delete ON flowrank.sessions FOR DELETE TO flowrank_runtime
 USING (expires < extract(epoch from now()));
REVOKE ALL ON ALL TABLES IN SCHEMA flowrank FROM PUBLIC,anon,authenticated;
-- This schema is private and must never be added to PostgREST's exposed schemas.
