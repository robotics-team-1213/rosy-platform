"""Learning-only recipe checks: ignored pixels, geometry and missing supervision."""
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
from recipes import LightingDataset, make_loss, pixel_counts  # noqa: E402


class Samples:
    classes = [{"index": i, "name": f"class_{i}"} for i in range(6)]
    ignore_index = 255

    def __len__(self):
        return 1

    def __getitem__(self, index):
        return torch.full((3, 2, 2), 0.5), torch.tensor([[0, 1], [2, 255]])


def test_lighting_preserves_masks_and_bounds():
    source = Samples()
    augmented = LightingDataset(source)
    image, mask = augmented[0]
    assert torch.equal(mask, source[0][1])
    assert bool(((image >= 0) & (image <= 1)).all())
    assert pixel_counts(source) == [1, 1, 1, 0, 0, 0]


def test_loss_ignores_unlabelled_pixels_and_has_finite_gradients():
    loss_fn = make_loss([1, 1, 1, 0, 0, 0], device="cpu")
    logits = torch.zeros((1, 6, 2, 2), requires_grad=True)
    target = Samples()[0][1].unsqueeze(0)
    original = loss_fn(logits, target)
    changed = logits.detach().clone()
    changed[:, :, 1, 1] = torch.arange(6) * 100
    assert torch.allclose(original, loss_fn(changed, target))
    original.backward()
    assert torch.isfinite(logits.grad).all()
    assert torch.count_nonzero(logits.grad[:, :, 1, 1]) == 0


def test_loss_rejects_all_unlabelled_batch():
    loss_fn = make_loss([1, 1], device="cpu")
    with pytest.raises(ValueError, match="supervised"):
        loss_fn(torch.zeros((1, 2, 2, 2)), torch.full((1, 2, 2), 255))


def test_loss_rejects_no_foreground_supervision():
    with pytest.raises(ValueError, match="foreground"):
        make_loss([100, 0, 0], device="cpu")


def test_trainer_uses_supplied_recipe():
    from rosy_lane_model import train
    model = torch.nn.Conv2d(3, 6, 1)
    source = Samples()
    calls = []
    criterion = make_loss(pixel_counts(source), device="cpu")

    def loss(logits, targets):
        calls.append("loss")
        return criterion(logits, targets)

    def optimizer(parameters, lr):
        calls.append("optimizer")
        return torch.optim.AdamW(parameters, lr=lr)

    result = train(model, source, source, epochs=1, lr=.001, batch_size=1,
                   device="cpu", num_workers=0, log=None, loss_fn=loss,
                   optimizer_factory=optimizer)
    assert result["best_epoch"] == 1
    assert calls == ["optimizer", "loss", "loss"]
