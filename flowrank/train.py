"""Deterministic synthetic-data training; no external packages required."""
import json
import math
import random
from .engine import Engine, FEATURES, sigmoid


def train(path='data/flowrank.db'):
    rng = random.Random(2026)
    samples = []
    for _ in range(6000):
        x = [rng.uniform(-1, 1), rng.random(), rng.random(), rng.random()]
        y = int(rng.random() < sigmoid(-1.5 + sum(a*b for a, b in zip(x, [3., 1.2, .6, .8]))))
        samples.append((x, y))
    training, test = samples[:4800], samples[4800:]
    weights, bias = [0.] * 4, 0.
    for _ in range(60):
        rng.shuffle(training)
        for x, y in training:
            error = sigmoid(bias + sum(a*b for a, b in zip(x, weights))) - y
            weights = [w - .015 * (error * f + .001 * w) for w, f in zip(weights, x)]
            bias -= .015 * error
    predictions = [sigmoid(bias + sum(a*b for a, b in zip(x, weights))) for x, _ in test]
    loss = -sum(y * math.log(p) + (1-y) * math.log(1-p) for p, (_, y) in zip(predictions, test)) / len(test)
    prevalence = sum(y for _, y in training) / len(training)
    baseline = -sum(y * math.log(prevalence) + (1-y) * math.log(1-prevalence) for _, y in test) / len(test)
    model = {'type': 'logistic regression', 'features': FEATURES, 'weights': weights, 'bias': bias,
             'dataset': 'synthetic; no real-world performance claims', 'train_rows': len(training), 'test_rows': len(test),
             'test_log_loss': round(loss, 4), 'baseline_log_loss': round(baseline, 4)}
    engine = Engine(path)
    engine.db.execute('INSERT OR REPLACE INTO models VALUES(1,?)', (json.dumps(model),))
    engine.db.commit()
    engine.db.close()
    return model


if __name__ == '__main__':
    print(json.dumps(train(), indent=2))
