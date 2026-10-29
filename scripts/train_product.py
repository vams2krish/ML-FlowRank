"""Temporal synthetic evaluation, or opt-in training on explicit session exports."""
import argparse
import json
import math
import random
from pathlib import Path
from flowrank.engine import sigmoid, FEATURES


def fit(rows):
    rng=random.Random(2026)
    weights,bias=[0.]*4,0.
    training=list(rows)
    for _ in range(60):
        rng.shuffle(training)
        for row in training:
            error=sigmoid(bias+sum(a*b for a,b in zip(row['x'],weights)))-row['y']
            weights=[w-.015*(error*x+.001*w) for w,x in zip(weights,row['x'])]
            bias-=.015*error
    return weights,bias


def log_loss(rows,predict):
    return -sum(r['y']*math.log(max(1e-9,predict(r)))+(1-r['y'])*math.log(max(1e-9,1-predict(r))) for r in rows)/len(rows)


def ranking_metrics(rows,predict,k=10):
    groups={}
    for row in rows:
        groups.setdefault(row['query'],[]).append(row)
    ndcg,recall=[],[]
    for group in groups.values():
        positives=sum(r['y'] for r in group)
        if not positives:
            continue
        ranked=sorted(group,key=predict,reverse=True)[:k]
        dcg=sum(r['y']/math.log2(i+2) for i,r in enumerate(ranked))
        ideal=sum(1/math.log2(i+2) for i in range(min(k,positives)))
        ndcg.append(dcg/ideal)
        recall.append(sum(r['y'] for r in ranked)/positives)
    return {'ndcg_at_10':round(sum(ndcg)/len(ndcg),4),'recall_at_10':round(sum(recall)/len(recall),4),'evaluated_queries':len(ndcg)}


def synthetic():
    rng=random.Random(2026)
    rows=[]
    for query in range(300):
        for candidate in range(20):
            x=[rng.uniform(-1,1),rng.random(),rng.random(),rng.random()]
            p=sigmoid(-1.5+sum(a*b for a,b in zip(x,[3.,1.2,.6,.8])))
            rows.append(dict(x=x,y=int(rng.random()<p),created=query*100+candidate,query=query))
    return rows


def from_exports(paths):
    rows=[]
    for path in paths:
        data=json.loads(Path(path).read_text())
        labels={}
        for event in data['events']:
            label=1 if event['kind']=='like' or (event['kind']=='watch' and event['watch']>=.6) else 0 if event['kind'] in ('skip','report') else None
            if label is not None:
                key=event['impression']
                labels[key]=max(label,labels.get(key,0))
        for item in data['impressions']:
            if item['id'] in labels:
                x=json.loads(item['features'])
                if len(x)!=4 or any(type(f) not in (float,int) or not math.isfinite(f) for f in x):
                    raise ValueError('Invalid feature snapshot')
                rows.append(dict(x=x,y=labels[item['id']],created=item['created']))
    rows.sort(key=lambda row:row['created'])
    if len(rows)<100:
        raise ValueError('At least 100 explicitly labeled impressions are required; keep the synthetic model for this demo.')
    return rows


def train(paths=None,output='flowrank/model.json'):
    rows=from_exports(paths) if paths else synthetic()
    cutoff=rows[int(len(rows)*.8)]['created']
    training=[r for r in rows if r['created']<cutoff]
    holdout=[r for r in rows if r['created']>=cutoff]
    if not training or not holdout or len({r['y'] for r in training})!=2:
        raise ValueError('Temporal partitions need both training classes and a nonempty holdout')
    weights,bias=fit(training)
    predict=lambda row:sigmoid(bias+sum(a*b for a,b in zip(weights,row['x'])))
    prevalence=sum(r['y'] for r in training)/len(training)
    model=dict(type='logistic regression',version='2.1.0',features=FEATURES,weights=weights,bias=bias,
               dataset='explicit session exports; selection-biased' if paths else 'synthetic; no real-world performance claims',
               split='chronological 80/20; feature snapshots precede feedback',split_cutoff=cutoff,
               train_rows=len(training),test_rows=len(holdout),test_log_loss=round(log_loss(holdout,predict),4),
               baseline_log_loss=round(log_loss(holdout,lambda r:prevalence),4))
    if not paths:
        model['ranking']=ranking_metrics(holdout,predict)
        model['ranking_baseline']=ranking_metrics(holdout,lambda r:r['x'][3])
    Path(output).parent.mkdir(parents=True,exist_ok=True)
    Path(output).write_text(json.dumps(model,indent=2))
    return model


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--exports',nargs='+')
    parser.add_argument('--output',default='flowrank/model.json')
    args=parser.parse_args()
    print(json.dumps(train(args.exports,args.output),indent=2))
