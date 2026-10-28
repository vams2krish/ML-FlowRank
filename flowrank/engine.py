import json
import math
import random
import sqlite3
import time
from pathlib import Path

TOPICS = ['Technology', 'Cooking', 'Travel', 'Music', 'Fitness', 'Art']
FEATURES = ['affinity', 'quality', 'freshness', 'popularity']


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-30, min(30, x))))


class Engine:
    def __init__(self, path='data/flowrank.db'):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS videos(id INTEGER PRIMARY KEY, title TEXT, topic TEXT, creator TEXT, quality REAL, created REAL, popularity REAL, duration REAL);
        CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, user TEXT, video INTEGER REFERENCES videos(id), kind TEXT, watch REAL, created REAL);
        CREATE TABLE IF NOT EXISTS models(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT);
        ''')
        self.db.execute('PRAGMA foreign_keys=ON')
        if not self.db.execute('SELECT 1 FROM videos LIMIT 1').fetchone():
            rng = random.Random(42)
            for i in range(120):
                topic = TOPICS[i % len(TOPICS)]
                self.db.execute('INSERT INTO videos VALUES(?,?,?,?,?,?,?,?)',
                                (i + 1, f'{topic}: discovery #{i // 6 + 1}', topic, f'creator_{i % 18}', rng.uniform(.3, 1), time.time() - rng.uniform(0, 604800), rng.random(), rng.randint(10, 60)))
            self.db.commit()
        row = self.db.execute('SELECT payload FROM models WHERE id=1').fetchone()
        self.model = json.loads(row[0]) if row else None

    def profile(self, user):
        profile = dict.fromkeys(TOPICS, 0.)
        rows = self.db.execute('SELECT v.topic,e.kind,e.watch,e.created FROM events e JOIN videos v ON v.id=e.video WHERE e.user=?', (user,))
        for row in rows:
            reward = {'like': 1., 'skip': -1., 'watch': 2 * row['watch'] - .5}[row['kind']]
            profile[row['topic']] += reward * math.exp(-(time.time() - row['created']) / 604800)
        return {k: math.tanh(v / 3) for k, v in profile.items()}

    def feed(self, user, limit=12):
        profile = self.profile(user)
        seen = {r[0] for r in self.db.execute('SELECT video FROM events WHERE user=?', (user,))}
        videos = [dict(v) for v in self.db.execute('SELECT * FROM videos') if v['id'] not in seen]
        # Retrieve a union of personalized, trending, and fresh candidates.
        candidates = {v['id']: v for key in [lambda v: profile[v['topic']], lambda v: v['popularity'], lambda v: v['created']]
                      for v in sorted(videos, key=key, reverse=True)[:40]}
        for v in candidates.values():
            x = [profile[v['topic']], v['quality'], math.exp(-(time.time() - v['created']) / 604800), v['popularity']]
            weights = self.model['weights'] if self.model else [2., .8, .4, .4]
            bias = self.model['bias'] if self.model else -1.
            v['score'] = round(sigmoid(bias + sum(a * b for a, b in zip(x, weights))), 4)
            v['reason'] = 'Matches your interests' if x[0] > .1 else 'Explore something new'
        pool = sorted(candidates.values(), key=lambda v: v['score'], reverse=True)
        result, counts = [], {}
        while pool and len(result) < limit:
            # Greedy diversity penalty prevents one topic dominating a page.
            best = max(pool, key=lambda v: v['score'] - .18 * counts.get(v['topic'], 0))
            pool.remove(best)
            counts[best['topic']] = counts.get(best['topic'], 0) + 1
            result.append(best)
        return result

    def event(self, payload):
        if payload.get('kind') not in ('watch', 'like', 'skip'):
            raise ValueError('kind must be watch, like, or skip')
        if not isinstance(payload.get('user'), str) or not 1 <= len(payload['user']) <= 80:
            raise ValueError('user must contain 1–80 characters')
        if not isinstance(payload.get('event_id'), str) or not 1 <= len(payload['event_id']) <= 100:
            raise ValueError('event_id must contain 1–100 characters')
        watch = float(payload.get('watch', 0))
        if not math.isfinite(watch) or not 0 <= watch <= 1:
            raise ValueError('watch must be a fraction between 0 and 1')
        if type(payload.get('video')) is not int or not self.db.execute('SELECT 1 FROM videos WHERE id=?', (payload.get('video'),)).fetchone():
            raise ValueError('unknown video')
        self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)', (payload['event_id'], payload['user'], payload['video'], payload['kind'], watch, time.time()))
        self.db.commit()

    def stats(self):
        return {'videos': self.db.execute('SELECT count(*) FROM videos').fetchone()[0],
                'events': self.db.execute('SELECT count(*) FROM events').fetchone()[0],
                'model': self.model or {'status': 'heuristic fallback; run python -m flowrank.train'}}
