"""Pinned release-corrector evaluation and RL cases (split from mapped_stack_fixture, D-766)."""

EVALUATION_CASES = {  # nominal geometry; the release feedback sees a 2-5 mm held-box estimate error
    'nominal-estimate': None,
    'nominal-bc-v0': dict(file='release-corrector-bc-v0.npz',
                          sha256='85713c8ec54190e53729d6df73d5d59f3e6e7d715058bfb7698b3793042b9294'),
    'nominal-bc-v0-rl0': dict(file='release-corrector-bc-v0.npz',
                              sha256='85713c8ec54190e53729d6df73d5d59f3e6e7d715058bfb7698b3793042b9294')}
EVALUATION_CASES['release-episodes-rl0'] = EVALUATION_CASES['nominal-bc-v0']
# RL iterations add a pinned residual and Gaussian exploration (metres) to the BC corrector.
RL_RESIDUALS = {'nominal-bc-v0-rl0': dict(file='release-residual-rl0.npz',
    sha256='c44398fffbefca6bba7ec6e7c7d16895dcab272c6394d4d9e16ea00f66ea0f72', sigma_m=.0002)}
RL_RESIDUALS['release-episodes-rl0'] = RL_RESIDUALS['nominal-bc-v0-rl0']
# rl1: one REINFORCE step on 135 decisions from episode runs 29b7 and 1f81 (rl0: 16/20 episodes settled).
EVALUATION_CASES['release-episodes-rl1'] = EVALUATION_CASES['nominal-bc-v0']
RL_RESIDUALS['release-episodes-rl1'] = dict(file='release-residual-rl1.npz',
    sha256='cf84c0a0d2a878eb072b37b2f2428a315e54899887db583314fbe878739036ed', sigma_m=.0002)
# 0.5 mm exploration on top of the v0 model's ~1 mm residual error pushed the first release past the 1.5 mm
# convergence tolerance (run 3d52), so no decision was recorded.
# rl2: rl1's data again from rl0 inside a 0.2 mm trust region (rl1 itself blocked 31 of 32 episodes, run 9968).
EVALUATION_CASES['release-episodes-rl2'] = EVALUATION_CASES['nominal-bc-v0']
RL_RESIDUALS['release-episodes-rl2'] = dict(file='release-residual-rl2.npz',
    sha256='bb424ece0730ab37b16a8e5dcc43febfeb45070fcd5e3f255eb36680f070c935', sigma_m=.0002)
