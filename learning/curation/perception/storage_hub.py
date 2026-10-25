"""Explicit per-job HF credentials; verification streams never populate a disk cache."""
from learning_imports import HFTransport


class StorageHub:
    def info(self, assignment, token):
        from huggingface_hub import HfApi
        value = HfApi(endpoint='https://huggingface.co', token=token).repo_info(repo_id=assignment['repo_id'], repo_type=assignment['repo_type'],
                                           revision=assignment.get('revision'))
        return dict(private=value.private, sha=value.sha)

    def commit(self, assignment, streams, token):
        from huggingface_hub import HfApi, CommitOperationAdd
        info = self.info(assignment, token)
        return HfApi(endpoint='https://huggingface.co', token=token).create_commit(repo_id=assignment['repo_id'], repo_type=assignment['repo_type'],
            parent_commit=info['sha'], commit_message='ROSY storage ' + assignment['id'],
            operations=[CommitOperationAdd(path_in_repo='bundles/' + assignment['id'] + '/' + name,
                                           path_or_fileobj=stream) for name, stream in streams.items()]).oid

    def chunks(self, assignment, name, token):
        return HFTransport().chunks(assignment['repo_type'], assignment['repo_id'], assignment['revision'],
                                    'bundles/' + assignment['id'] + '/' + name, token)
