import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from flowrank.engine import Engine
from flowrank.train import train
from flowrank.server import create_server


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.db')
        self.engine = Engine(self.path)

    def tearDown(self):
        self.engine.db.close()
        self.temp.cleanup()

    def test_feedback_and_idempotency(self):
        video = self.engine.feed('a')[0]
        event = dict(event_id='one', user='a', video=video['id'], kind='like')
        self.engine.event(event)
        self.engine.event(event)
        self.assertEqual(self.engine.stats()['events'], 1)
        self.assertGreater(self.engine.profile('a')[video['topic']], 0)
        self.assertNotIn(video['id'], [v['id'] for v in self.engine.feed('a')])
        self.assertTrue(all(v == 0 for v in self.engine.profile('b').values()))

    def test_diversity_and_validation(self):
        self.assertGreaterEqual(len({v['topic'] for v in self.engine.feed('new')}), 4)
        for patch in [dict(kind='bad'), dict(watch=float('nan')), dict(video=9999)]:
            with self.assertRaises(ValueError):
                self.engine.event(dict(dict(event_id='x',user='a',video=1,kind='watch'), **patch))

    def test_training_and_reload(self):
        model = train(self.path)
        self.assertLess(model['test_log_loss'], model['baseline_log_loss'])
        restored = Engine(self.path)
        self.assertEqual(restored.model, model)
        restored.db.close()

    def test_http_roundtrip(self):
        server = create_server(0, self.path)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base + '/api/feed?user=http') as response:
                item = json.load(response)['items'][0]
            request = Request(base + '/api/events', data=json.dumps(dict(event_id='http',user='http',video=item['id'],kind='like')).encode(), headers={'Content-Type':'application/json'})
            with urlopen(request) as response:
                self.assertTrue(json.load(response)['ok'])
            with urlopen(base + '/api/feed?user=http') as response:
                self.assertNotIn(item['id'], [v['id'] for v in json.load(response)['items']])
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + '/api/events', data=b'[]'))
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            # Close SQLite on its owning test thread after HTTP thread exits.
            thread.join()


if __name__ == '__main__':
    unittest.main()
