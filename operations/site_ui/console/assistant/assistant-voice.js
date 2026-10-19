// shortcut: local Korean speech packs are browser-dependent; add AI-PC STT after target-browser acceptance.
export function createVoice({platform = globalThis, onText, onState}) {
  const Recognition = platform.SpeechRecognition;
  let recognition = null, generation = 0, timer = null;
  const supported = () => platform.isSecureContext && Recognition &&
    'processLocally' in Recognition.prototype && typeof Recognition.available === 'function';
  const clearTimer = () => { platform.clearTimeout?.(timer); timer = null; };
  function stopSpeaking() { platform.speechSynthesis?.cancel(); }
  async function available() {
    if (!supported()) return 'unavailable';
    try { return await Recognition.available({langs:['ko-KR'], processLocally:true}); }
    catch { return 'unavailable'; }
  }
  function cancel() {
    generation++; clearTimer();
    const previous = recognition; recognition = null;
    previous?.abort(); stopSpeaking();
  }
  return {
    available,
    async prepare() {
      const state = await available();
      if (state === 'available') return true;
      if (!['downloadable', 'downloading'].includes(state) || typeof Recognition.install !== 'function') return false;
      return await Recognition.install({langs:['ko-KR'], processLocally:true});
    },
    async start() {
      cancel(); const token = generation;
      if (await available() !== 'available' || token !== generation) {
        if (token === generation) onState('unavailable');
        return false;
      }
      let text = '';
      const current = new Recognition();
      current.lang = 'ko-KR'; current.processLocally = true;
      current.continuous = false; current.interimResults = false;
      recognition = current;
      current.onresult = event => {
        if (token !== generation) return;
        text = Array.from(event.results).filter(result => result.isFinal).map(result => result[0].transcript).join(' ').trim();
        if (text.length > 2000) { cancel(); onState('too-long'); }
      };
      current.onerror = event => {
        if (token !== generation) return;
        cancel(); onState(event.error === 'not-allowed' ? 'denied' : 'error');
      };
      current.onend = () => {
        if (token !== generation) return;
        clearTimer(); recognition = null;
        if (text) onText(text);
        onState(text ? 'ready' : 'empty');
      };
      try {
        current.start(); timer = platform.setTimeout(() => current.stop(), 30000); onState('listening');
        return true;
      } catch {
        cancel(); onState('error'); return false;
      }
    },
    stop() { recognition?.stop(); },
    cancel,
    stopSpeaking,
    speak(text) {
      stopSpeaking();
      const synth = platform.speechSynthesis;
      const voice = synth?.getVoices().find(item => item.localService === true && /^ko(?:-|$)/i.test(item.lang));
      if (!voice || !platform.SpeechSynthesisUtterance || recognition) { onState('no-voice'); return false; }
      const utterance = new platform.SpeechSynthesisUtterance(text.slice(0, 4000));
      utterance.lang = 'ko-KR'; utterance.voice = voice;
      synth.speak(utterance); return true;
    },
  };
}
