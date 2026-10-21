"""Evaluate saved/reloaded policies against held-out actions; no physical success inference."""
import numpy as np

from experiment_dataset import chunk_indices


def evaluate_reloaded(reloaded, dataset, tensors, features, stats, *, method, declared_bounds):
    import torch
    from experiment_train import transform_action

    errors, baseline_errors = [], []
    with torch.no_grad():
        for episode in dataset.split('eval'):
            reloaded.reset()
            for index in range(len(episode.arrays['action'])):
                if index and chunk_indices(episode, index - 1, 2)[1] is None:
                    reloaded.reset()
                values = tensors[episode.metadata['id']]
                batch = {key: values[key][index].unsqueeze(0) for key in features}
                prediction = reloaded.select_action(batch)[0].cpu().numpy()
                normal = stats['action']
                if method == 'hilserl':
                    prediction = transform_action(prediction, normal, inverse=True,
                                                  declared=declared_bounds)
                else:
                    prediction = prediction * normal['std'] + normal['mean']
                if not np.isfinite(prediction).all():
                    raise ValueError('nonfinite reloaded policy prediction')
                truth = episode.arrays['action'][index]
                errors.append(float(np.abs(prediction - truth).mean()))
                baseline_errors.append(float(np.abs(np.asarray(normal['mean']) - truth).mean()))
    evaluation = dict(frames=len(errors), action_mae=float(np.mean(errors)),
        constant_train_mean_mae=float(np.mean(baseline_errors)), split='eval',
        task_success='unverified', test_split_used=False, weights_reloaded=True)
    return evaluation
