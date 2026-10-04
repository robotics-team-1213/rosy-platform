"""ROS-free recipes informed by now2466/pinky-lane-segmentation@443f63f.

Use the ROSY manifest's classes, not the upstream 4/5-class semantic IDs.
No partial-label/background remapping: 255 remains the only ignored label.
Torch stays lazy, like the export and run-log helpers.
"""
import random


class LightingDataset:
    """Image-only augmentation: preserve geometry and all source labels."""

    def __init__(self, source):
        self.source = source
        self.classes = source.classes
        self.ignore_index = source.ignore_index

    def __len__(self):
        return len(self.source)

    def __getitem__(self, index):
        image, labels = self.source[index]
        return (image * random.uniform(.8, 1.2) + random.uniform(-.06, .06)).clamp(0, 1), labels


def pixel_counts(dataset):
    import torch
    counts = torch.zeros(len(dataset.classes), dtype=torch.int64)
    for index in range(len(dataset)):
        _, mask = dataset[index]
        counts += torch.bincount(mask[mask != dataset.ignore_index].reshape(-1),
                                 minlength=len(counts))
    return counts.tolist()


def make_loss(counts, *, device, dice_weight=.3, ignore_index=255):
    """Weighted CE + masked foreground Dice; absent classes are recorded, not fabricated."""
    import torch
    import torch.nn.functional as functional
    pixels = torch.tensor(counts, dtype=torch.float32, device=device)
    if pixels.ndim != 1 or len(pixels) < 2 or not torch.isfinite(pixels).all() or (pixels < 0).any():
        raise ValueError("pixel counts must be finite nonnegative class counts")
    if not bool((pixels[1:] > 0).any()):
        raise ValueError("need foreground supervision in the training dataset")
    if not 0 <= dice_weight <= 1:
        raise ValueError("dice_weight must be in [0,1]")
    weights = torch.sqrt(pixels.max() / pixels.clamp_min(1)).clamp(1, 6)
    weights[pixels == 0] = 1
    foreground = [index for index in range(1, len(counts)) if counts[index] > 0]

    def criterion(logits, labels):
        valid = labels != ignore_index
        if not bool(valid.any()):
            raise ValueError("batch contains no supervised pixels")
        ce = functional.cross_entropy(logits, labels, weight=weights, ignore_index=ignore_index)
        probabilities = logits.softmax(dim=1)
        scores = []
        for index in foreground:
            probability = probabilities[:, index] * valid
            target = (labels == index) & valid
            intersection = (probability * target).sum()
            scores.append((2 * intersection + 1) / (probability.sum() + target.sum() + 1))
        dice = 1 - torch.stack(scores).mean()
        return ce + dice_weight * dice

    return criterion


def adamw(parameters, lr):
    import torch
    return torch.optim.AdamW(parameters, lr=lr, weight_decay=.0001)
