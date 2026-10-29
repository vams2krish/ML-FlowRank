"""Optional integration test against provisioned private FlowRank schema."""
import os
import secrets
import time
import unittest
from flowrank.store import Store


@unittest.skipUnless(os.environ.get('DATABASE_TEST_URL'),'Set DATABASE_TEST_URL for PostgreSQL RLS integration')
class PostgresIsolationTests(unittest.TestCase):
    def test_rls_rejects_cross_session_access_and_writes(self):
        store=Store(url=os.environ['DATABASE_TEST_URL'])
        a,b=secrets.token_hex(32),secrets.token_hex(32)
        try:
            for user in (a,b):
                with store.transaction(user) as tx:
                    tx.execute('INSERT INTO sessions VALUES(?,?,?,?,1)',(user,time.time(),time.time()+3600,'balanced'))
            with store.transaction(a) as tx:
                rows=tx.rows('SELECT token_hash FROM sessions WHERE expires>?',(time.time(),))
                self.assertEqual([r['token_hash'] for r in rows],[a])
                self.assertIsNone(tx.one('SELECT * FROM sessions WHERE token_hash=?',(b,)))
                tx.execute('UPDATE sessions SET personalized=0 WHERE token_hash=?',(b,))
            with store.transaction(b) as tx:
                self.assertEqual(tx.one('SELECT personalized FROM sessions WHERE token_hash=?',(b,))['personalized'],1)
            with self.assertRaises(Exception):
                with store.transaction(a) as tx:
                    tx.execute('INSERT INTO sessions VALUES(?,?,?,?,1)',(secrets.token_hex(32),time.time(),time.time()+3600,'balanced'))
        finally:
            for user in (a,b):
                with store.transaction(user) as tx:
                    tx.execute('DELETE FROM sessions WHERE token_hash=?',(user,))
