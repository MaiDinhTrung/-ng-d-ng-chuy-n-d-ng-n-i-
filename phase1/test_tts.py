import time
import soundfile as sf
import numpy as np
from zerotts import ZeroTTS

t0 = time.time()
tts = ZeroTTS.from_pretrained("zeroweight-ai/ZeroTTS")
print("load_s", round(time.time() - t0, 1), "sample_rate", tts.sample_rate, flush=True)
try:
    print("voices", tts.list_voices() if hasattr(tts, "list_voices") else [a for a in dir(tts) if "voice" in a.lower()], flush=True)
except Exception as e:
    print("voices err", repr(e), flush=True)

text = "Xin chào các bạn, hôm nay trời đẹp quá."
t1 = time.time()
audio = tts.synthesize(text, voice="maichi")
dt = time.time() - t1
a = np.asarray(audio)
dur = a.size / tts.sample_rate
print("shape", a.shape, "dtype", a.dtype, "dur_s", round(dur, 2), "gen_s", round(dt, 2), "rtf", round(dt / dur, 2), flush=True)
tts.save_audio(audio, "out_maichi.wav")
info = sf.info("out_maichi.wav")
print("wav", info.samplerate, info.channels, round(info.duration, 2), "peak", float(np.abs(a).max()), flush=True)
