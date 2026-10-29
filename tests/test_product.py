import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from app import create_app,digest,COOKIE
from flowrank.store import Store

HEADERS={'X-FlowRank':'1'}


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(url='',path=self.temp.name+'/product.db')
        self.app=create_app(self.store,testing=True)
        self.client=self.app.test_client()
        self.client.post('/api/session',json={},headers=HEADERS)

    def tearDown(self):
        self.temp.cleanup()

    def impression(self,client=None):
        client=client or self.client
        item=client.get('/api/feed').json['items'][0]
        response=client.post('/api/impressions',json={'video':item['id']},headers=HEADERS)
        self.assertEqual(response.status_code,200)
        return item,response.json['impression']

    def test_session_and_csrf(self):
        self.assertEqual(self.app.test_client().get('/api/feed?user=demo').status_code,401)
        self.assertEqual(self.client.post('/api/session',json={}).status_code,403)
        self.assertEqual(self.client.post('/api/session',json={},headers={**HEADERS,'Origin':'https://evil.example'}).status_code,403)
        cookie=self.client.get_cookie(COOKIE)
        self.assertTrue(cookie.http_only)
        self.assertEqual(cookie.same_site,'Lax')

    def test_feedback_isolation_idempotency_and_privacy(self):
        item,exposure=self.impression()
        payload=dict(event_id='unique',impression=exposure,kind='like')
        self.assertEqual(self.client.post('/api/events',json=payload,headers=HEADERS).status_code,200)
        self.client.post('/api/events',json=payload,headers=HEADERS)
        self.assertEqual(len(self.client.get('/api/privacy/export').json['events']),1)
        self.assertGreater(self.client.get('/api/session').json['profile'][item['topic']],0)
        other=self.app.test_client()
        other.post('/api/session',json={},headers=HEADERS)
        self.assertEqual(other.post('/api/events',json=payload,headers=HEADERS).status_code,403)
        self.assertEqual(other.get('/api/privacy/export').json['events'],[])
        self.client.patch('/api/preferences',json={'personalized':False},headers=HEADERS)
        self.assertTrue(all(v==0 for v in self.client.get('/api/feed').json['profile'].values()))
        self.client.delete('/api/privacy',headers=HEADERS)
        self.assertEqual(self.client.get('/api/session').status_code,401)
        with self.store.transaction() as tx:
            self.assertEqual(tx.one('SELECT count(*) AS count FROM feedback')['count'],0)
            self.assertEqual(tx.one('SELECT count(*) AS count FROM impressions')['count'],0)

    def test_moderation_and_reports(self):
        item,exposure=self.impression()
        self.client.post('/api/events',json=dict(event_id='report',impression=exposure,kind='report'),headers=HEADERS)
        self.assertNotIn(item['id'],[v['id'] for v in self.client.get('/api/feed').json['items']])
        self.assertEqual(self.client.patch('/api/admin/catalog/1',json={'status':'blocked'},headers=HEADERS).status_code,404)
        with patch.dict(os.environ,{'ADMIN_TOKEN_HASH':digest('test-admin')}):
            response=self.client.patch('/api/admin/catalog/1',json={'status':'blocked'},headers={**HEADERS,'Authorization':'Bearer test-admin'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.client.post('/api/impressions',json={'video':1},headers=HEADERS).status_code,404)

    def test_bad_payload_and_watch_time_bound(self):
        _,exposure=self.impression()
        for body in [[],{'kind':'oops'},dict(event_id='bad',impression=exposure,kind='watch',watch=-1),dict(event_id='bad',impression=exposure,kind='watch',watch='1')]:
            self.assertEqual(self.client.post('/api/events',json=body,headers=HEADERS).status_code,400)
        self.client.post('/api/events',json=dict(event_id='watch',impression=exposure,kind='watch',watch=1),headers=HEADERS)
        self.assertLess(self.client.get('/api/privacy/export').json['events'][0]['watch'],.2)
        self.assertEqual(self.client.get('/api/feed?topic=bad').status_code,400)

    def test_session_expiry_and_rate_limit(self):
        user=digest(self.client.get_cookie(COOKIE).value)
        with self.store.transaction() as tx:
            tx.execute('INSERT INTO rate_limits VALUES(?,?,?)',('user:'+user,int(time.time()//60),120))
        self.assertEqual(self.client.get('/api/feed').status_code,429)
        with self.store.transaction() as tx:
            tx.execute('UPDATE sessions SET expires=0 WHERE token_hash=?',(user,))
        self.assertEqual(self.client.get('/api/session').status_code,401)

    def test_media_security_and_health(self):
        self.assertEqual(self.client.get('/health').json['status'],'ok')
        response=self.client.get('/static/media/signal.mp4',headers={'Range':'bytes=0-127'})
        self.assertEqual(response.status_code,206)
        response.close()

    def test_ingestion_pending_review_and_retention(self):
        with patch.dict(os.environ,{'ADMIN_TOKEN_HASH':digest('test-admin'),'CRON_SECRET':'test-cron'}):
            headers={**HEADERS,'Authorization':'Bearer test-admin'}
            entry=dict(id=500,title='A reviewed import',topic='Art',caption='A new study',creator='studio',media_url='/static/media/color.mp4',poster_url='/static/media/color.jpg',duration=12,quality=.8,popularity=.5,source='Original',license='CC0-1.0')
            self.assertEqual(self.client.post('/api/admin/catalog',json=entry,headers=headers).status_code,201)
            self.assertEqual(self.client.post('/api/impressions',json={'video':500},headers=HEADERS).status_code,404)
            self.client.patch('/api/admin/catalog/500',json={'status':'approved'},headers=headers)
            self.assertEqual(self.client.post('/api/impressions',json={'video':500},headers=HEADERS).status_code,200)
            with self.store.transaction() as tx:
                tx.execute('INSERT INTO sessions VALUES(?,?,?,?,1)',('expired',0,0,'balanced'))
            self.assertEqual(self.client.get('/api/maintenance').status_code,404)
            self.assertEqual(self.client.get('/api/maintenance',headers={'Authorization':'Bearer test-cron'}).status_code,200)
            with self.store.transaction() as tx:
                self.assertIsNone(tx.one('SELECT * FROM sessions WHERE token_hash=?',('expired',)))
        response=self.client.get('/')
        self.assertIn("script-src 'self'",response.headers['Content-Security-Policy'])
        response.close()


if __name__=='__main__':
    unittest.main()
