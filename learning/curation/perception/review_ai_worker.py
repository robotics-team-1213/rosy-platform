"""Fixed, single-frame model-PC worker. Outputs candidates, never approvals."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import threading
import time

import cv2
import numpy as np

import qwen_review_completion as completion
import review_masks
import vision_review_drafts as objects
import vlm_mask_feedback as feedback


def execute(snapshot, config, folder):
    models = feedback._get_json(feedback.ENDPOINT + '/api/tags')['models']
    model = next((m for m in models if m['name'] == objects.MODEL), None)
    if model is None or model['digest'] != config['model_digest']:
        raise ValueError('configured model digest differs')
    image = base64.b64decode(snapshot['image'], validate=True)
    if hashlib.sha256(image).hexdigest() != snapshot['image_sha256']:
        raise ValueError('image snapshot differs')
    photo = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if photo is None or photo.shape[:2] != (snapshot['height'], snapshot['width']):
        raise ValueError('image dimensions differ')
    action = snapshot['action']
    if action == 'object_draft':
        first, _ = objects.scaled_boxes(objects.ask(image, feedback.ENDPOINT + '/api/chat',
            120, objects.PROMPT), snapshot['width'], snapshot['height'])
        second, _ = objects.scaled_boxes(objects.ask(image, feedback.ENDPOINT + '/api/chat',
            120, objects.VERIFY_PROMPT), snapshot['width'], snapshot['height']) if first else ([], [])
        return {'boxes': objects.confirmed(first, second)}
    raw = base64.b64decode(snapshot['mask'], validate=True)
    raw = review_masks.from_indexed(raw, snapshot['width'], snapshot['height'], snapshot['binding'])
    human = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    ids = {entry['name']: entry['index'] for entry in snapshot['binding']['classes']}
    if action == 'mask_check':
        overlay = completion.overlay(photo, human, ids['drivable'])
        view = cv2.imencode('.png', cv2.resize(overlay, None, fx=2, fy=2,
                                            interpolation=cv2.INTER_NEAREST))[1].tobytes()
        response = feedback._get_json(feedback.ENDPOINT + '/api/chat', {
            'model': objects.MODEL, 'messages': [{'role': 'user', 'content': feedback.PROMPT,
                'images': [base64.b64encode(value).decode('ascii') for value in (image, view)]}],
            'format': feedback.FORMAT, 'stream': False, 'think': False,
            'options': {'temperature': 0, 'num_predict': 240}})
        return {'feedback': feedback._feedback(json.loads(response['message']['content']))}
    if action != 'pixel_draft':
        raise ValueError('unknown action')
    checkpoint = Path(config['sam_checkpoint'])
    with checkpoint.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != config['sam_checkpoint_sha256']:
            raise ValueError('configured checkpoint digest differs')
    seeds = completion.ask(photo, human, ids['drivable'], feedback.ENDPOINT)
    if not any(seeds.values()):
        return {'mask': base64.b64encode(raw).decode('ascii'), 'added_pixels': 0}
    completion.qwen_points.unload(feedback.ENDPOINT, objects.MODEL)
    import torch
    from sam3.model_builder import build_sam3_video_model
    model_sam = build_sam3_video_model(checkpoint_path=str(checkpoint), load_from_HF=False)
    tracker = model_sam.tracker
    tracker.backbone = model_sam.detector.backbone
    with torch.inference_mode():
        proposals = completion.segment(tracker, folder / 'single-frame', photo, seeds, torch)
        draft = completion.compose(human, proposals, snapshot['binding'])
    return {'mask': base64.b64encode(review_masks.encode(draft)).decode('ascii'),
            'added_pixels': int(np.count_nonzero((human == 255) & (draft != 255)))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--parent-pid', type=int, required=True)
    args = parser.parse_args()
    def watch_parent():
        while os.getppid() == args.parent_pid:
            time.sleep(.5)
        os._exit(1)
    threading.Thread(target=watch_parent, daemon=True).start()
    value = json.loads(args.input.read_text(encoding='utf-8'))
    result = execute(value['snapshot'], value['config'], args.input.parent)
    args.output.write_text(json.dumps(result), encoding='utf-8')


if __name__ == '__main__':
    main()
