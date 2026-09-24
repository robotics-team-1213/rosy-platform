# apps

Only `control` remains here. Sensing and `robot.yaml` live in this package; it is not an application, and its legacy final publisher must not run beside `core`.

`emotion` is `src/face/emotion`. `games` is `src/site/games`. `omx_adapter` is `src/products/omx_adapter`. Moving `control` to `src/core/control` was blocked because this directory is locked on the machine.
