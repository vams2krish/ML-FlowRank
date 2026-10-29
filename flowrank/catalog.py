"""Original procedural motion studies; no third-party video dependency."""
TOPICS = ['Technology', 'Cooking', 'Travel', 'Music', 'Fitness', 'Art']
STUDIES = [
    ('Technology', 'Inside the signal', 'A small world made of waves.', 'signal'),
    ('Cooking', 'The slow simmer', 'An abstract study in heat and movement.', 'simmer'),
    ('Travel', 'Somewhere beyond', 'A landscape that never quite stands still.', 'horizon'),
    ('Music', 'Feel the frequency', 'Rhythm, translated into light.', 'frequency'),
    ('Fitness', 'Find your momentum', 'One motion. A thousand possibilities.', 'momentum'),
    ('Art', 'Color in motion', 'Let your eyes wander for a moment.', 'color'),
]


def seed_catalog(now):
    return [dict(id=i*6+j+1, title=title + (f' · Study {i+1}' if i else ''),
                 topic=topic, caption=caption, creator=['form.studio','motion.lab','daily.curiosity'][i%3],
                 media_url=f'/static/media/{slug}.mp4', poster_url=f'/static/media/{slug}.jpg',
                 duration=12., quality=.6 + ((i*7+j*3)%20)/50, popularity=((i*11+j*7)%30)/30,
                 created=now-(i*6+j)*7200, status='approved', source='FlowRank original · CC0',
                 license='CC0-1.0')
            for i in range(4) for j,(topic,title,caption,slug) in enumerate(STUDIES)]
