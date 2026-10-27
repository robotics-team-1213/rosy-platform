"""Peak GPU memory of one SmolVLA fine-tune step (forward+backward+AdamW) on OMX-shaped batches.

smolvla_base with the OMX features (state 6, action 6, cameras top/front). Normalization is skipped (no memory
effect); the language tokens come from the policy's own tokenizer. Our share of the GPU is capped so an
out-of-memory error stays in this process.
"""
import json
import sys
import time

import torch
from lerobot.configs.policies import PreTrainedConfig
from lerobot.configs.types import FeatureType, PolicyFeature
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

base, cap_gb, sizes = sys.argv[1], float(sys.argv[2]), [int(s) for s in sys.argv[3].split(',')]
dev = torch.device('cuda')
torch.cuda.set_per_process_memory_fraction(cap_gb * 2**30 / torch.cuda.get_device_properties(0).total_memory)
config = PreTrainedConfig.from_pretrained(base)
config.input_features = {'observation.state': PolicyFeature(FeatureType.STATE, (6,)),
                         **{f'observation.images.{c}': PolicyFeature(FeatureType.VISUAL, (3, 480, 640))
                            for c in ('top', 'front')}}
config.output_features = {'action': PolicyFeature(FeatureType.ACTION, (6,))}
config.device = 'cuda'
policy = SmolVLAPolicy.from_pretrained(base, config=config).to(dev).train()
params = [p for p in policy.parameters() if p.requires_grad]
optimizer = torch.optim.AdamW(params, lr=config.optimizer_lr)
tokenizer = policy.model.vlm_with_expert.processor.tokenizer
weights_gb = torch.cuda.memory_allocated() / 2**30
results = {'weights_gb': round(weights_gb, 2), 'trainable_params': sum(p.numel() for p in params),
           'cap_gb': cap_gb, 'freeze_vision_encoder': config.freeze_vision_encoder,
           'train_expert_only': config.train_expert_only, 'chunk_size': config.chunk_size, 'steps': []}
for batch_size in sizes:
    tokens = tokenizer(['pick the slip sheet and place it on pallet A\n'] * batch_size, padding='max_length',
                       max_length=config.tokenizer_max_length, truncation=True, return_tensors='pt')
    batch = {'observation.state': torch.randn(batch_size, 6, device=dev),
             'observation.images.top': torch.rand(batch_size, 3, 480, 640, device=dev),
             'observation.images.front': torch.rand(batch_size, 3, 480, 640, device=dev),
             'observation.language.tokens': tokens['input_ids'].to(dev),
             'observation.language.attention_mask': tokens['attention_mask'].to(dev).bool(),
             'action': torch.randn(batch_size, config.chunk_size, 6, device=dev),
             'action_is_pad': torch.zeros(batch_size, config.chunk_size, dtype=torch.bool, device=dev)}
    torch.cuda.reset_peak_memory_stats()
    try:
        began = time.monotonic()
        for _ in range(3):  # AdamW allocates its state on the first step; the peak settles by the second.
            loss, _ = policy.forward(batch)
            loss.backward()
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        torch.cuda.synchronize()
        results['steps'].append({'batch': batch_size, 'peak_gb': round(torch.cuda.max_memory_allocated() / 2**30, 2),
                                 'reserved_gb': round(torch.cuda.max_memory_reserved() / 2**30, 2),
                                 'step_s': round((time.monotonic() - began) / 3, 3)})
    except torch.OutOfMemoryError:
        results['steps'].append({'batch': batch_size, 'peak_gb': f'over cap {cap_gb}'})
        break
    finally:
        del batch
        torch.cuda.empty_cache()
print('SMOLVLA_TRAIN_MEM=' + json.dumps(results))
