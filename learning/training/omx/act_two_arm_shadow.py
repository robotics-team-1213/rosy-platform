"""Shadow binding for the sim-trained two-arm ACT checkpoint (four cameras, twelve joints, optional goal).

`act_inference.ACTShadowInference` takes a one-wrist-camera policy artifact; the two-arm LeRobot checkpoint of
`tools/sim/omx_two_arm_policy.py` has a different input contract, so it has its own binding. The computation is
`Driver.act` of `tools/sim/omx_two_arm_policy_helpers.py` (same processors, same batch keys, uint8/255 CHW images, the
checkpoint's own `observation.environment_state`), and the chunk is the `n_action_steps` actions `select_action` would send.
It reads a checkpoint and returns numbers: no owner, ROS, actuator or registry authority. The result is logged beside a real
IK outcome by `deploy/robot/omx/cell_act_shadow.py` and never executed."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

IMAGE = "observation.images."
STATE, GOAL = "observation.state", "observation.environment_state"
PROMPT = "carry the container of this plan step"  # omx_two_arm_policy_helpers.PROMPT
GOAL_JOINTS_SIZE = 22  # omx_two_arm_policy_helpers.GOAL_SIZE: any other width is site mode


class TwoArmShadowInference:
    """`policy_revision` pins the checkpoint: the leading hex of model.safetensors' sha256 (at least 12 characters)."""

    policy_environment = "sim"

    def __init__(self, checkpoint, policy_revision, steps_file, *, joint_names, device="cpu"):
        root = Path(checkpoint).resolve()
        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256((root / "model.safetensors").read_bytes()).hexdigest()
        if config.get("type") != "act" or config.get("temporal_ensemble_coeff") is not None:
            raise ValueError("a plain ACT checkpoint (no temporal ensemble) is required")
        if len(str(policy_revision)) < 12 or not digest.startswith(str(policy_revision)):
            raise ValueError("policy revision differs from the checkpoint weights")
        features = config["input_features"]
        self.image_views = tuple(key[len(IMAGE):] for key in features if key.startswith(IMAGE))
        shapes = {tuple(features[IMAGE + view]["shape"]) for view in self.image_views}
        self.image_shape = shapes.pop() if len(shapes) == 1 else None
        self.state_size = features[STATE]["shape"][0]
        self.goal_size = features[GOAL]["shape"][0] if GOAL in features else 0
        self.goal_mode, self.goal_sites = ("joints" if self.goal_size == GOAL_JOINTS_SIZE else "site"), ()
        if self.goal_size and self.goal_mode == "site":  # a site goal is only meaningful with the training run's site names
            self.goal_sites = tuple(json.loads(Path(steps_file).read_text(encoding="utf-8")).get("goal_sites") or ())
            if self.goal_size != 2 * (1 + 2 * len(self.goal_sites)):
                raise ValueError("steps file goal_sites do not match the checkpoint's goal width")
        self.policy_revision, self.joint_names = digest[:16], tuple(joint_names)
        import torch
        from lerobot.policies.act.modeling_act import ACTPolicy
        from lerobot.policies.factory import make_pre_post_processors
        self._torch = torch
        self._policy = ACTPolicy.from_pretrained(root, local_files_only=True).to(device).eval()
        self._steps = self._policy.config.n_action_steps
        self._pre, self._post = make_pre_post_processors(
            self._policy.config, pretrained_path=str(root),
            preprocessor_overrides={"device_processor": {"device": str(device)}},
            postprocessor_overrides={"device_processor": {"device": "cpu"}})
        self._device = next(self._policy.parameters()).device

    def infer(self, inputs: dict):
        """inputs: state (float32 [12]), images {view: uint8 HxWx3 RGB}, goal (float32 or None) -> .chunk of [12] rows."""
        torch = self._torch
        if tuple(sorted(inputs["images"])) != tuple(sorted(self.image_views)) or (inputs.get("goal") is None) != (not self.goal_size):
            raise ValueError("inputs differ from the checkpoint's input features")
        batch = {STATE: torch.from_numpy(inputs["state"])[None].to(self._device), "task": [inputs.get("prompt", PROMPT)],
                 **{IMAGE + view: torch.from_numpy(image.copy()).to(self._device).permute(2, 0, 1)[None].float() / 255
                    for view, image in inputs["images"].items()}}
        if self.goal_size:
            batch[GOAL] = torch.from_numpy(inputs["goal"])[None].to(self._device)
        with torch.inference_mode():
            self._policy.reset()
            processed = self._pre(batch)
            chunk = [self._post(self._policy.select_action(processed)).cpu().numpy()[0].tolist() for _ in range(self._steps)]
        if any(len(row) != self.state_size for row in chunk):
            raise ValueError("predicted action width differs from the state")
        return SimpleNamespace(chunk=chunk)
