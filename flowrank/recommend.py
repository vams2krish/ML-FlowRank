import hashlib
import json
import math
import time
from pathlib import Path
from .engine import sigmoid
from .catalog import TOPICS

MODEL_PATH = Path(__file__).resolve().parent / 'model.json'


def profile(tx, user, enabled=True, now=None):
    interests = dict.fromkeys(TOPICS, 0.)
    if not enabled:
        return interests
    now = now or time.time()
    for row in tx.rows('SELECT v.topic,f.kind,f.watch,f.created FROM feedback f JOIN videos v ON v.id=f.video WHERE f.token_hash=? AND f.created>?', (user, now-30*86400)):
        reward = {'like': 1., 'skip': -.6, 'report': -2., 'watch': 2*row['watch']-.5}[row['kind']]
        interests[row['topic']] += reward * math.exp(-max(0, now-row['created'])/604800)
    return {topic: math.tanh(value/3) for topic,value in interests.items()}


def features(video, interests, now):
    return [interests.get(video['topic'],0), video['quality'], math.exp(-max(0,now-video['created'])/604800), video['popularity']]


def rank(videos, interests, variant, user, limit=8, now=None):
    now = now or time.time()
    model = json.loads(MODEL_PATH.read_text())
    candidates = {v['id']: dict(v) for key in [lambda v: interests.get(v['topic'],0), lambda v:v['created'],lambda v:v['popularity']]
                  for v in sorted(videos,key=key,reverse=True)[:40]}
    for video in candidates.values():
        video['features'] = features(video,interests,now)
        score = sigmoid(model['bias']+sum(a*b for a,b in zip(model['weights'],video['features'])))
        video['score'] = round(score,5)
        video['reason'] = 'Because you lingered on '+video['topic'].lower() if video['features'][0]>.1 else 'A fresh perspective to explore'
        # Stable bounded exploration is a demonstration, not propensity-correct randomization.
        video['exploration'] = int(hashlib.sha256(f'{user}:{video["id"]}'.encode()).hexdigest()[:8],16)/0xffffffff*.06
    result,topics,creators = [],{},{}
    pool = list(candidates.values())
    while pool and len(result)<limit:
        penalty = .17 if variant=='diverse' else .07
        best=max(pool,key=lambda v:v['score']+v['exploration']-penalty*topics.get(v['topic'],0)-.04*creators.get(v['creator'],0))
        pool.remove(best)
        topics[best['topic']]=topics.get(best['topic'],0)+1
        creators[best['creator']]=creators.get(best['creator'],0)+1
        result.append(best)
    return result
