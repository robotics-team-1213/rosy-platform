"""Fresh-process generic ACT evaluation, resetting once per held-out episode."""
import argparse
from pathlib import Path

from experiment_io import read_json, write_json
from experiment_lerobot_entry import restore_vectors
import experiment_lerobot_source as source


def evaluate(root, model):
    import torch
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    torch.set_num_threads(2)
    request = read_json(root/'source-request.json', max_bytes=32*1024**2)
    provenance = read_json(root/'provenance.json', max_bytes=32*1024**2)
    if (source.hashes(root/'dataset') != provenance['files']
            or source.hashes(root/'train-dataset') != provenance['train_files']):
        raise ValueError('evaluation derivative bytes changed')
    train = source.reader(root/'train-dataset')
    policy = ACTPolicy.from_pretrained(model, local_files_only=True)
    pre, post = make_pre_post_processors(policy.config, pretrained_path=str(model))
    policy.eval()
    dimension = request['inspection']['action']['shape'][0]
    mean = torch.as_tensor(train.meta.stats['action']['mean'], dtype=torch.float32).reshape(1, dimension)
    if not torch.isfinite(mean).all():
        raise ValueError('train-only action mean must be finite')
    mappings = {m['source_episode']: m for m in provenance['episode_mapping']}
    reports = {'validation': [], 'eval': []}
    for split in reports:
        for episode in request['split'][split]:
            derived_episode = mappings[episode]['derived_episode']
            data = source.reader(root/'dataset', episodes=[derived_episode])
            error, baseline = torch.zeros(dimension), torch.zeros(dimension)
            samples, count = [], 0
            policy.reset()
            with torch.inference_mode():
                for batch in torch.utils.data.DataLoader(data, batch_size=1, shuffle=False):
                    restore_vectors(batch, provenance['source_info']['features'],
                        {'observation.state': (1,), 'action': (1,)})
                    if int(batch['frame_index'].item()) != count:
                        raise ValueError('evaluation frames must be contiguous from zero')
                    target = batch['action'].detach().clone().cpu().reshape(1, dimension)
                    prediction = post(policy.select_action(pre(batch))).detach().cpu()
                    if (prediction.shape != (1, dimension) or not torch.isfinite(prediction).all()
                            or not torch.isfinite(target).all()):
                        raise ValueError('fresh model predictions/targets must be finite action vectors')
                    error += (prediction-target).abs().reshape(dimension)
                    baseline += (mean-target).abs().reshape(dimension)
                    if len(samples) < 4:
                        samples.append(dict(frame=count, target=target[0].tolist(), predicted=prediction[0].tolist()))
                    count += 1
                    if count == 128:
                        break
            if not count:
                raise ValueError('held-out episode contains no evaluation frames')
            reports[split].append(dict(episode=episode, derived_episode=derived_episode, samples=count,
                mae_per_joint=(error/count).tolist(), train_mean_baseline_mae_per_joint=(baseline/count).tolist(),
                prediction_samples=samples, sampling='first up to 128 contiguous frames', policy_reset=True))
    count = sum(row['samples'] for row in reports['eval'])
    def weighted(key):
        return [sum(row[key][i]*row['samples'] for row in reports['eval'])/count for i in range(dimension)]
    result = dict(samples=count, mae_per_joint=weighted('mae_per_joint'),
        train_mean_baseline_mae_per_joint=weighted('train_mean_baseline_mae_per_joint'),
        joint_names=request['inspection']['action']['names'], units='dataset-native/unverified',
        model_reloaded_in_new_process=True, splits=reports, physical_task_success=None,
        physical_learning_verified=False, inspection_revision=request['inspection']['revision'],
        split_revision=request['split']['revision'], source_revision=request['source_revision'],
        study_id=request['study_id'], project_id=request['project_id'], compute_host=request['compute_host'])
    write_json(root/'evaluation.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.root, args.model)
