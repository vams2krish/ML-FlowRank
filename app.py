"""Production WSGI entrypoint. Guest identity is an opaque HttpOnly cookie."""
import hashlib
import json
import logging
import math
import os
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from flowrank.store import Store
from flowrank.recommend import profile, rank, MODEL_PATH
from flowrank.catalog import TOPICS, seed_catalog

ROOT=Path(__file__).resolve().parent
COOKIE='flowrank_session'
MAX_AGE=30*86400


class APIError(Exception):
    def __init__(self,message,status=400):
        self.message,self.status=message,status


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def create_app(store=None, testing=False):
    app=Flask(__name__,static_folder='static')
    app.config.update(MAX_CONTENT_LENGTH=16384,TESTING=testing)
    app.store=store or Store()
    secure=os.environ.get('COOKIE_SECURE','true' if os.environ.get('VERCEL') else 'false')=='true'
    if not app.store.url:
        with app.store.transaction() as tx:
            for video in seed_catalog(time.time()):
                columns=','.join(video)
                tx.execute(f'INSERT INTO videos({columns}) VALUES({",".join("?" for _ in video)}) ON CONFLICT(id) DO NOTHING',tuple(video.values()))

    @app.before_request
    def start():
        g.started=time.monotonic()
        g.request_id=uuid.uuid4().hex
        if request.path.startswith('/api/') and request.method in ('POST','DELETE','PATCH'):
            if request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/'):
                raise APIError('Cross-origin writes are not permitted',403)
            if request.headers.get('Sec-Fetch-Site')=='cross-site':
                raise APIError('Cross-site writes are not permitted',403)
            if request.headers.get('X-FlowRank')!='1':
                raise APIError('Missing request verification header',403)

    @app.after_request
    def finish(response):
        response.headers['X-Request-ID']=g.request_id
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if secure:
            response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
        if request.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        app.logger.info(json.dumps(dict(request_id=g.request_id,path=request.path,status=response.status_code,duration_ms=round((time.monotonic()-g.started)*1000,2))))
        return response

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc,APIError):
            return jsonify(error=exc.message,request_id=g.request_id),exc.status
        if isinstance(exc,HTTPException):
            return jsonify(error=exc.description,request_id=g.request_id),exc.code
        app.logger.exception('request_failed id=%s',g.request_id)
        return jsonify(error='Service unavailable. Please retry.',request_id=g.request_id),503

    def body():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            raise APIError('Expected a JSON object')
        return data

    def identity():
        token=request.cookies.get(COOKIE,'')
        if not 40<=len(token)<=100:
            raise APIError('Start a guest session first',401)
        return digest(token)

    def session(tx,user):
        row=tx.one('SELECT * FROM sessions WHERE token_hash=? AND expires>?',(user,time.time()))
        if not row:
            raise APIError('Session expired. Start a new session.',401)
        return row

    def throttle(tx,key,limit=120):
        window=int(time.time()//60)
        row=tx.one('''INSERT INTO rate_limits(key,bucket,hits) VALUES(?,?,1)
          ON CONFLICT(key) DO UPDATE SET hits=CASE WHEN rate_limits.bucket=excluded.bucket THEN rate_limits.hits+1 ELSE 1 END,bucket=excluded.bucket RETURNING hits''',(key,window))
        if row['hits']>limit:
            # Commit the counter before returning a 429, rather than rolling it back.
            tx.connection.commit()
            raise APIError('Please slow down and try again in a minute',429)

    @app.get('/')
    def home():
        return send_from_directory(ROOT/'static','index.html')

    @app.get('/health')
    def health():
        with app.store.transaction() as tx:
            tx.one('SELECT 1 AS ok')
        return jsonify(status='ok',storage='postgresql' if app.store.url else 'sqlite',version='2.1.0')

    @app.route('/api/session',methods=['GET','POST'])
    def guest():
        if request.method=='POST':
            token=secrets.token_urlsafe(32)
            user=digest(token)
            # Only Vercel's trusted edge IP header is used on its platform.
            ip=request.headers.get('X-Vercel-Forwarded-For',request.remote_addr) if os.environ.get('VERCEL') else request.remote_addr
            with app.store.transaction(user) as tx:
                throttle(tx,'new:'+digest(ip or 'unknown'),12)
                variant='diverse' if int(user[:8],16)%2 else 'balanced'
                now=time.time()
                tx.execute('INSERT INTO sessions VALUES(?,?,?,?,1)',(user,now,now+MAX_AGE,variant))
            response=jsonify(variant=variant,personalized=True,expires_in=MAX_AGE)
            response.set_cookie(COOKIE,token,httponly=True,secure=secure,samesite='Lax',max_age=MAX_AGE)
            return response
        user=identity()
        with app.store.transaction(user) as tx:
            info=session(tx,user)
            interests=profile(tx,user,bool(info['personalized']))
        return jsonify(variant=info['variant'],personalized=bool(info['personalized']),profile=interests)

    @app.get('/api/feed')
    def feed():
        user=identity()
        topic=request.args.get('topic','All')
        if topic not in TOPICS+['All']:
            raise APIError('Unknown topic')
        with app.store.transaction(user) as tx:
            info=session(tx,user)
            throttle(tx,'user:'+user)
            interests=profile(tx,user,bool(info['personalized']))
            videos=tx.rows('''SELECT v.* FROM videos v WHERE v.status='approved'
               AND NOT EXISTS(SELECT 1 FROM feedback f WHERE f.token_hash=? AND f.video=v.id AND (f.kind='report' OR (f.kind IN ('watch','skip') AND f.created>?)))''',(user,time.time()-1800))
            if topic!='All':
                videos=[v for v in videos if v['topic']==topic]
            items=rank(videos,interests,info['variant'],user)
        return jsonify(items=[{k:v for k,v in item.items() if k not in ('features','exploration')} for item in items],profile=interests,variant=info['variant'],personalized=bool(info['personalized']))

    @app.post('/api/impressions')
    def impression():
        user=identity()
        data=body()
        video=data.get('video')
        if type(video) is not int:
            raise APIError('video must be an integer')
        with app.store.transaction(user) as tx:
            info=session(tx,user)
            throttle(tx,'user:'+user)
            item=tx.one("SELECT * FROM videos WHERE id=? AND status='approved'",(video,))
            if not item:
                raise APIError('Video unavailable',404)
            interests=profile(tx,user,bool(info['personalized']))
            scored=rank([item],interests,info['variant'],user)[0]
            exposure=uuid.uuid4().hex
            tx.execute('INSERT INTO impressions VALUES(?,?,?,?,?,?,?,?)',(exposure,user,video,time.time(),info['variant'],0,json.dumps(scored['features']),scored['score']))
        return jsonify(impression=exposure)

    @app.post('/api/events')
    def feedback():
        user=identity()
        data=body()
        if data.get('kind') not in ('watch','like','skip','report'):
            raise APIError('Invalid feedback kind')
        for key in ('event_id','impression'):
            if not isinstance(data.get(key),str) or not 1<=len(data[key])<=100:
                raise APIError('Invalid '+key)
        watch=data.get('watch',0)
        if type(watch) not in (int,float) or not math.isfinite(watch) or not 0<=watch<=1:
            raise APIError('watch must be a finite fraction between 0 and 1')
        with app.store.transaction(user) as tx:
            session(tx,user)
            throttle(tx,'user:'+user)
            exposure=tx.one('SELECT * FROM impressions WHERE id=? AND token_hash=?',(data['impression'],user))
            if not exposure:
                raise APIError('Impression does not belong to this session',403)
            if time.time()-exposure['created']>3600:
                raise APIError('Impression expired')
            # Bound reported viewing time by elapsed wall time, with startup tolerance.
            video=tx.one('SELECT duration FROM videos WHERE id=?',(exposure['video'],))
            watch=min(watch,(time.time()-exposure['created']+1)/video['duration'],1)
            tx.execute('''INSERT INTO feedback VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',(data['event_id'],user,data['impression'],exposure['video'],data['kind'],watch,time.time()))
        return jsonify(ok=True)

    @app.patch('/api/preferences')
    def preferences():
        user=identity()
        enabled=body().get('personalized')
        if type(enabled) is not bool:
            raise APIError('personalized must be boolean')
        with app.store.transaction(user) as tx:
            session(tx,user)
            throttle(tx,'user:'+user)
            tx.execute('UPDATE sessions SET personalized=? WHERE token_hash=?',(int(enabled),user))
        return jsonify(personalized=enabled)

    @app.get('/api/privacy/export')
    def export():
        user=identity()
        with app.store.transaction(user) as tx:
            info=session(tx,user)
            throttle(tx,'user:'+user)
            events=tx.rows('SELECT event_id,impression,video,kind,watch,created FROM feedback WHERE token_hash=? ORDER BY created',(user,))
            exposures=tx.rows('SELECT id,video,created,variant,score,features FROM impressions WHERE token_hash=? ORDER BY created',(user,))
        return jsonify(preferences=dict(personalized=bool(info['personalized']),variant=info['variant']),events=events,impressions=exposures)

    @app.delete('/api/privacy')
    def erase():
        user=identity()
        with app.store.transaction(user) as tx:
            session(tx,user)
            tx.execute('DELETE FROM sessions WHERE token_hash=?',(user,))
            tx.execute('DELETE FROM rate_limits WHERE key=?',('user:'+user,))
        response=jsonify(ok=True)
        response.delete_cookie(COOKIE,secure=secure,httponly=True,samesite='Lax')
        return response

    @app.get('/api/stats')
    def stats():
        user=identity()
        with app.store.transaction(user) as tx:
            session(tx,user)
            counts=tx.one('SELECT count(*) AS count FROM feedback WHERE token_hash=?',(user,))
            videos=tx.one("SELECT count(*) AS count FROM videos WHERE status='approved'")
        model=json.loads(MODEL_PATH.read_text())
        return jsonify(videos=videos['count'],events=counts['count'],model=dict(type=model['type'],version=model['version'],dataset=model['dataset'],test_log_loss=model['test_log_loss']),retention_days=30)

    def admin():
        expected=os.environ.get('ADMIN_TOKEN_HASH','')
        token=request.headers.get('Authorization','').removeprefix('Bearer ')
        if not expected or not secrets.compare_digest(digest(token),expected):
            raise APIError('Not found',404)

    @app.get('/api/maintenance')
    def maintenance():
        expected=os.environ.get('CRON_SECRET','')
        supplied=request.headers.get('Authorization','').removeprefix('Bearer ')
        if not expected or not secrets.compare_digest(supplied,expected):
            raise APIError('Not found',404)
        with app.store.transaction() as tx:
            tx.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            tx.execute('DELETE FROM rate_limits WHERE bucket<?',(int(time.time()//60)-1440,))
        return jsonify(ok=True)

    @app.post('/api/admin/catalog')
    def ingest():
        admin()
        data=body()
        required={'id','title','topic','caption','creator','media_url','poster_url','duration','quality','popularity','source','license'}
        if not required<=data.keys() or type(data['id']) is not int or data['topic'] not in TOPICS:
            raise APIError('Invalid catalog entry')
        for key in ('title','caption','creator','source','license'):
            if not isinstance(data[key],str) or not 1<=len(data[key])<=300:
                raise APIError('Invalid '+key)
        for key in ('media_url','poster_url'):
            url=data[key]
            if not isinstance(url,str) or not url.startswith('/static/media/') or '..' in url or not (ROOT/url.lstrip('/')).is_file():
                raise APIError('Media must be an existing reviewed local asset')
        for key,maximum in [('duration',300),('quality',1),('popularity',1)]:
            if type(data[key]) not in (float,int) or not math.isfinite(data[key]) or not 0<data[key]<=maximum:
                raise APIError('Invalid '+key)
        with app.store.transaction() as tx:
            tx.execute('INSERT INTO videos VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(data['id'],data['title'],data['topic'],data['caption'],data['creator'],data['media_url'],data['poster_url'],data['duration'],data['quality'],data['popularity'],time.time(),'pending',data['source'],data['license']))
        return jsonify(status='pending'),201

    @app.patch('/api/admin/catalog/<int:video>')
    def moderate(video):
        admin()
        status=body().get('status')
        if status not in ('pending','approved','blocked'):
            raise APIError('Invalid moderation status')
        with app.store.transaction() as tx:
            if not tx.one('SELECT id FROM videos WHERE id=?',(video,)):
                raise APIError('Video not found',404)
            tx.execute('UPDATE videos SET status=? WHERE id=?',(status,video))
        return jsonify(status=status)

    return app


app=create_app()
logging.basicConfig(level=logging.INFO)

if __name__=='__main__':
    from waitress import serve
    serve(app,host='127.0.0.1',port=int(os.environ.get('PORT',8000)))
