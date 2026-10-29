"""Print the reviewed migration. Credentials are provisioned separately."""
from flowrank.store import SCHEMA

SQL='''
CREATE SCHEMA IF NOT EXISTS flowrank;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='flowrank_runtime') THEN
  CREATE ROLE flowrank_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
 END IF;
END $$;
SET search_path TO flowrank,pg_catalog;
'''+SCHEMA+'''
GRANT USAGE ON SCHEMA flowrank TO flowrank_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA flowrank TO flowrank_runtime;
REVOKE ALL ON SCHEMA flowrank FROM PUBLIC,anon,authenticated;
'''
for table in ('sessions','impressions','feedback'):
    SQL+=f'''
ALTER TABLE flowrank.{table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE flowrank.{table} FORCE ROW LEVEL SECURITY;
CREATE POLICY guest_ownership ON flowrank.{table} TO flowrank_runtime
 USING (token_hash = current_setting('app.session_hash',true))
 WITH CHECK (token_hash = current_setting('app.session_hash',true));
'''
for table in ('videos','rate_limits'):
    SQL+=f'''
ALTER TABLE flowrank.{table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE flowrank.{table} FORCE ROW LEVEL SECURITY;
CREATE POLICY backend_access ON flowrank.{table} TO flowrank_runtime USING(true) WITH CHECK(true);
'''
SQL+='''
CREATE POLICY expired_session_read ON flowrank.sessions FOR SELECT TO flowrank_runtime
 USING (expires < extract(epoch from now()));
CREATE POLICY expired_session_delete ON flowrank.sessions FOR DELETE TO flowrank_runtime
 USING (expires < extract(epoch from now()));
REVOKE ALL ON ALL TABLES IN SCHEMA flowrank FROM PUBLIC,anon,authenticated;
-- This schema is private and must never be added to PostgREST's exposed schemas.
'''

if __name__=='__main__':
    from pathlib import Path
    Path('migrations/001_product.sql').write_text(SQL)
