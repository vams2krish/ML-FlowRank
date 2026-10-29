import json
import tempfile
import unittest
from pathlib import Path
from scripts.train_product import train,from_exports


class TrainingTests(unittest.TestCase):
    def test_temporal_model_beats_baselines(self):
        with tempfile.TemporaryDirectory() as folder:
            model=train(output=folder+'/model.json')
            self.assertEqual(model['train_rows'],4800)
            self.assertEqual(model['test_rows'],1200)
            self.assertLess(model['test_log_loss'],model['baseline_log_loss'])
            self.assertGreater(model['ranking']['ndcg_at_10'],model['ranking_baseline']['ndcg_at_10'])
            self.assertGreater(model['ranking']['recall_at_10'],model['ranking_baseline']['recall_at_10'])

    def test_unlabeled_impressions_are_not_negatives(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'export.json'
            path.write_text(json.dumps({'events':[],'impressions':[{'id':str(i),'features':'[0,1,1,1]','created':i} for i in range(120)]}))
            with self.assertRaisesRegex(ValueError,'explicitly labeled'):
                from_exports([path])
