"""Restore declared vector axes in the isolated LeRobot 0.4.4 training process."""
import importlib.metadata
import runpy


def restore_vectors(values, features, leading_shapes=None):
    leading_shapes = leading_shapes or {}
    for key in ('observation.state', 'action'):
        expected = tuple(leading_shapes.get(key, ())) + tuple(features[key]['shape'])
        if tuple(values[key].shape) != expected:
            values[key] = values[key].reshape(expected)
    return values


def install_vector_shapes():
    if importlib.metadata.version('lerobot') != '0.4.4':
        raise ValueError('vector adapter requires pinned lerobot==0.4.4')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    original = LeRobotDataset.__getitem__

    def getitem(dataset, index):
        temporal = dataset.delta_timestamps or {}
        leading = {key: (len(temporal[key]),) for key in ('observation.state', 'action') if key in temporal}
        return restore_vectors(original(dataset, index), dataset.meta.info['features'], leading)

    LeRobotDataset.__getitem__ = getitem


if __name__ == '__main__':
    install_vector_shapes()
    runpy.run_module('lerobot.scripts.lerobot_train', run_name='__main__')
