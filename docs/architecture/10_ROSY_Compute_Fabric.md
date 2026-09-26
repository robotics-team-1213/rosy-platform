# 10. ROSY Compute Fabric Architecture

## 1. Initial Hardware

- Gram 16GB x 4
- RTX 5080 workstation x 1

## 2. Architectural Principle

Do not treat five computers as one virtual PC.

Treat them as a distributed compute fabric.

## 3. Node Roles

### Gram

Suitable for:

- ROSY Control Plane
- ROS 2 bridges
- edge processing
- OpenVINO
- tracking
- video preprocessing
- simulation
- standby workers

### RTX 5080

Suitable for:

- YOLO
- DINO
- segmentation
- VLM
- VLA
- CUDA inference
- TensorRT inference
- training
- model serving

## 4. Compute Job Model

Example:

```yaml
job:
  type: vision.embedding
  model: dino
  priority: realtime

requirements:
  accelerator: gpu_preferred
  ram_mb: 2048

fallback:
  allow_openvino: true
```

## 5. Scheduling Inputs

Scheduler should consider:

- CPU availability
- GPU availability
- RAM
- VRAM
- model residency
- current queue
- network latency
- task deadline
- data locality

## 6. Optional Backend

Ray may be used as an execution backend, but ROSY remains the orchestration owner.

```text
ROSY Scheduler
  -> Compute Adapter
      -> Local Process
      -> CUDA
      -> OpenVINO
      -> Ray
```
