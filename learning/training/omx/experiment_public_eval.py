"""Fresh-process, bounded evaluation of public dataset-native joint actions."""
import argparse
from pathlib import Path

from experiment_io import read_json, write_json
import experiment_public_source as source


def evaluate(root, model):
    import torch
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors
    torch.set_num_threads(2)
    receipt = read_json(root/'provenance.json', max_bytes=32*1024*1024)
    if (source.hashes(root/'dataset') != receipt['files']
            or source.hashes(root/'train-dataset') != receipt['train_files']):
        raise ValueError('public evaluation source bytes changed')
    train = LeRobotDataset(source.DERIVED_REPO, root=root/'train-dataset', download_videos=False,
                           video_backend='pyav')
    policy = ACTPolicy.from_pretrained(model, local_files_only=True)
    pre, post = make_pre_post_processors(policy.config, pretrained_path=str(model))
    policy.eval()
    mean = torch.as_tensor(train.meta.stats['action']['mean'], dtype=torch.float32).reshape(1, 6)
    reports = {}
    write_json(root/'progress.json', dict(phase='evaluating'))
    for split, episode in [('validation', 8), ('eval', 9)]:
        data = LeRobotDataset(source.DERIVED_REPO, root=root/'dataset', episodes=[episode],
                              download_videos=False, video_backend='pyav')
        error, baseline, samples, count = torch.zeros(6), torch.zeros(6), [], 0
        policy.reset()
        with torch.inference_mode():
            for batch in torch.utils.data.DataLoader(data, batch_size=1, shuffle=False):
                target = batch['action'].detach().clone().cpu()
                prediction = post(policy.select_action(pre(batch))).detach().cpu()
                if (target.shape != (1, 6) or prediction.shape != (1, 6)
                        or not torch.isfinite(prediction).all()):
                    raise ValueError('public model returned invalid joint actions')
                error += (prediction-target).abs().reshape(6)
                baseline += (mean-target).abs().reshape(6)
                if len(samples) < 4:
                    samples.append(dict(frame=int(batch['frame_index'].item()),
                        target=target[0].tolist(), predicted=prediction[0].tolist()))
                count += 1
                if count >= 128:
                    break
        if not samples:
            raise ValueError('public evaluation contains no frames')
        reports[split] = dict(episode=episode, samples=count, mae_per_joint=(error/count).tolist(),
            train_mean_baseline_mae_per_joint=(baseline/count).tolist(), prediction_samples=samples,
            sampling='first up to 128 ordered frames; bounded offline comparison')
    report = dict(joint_names=source.NAMES, units='dataset-native/unverified',
        model_reloaded_in_new_process=True, split_independence='episode only',
        samples=reports['eval']['samples'], mae_per_joint=reports['eval']['mae_per_joint'],
        train_mean_baseline_mae_per_joint=reports['eval']['train_mean_baseline_mae_per_joint'],
        splits=reports, physical_task_success=None, physical_learning_verified=False)
    write_json(root/'evaluation.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.root, args.model)
