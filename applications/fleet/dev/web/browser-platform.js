// Synthetic events exercise the real voice UI without a microphone or speech-pack download.
const listeners = new Set();
class SampleRecognition {
  processLocally = true;
  static async available() { return 'available'; }
  start() { listeners.add(this); }
  stop() { listeners.delete(this); this.onend?.(); }
  abort() { listeners.delete(this); }
}
SampleRecognition.prototype.processLocally = true;
addEventListener('rosy-sample-voice', ({detail}) => {
  for (const recognition of [...listeners]) {
    if (detail.error) {
      recognition.onerror?.({error: detail.error});
    } else {
      const result = [{transcript: String(detail.text || '')}]; result.isFinal = true;
      recognition.onresult?.({results: [result]});
      recognition.stop();
    }
  }
});
export const voicePlatform = {
  isSecureContext: true, SpeechRecognition: SampleRecognition,
  setTimeout: globalThis.setTimeout.bind(globalThis), clearTimeout: globalThis.clearTimeout.bind(globalThis),
  SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } },
  speechSynthesis: {cancel() {}, getVoices: () => [{localService:true, lang:'ko-KR'}], speak() {}},
};
