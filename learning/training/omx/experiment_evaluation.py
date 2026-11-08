"""Evaluate saved/reloaded policies against held-out actions; no physical success inference."""
import numpy as np

from experiment_dataset import chunk_indices


def per_arm_mae(rows, profile):
    """Mean absolute error of each arm: a joint model's mean over all joints can hide one arm doing nothing useful."""
    columns, start, result = np.mean(rows, axis=0), 0, {}
    for arm in profile['arms']:
        end = start + len(arm['joint_names'])
        result[arm['id']] = float(columns[start:end].mean())
        start = end
    return result


def evaluate_reloaded(reloaded, dataset, tensors, features, stats, *, method, declared_bounds):
    import torch
    from experiment_train import transform_action

    errors, baseline_errors, rows, baseline_rows = [], [], [], []
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
                rows.append(np.abs(prediction - truth))
                baseline_rows.append(np.abs(np.asarray(normal['mean']) - truth))
                errors.append(float(rows[-1].mean()))
                baseline_errors.append(float(baseline_rows[-1].mean()))
    evaluation = dict(frames=len(errors), action_mae=float(np.mean(errors)),
        constant_train_mean_mae=float(np.mean(baseline_errors)), split='eval',
        action_mae_per_arm=per_arm_mae(rows, dataset.profile),
        constant_train_mean_mae_per_arm=per_arm_mae(baseline_rows, dataset.profile),
        task_success='unverified', test_split_used=False, weights_reloaded=True)
    return evaluation
