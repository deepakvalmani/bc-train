"""Isolated handbook experiment; existing policy_train.py remains unchanged."""
import zipfile
import tempfile
import shutil
from pathlib import Path
import policy_train
import handbook_repair


def check_bundle(path, limit=4_000_000):
    # The user's cap applies to the uploaded file. Expanded size is reported
    # separately and must not be confused with runtime memory or upload size.
    with zipfile.ZipFile(path) as archive:
        expanded = sum(member.file_size for member in archive.infolist())
        if archive.testzip() or not archive.namelist():
            raise ValueError('Invalid submission archive')
    if path.stat().st_size > limit:
        raise ValueError(f'Submission exceeds {limit} bytes: archive={path.stat().st_size}, source={expanded}')
    return dict(archive_bytes=path.stat().st_size, source_bytes=expanded, limit_bytes=limit)


class HandbookTrainer(policy_train.PolicyTrainer):
    def load_policy(self, *args, **kwargs):
        if self.config.get('start') != 'bots/learner-handbook':
            raise ValueError('This experimental entrypoint requires bots/learner-handbook')
        if self.config.get('submission_max_bytes') != 4_000_000:
            raise ValueError('Expected conservative 4,000,000-byte submission cap')
        existed=(self.folder/'state.json').exists()
        if existed:
            seed=args[0] if args else kwargs.get('seed', 20261016)
            upgrade=args[1] if len(args)>1 else kwargs.get('upgrade_from')
            handbook_repair.migrate(self, seed, upgrade)
        result=super().load_policy(*args, **kwargs)
        if not existed and self.state.get('imported_genes'):
            imported=self.state['imported_genes']
            original=Path(imported['run'])/'checkpoints'/imported['checkpoint']/'src'
            with tempfile.TemporaryDirectory(prefix='inherit_',dir=self.folder) as directory:
                path=Path(directory)
                policy_train.train.copy_source(self.checkpoints/self.state['incumbent'],path)
                # The parent loader imports strategy genes and policy weights.
                # Preserve accepted sequence/economic genes as well.
                for name in ('sequence_weights.h','economy_weights.h'):
                    if (original/name).exists():
                        shutil.copyfile(original/name,path/'src'/name)
                best=self.snapshot(path)
            self.state['incumbent']=best
            self.state['champions']=[best]
            self.save()
        return result

    def publish(self, digest):
        super().publish(digest)
        result=check_bundle(self.checkpoints/digest/'submission.zip', self.config['submission_max_bytes'])
        policy_train.train.atomic_json(self.folder/'submission_size.json',dict(checkpoint=digest,**result))


if __name__ == '__main__':
    policy_train.PolicyTrainer=HandbookTrainer
    policy_train.main()
