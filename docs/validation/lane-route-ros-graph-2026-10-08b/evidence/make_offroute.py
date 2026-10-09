#!/usr/bin/env python3
"""Change only recorded odometry frame 192 for the route rejection replay."""
import argparse

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source_npz")
    parser.add_argument("output_npz")
    args = parser.parse_args()
    original = np.load(args.source_npz)
    arrays = {key: original[key].copy() for key in original.files}
    if arrays["frames"].shape[0] != 226 or not np.allclose(
            arrays["gt"][192], (-0.6113245696590683, -0.3893339504233785,
                               1.0233245195868508), atol=1e-9):
        raise ValueError("unexpected guard1 source recording")
    arrays["gt"][192, :2] = (-0.681556215492219, -0.3510257799689326)
    np.savez_compressed(args.output_npz, **arrays)
    print("changed pose index 192 only; image, stamp and command arrays preserved")


if __name__ == "__main__":
    main()
