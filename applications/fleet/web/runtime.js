// Production and connected development use native browser services.
export const voicePlatform = globalThis;
export {openCamera as openRobotCamera} from '/common/webrtc.js';
