"""Limits and source/config compatibility for the isolated handbook experiment."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
import handbook_train
import train
import source_repairs
from unittest.mock import Mock, patch
import policy_train
import handbook_repair
import release_check
import time


class HandbookTests(unittest.TestCase):
    def old_vision_run(self, folder):
        config=json.loads((train.ROOT/'tools/train_handbook_config.json').read_text())
        trainer=handbook_train.HandbookTrainer(folder, config, 1, time.monotonic()+60)
        source=folder/'old_source'
        train.copy_source(train.ROOT/config['start'],source)
        path=source/'src/bot.cpp'
        path.write_text(handbook_repair.vision_source(path.read_text(),reverse=True))
        old=trainer.snapshot(source)
        trainer.state=dict(config=config,runtime=release_check.runtime_signature(config),
            policy_contract=train.source_hash(source),incumbent=old,teacher=old,
            champions=[old],anchors=[],holdouts=[],trials=0,promotions=0,policy_cycles=0)
        trainer.save()
        return trainer, old

    def test_vision_migration_preserves_archives_and_rechecks_new_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            trainer,old=self.old_vision_run(Path(directory))
            original=(trainer.checkpoints/old/'src/bot.cpp').read_bytes()
            cached=trainer.cache/'old_match.json'
            cached.write_text('preserved failed-match evidence')
            self.assertTrue(handbook_repair.migrate(trainer,1))
            new=trainer.state['incumbent']
            self.assertNotEqual(old,new)
            self.assertEqual(train.source_hash(trainer.checkpoints/new),new)
            self.assertEqual(trainer.state['champions'],[new])
            self.assertEqual((trainer.checkpoints/old/'src/bot.cpp').read_bytes(),original)
            self.assertEqual(cached.read_text(),'preserved failed-match evidence')
            self.assertTrue(list(trainer.folder.glob('state.before-vision-*.json')))
            self.assertFalse(handbook_repair.migrate(trainer,1))

    def test_vision_migration_refuses_runtime_changes_and_qualified_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            trainer,_=self.old_vision_run(Path(directory))
            trainer.state['runtime']='different engine/maps'
            trainer.save()
            before=(trainer.folder/'state.json').read_bytes()
            with self.assertRaisesRegex(ValueError,'engine, SDK or maps changed'):
                handbook_repair.migrate(trainer,1)
            self.assertEqual((trainer.folder/'state.json').read_bytes(),before)
            trainer.state['incumbent_validation']={'complete':True}
            trainer.save()
            with self.assertRaisesRegex(ValueError,'unqualified run'):
                handbook_repair.migrate(trainer,1)

    def test_upgrade_preserves_economic_and_sequence_genes(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            prior=folder/'old/checkpoints/accepted/src'
            candidate=folder/'checkpoints/new/src'
            prior.mkdir(parents=True); candidate.mkdir(parents=True)
            for name in ('sequence_weights.h','economy_weights.h'):
                (prior/name).write_text('accepted genes')
                (candidate/name).write_text('fresh defaults')
            (candidate/'main.cpp').write_text('new decision logic')
            trainer=handbook_train.HandbookTrainer.__new__(handbook_train.HandbookTrainer)
            trainer.folder=folder; trainer.checkpoints=folder/'checkpoints'
            trainer.config=dict(start='bots/learner-handbook',submission_max_bytes=4_000_000)
            trainer.state=dict(incumbent='new',imported_genes=dict(run=str(folder/'old'),checkpoint='accepted'))
            trainer.save=Mock()
            def snapshot(path):
                self.assertEqual((path/'src/main.cpp').read_text(),'new decision logic')
                for name in ('sequence_weights.h','economy_weights.h'):
                    self.assertEqual((path/'src'/name).read_text(),'accepted genes')
                return 'inherited'
            trainer.snapshot=snapshot
            with patch.object(policy_train.PolicyTrainer,'load_policy'):
                trainer.load_policy(1,folder/'old')
            self.assertEqual(trainer.state['incumbent'],'inherited')
            self.assertEqual(trainer.state['champions'],['inherited'])

    def test_real_parameter_coverage_and_repair_compatibility(self):
        config=json.loads((train.ROOT/'tools/train_handbook_config.json').read_text())
        train.validate_config(config)
        bot=train.ROOT/config['start']
        self.assertEqual(train.coverage(bot,config)['trainable'],236)
        values=train.read_params(bot,config['parameters'])
        train.validate_gene_rules(values)
        before=train.source_hash(bot)
        source_repairs.repair_movement(bot)
        self.assertEqual(before,train.source_hash(bot))

    def test_upload_limit_applies_to_archive_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'submission.zip'
            with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('src/main.cpp','x'*10000)
            self.assertEqual(handbook_train.check_bundle(path,1000)['source_bytes'],10000)
            self.assertEqual(handbook_train.check_bundle(path)['source_bytes'],10000)
            with zipfile.ZipFile(path,'w',zipfile.ZIP_STORED) as archive:
                archive.writestr('src/main.cpp','x'*900)
            with self.assertRaisesRegex(ValueError,'exceeds'):
                handbook_train.check_bundle(path,1000)


if __name__=='__main__':
    unittest.main()
