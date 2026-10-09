"""Spike S1 (sementara): bandingkan Gemini TTS vs Kokoro untuk dua gaya narasi.

Hasil: spike_out/<engine>_<style>_<voice>.wav + ringkasan wpm/hening di log.
Hapus folder spikes/ setelah keputusan TTS diambil.
"""
import os
import re
import subprocess
import sys

OUT = "spike_out"

# Naskah memakai markup Sheet: [pause], [long pause], *penekanan*
SCRIPTS = {
    "dark": (
        "Get up. [pause] I know it hurts. [pause] I know you are tired of starting over.\n\n"
        "But listen to me. [long pause] This is not where you *break*. "
        "This is where you *harden*.\n\n"
        "Every morning you rise when it would be easier to stay down, "
        "you become someone the dark cannot hold. [long pause] So get up. [pause] *Again*."
    ),
    "soft": (
        "Hey. [pause] I know it has been heavy lately.\n\n"
        "No matter how many nights you spent wondering if it gets better, "
        "no matter how *small* you feel right now, [pause]\n\n"
        "you are still here. [long pause] And that is *enough* for today. [pause] Keep going."
    ),
}
STYLE_NOTES = {
    "dark": "a weary voice that slowly hardens into resolve, low and slow at first, firm and intense at the end",
    "soft": "warm, gentle and intimate, speaking slowly like comforting a close friend late at night",
}
GEMINI_VOICES = {"dark": ["Algenib", "Gacrux", "Charon"], "soft": ["Sulafat", "Vindemiatrix", "Achernar"]}
KOKORO_VOICES = {"dark": ["bm_george", "am_michael"], "soft": ["af_heart", "bf_emma"]}


def plain_words(script: str) -> int:
    return len(re.sub(r"\[[^\]]*\]|\*", " ", script).split())


def to_gemini(script: str) -> str:
    s = script.replace("[long pause]", "<long pause>").replace("[pause]", "<short pause>")
    return re.sub(r"\*([^*]+)\*", lambda m: m.group(1).upper(), s)


def to_kokoro(script: str) -> str:
    s = script.replace("[long pause]", "...").replace("[pause]", ",")
    return s.replace("*", "")


def speech_stats(wav: str, words: int) -> str:
    """wpm saat bicara + porsi hening, diukur dengan silencedetect (sama dengan analisis referensi)."""
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", wav], capture_output=True, text=True).stdout)
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", wav, "-af",
                          "silencedetect=noise=-35dB:d=0.25", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    silence = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", log))
    speaking = max(dur - silence, 0.1)
    return f"durasi={dur:.1f}s wpm_bicara={words / speaking * 60:.0f} hening={silence / dur * 100:.0f}%"


def run_gemini():
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    for style, voices in GEMINI_VOICES.items():
        for voice in voices:
            path = f"{OUT}/gemini_{style}_{voice}.wav"
            try:
                resp = client.models.generate_content(
                    model=os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts"),
                    contents=[{"role": "user", "parts": [{
                        "text": to_gemini(SCRIPTS[style]),
                        "speech_metadata": {"style": STYLE_NOTES[style]},
                    }]}],
                    config={"response_modalities": ["AUDIO"],
                            "speech_config": {"voice_config": {"voice": voice}}},
                )
                with open(path, "wb") as f:
                    f.write(resp.candidates[0].content.parts[0].inline_data.data)
                print(f"[+] {path}: {speech_stats(path, plain_words(SCRIPTS[style]))}")
            except Exception as e:  # spike: catat lalu lanjut ke suara berikutnya
                print(f"[!] Gemini {style}/{voice} gagal: {e}")


def run_kokoro():
    import soundfile as sf
    from kokoro import KPipeline
    import numpy as np
    for style, voices in KOKORO_VOICES.items():
        for voice in voices:
            pipe = KPipeline(lang_code=voice[0])
            audio = np.concatenate([a for _, _, a in pipe(to_kokoro(SCRIPTS[style]), voice=voice, speed=0.9)])
            path = f"{OUT}/kokoro_{style}_{voice}.wav"
            sf.write(path, audio, 24000)
            print(f"[+] {path}: {speech_stats(path, plain_words(SCRIPTS[style]))}")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    print("[*] Target referensi: wpm_bicara 158-181, hening 21-25%")
    for name in sys.argv[1:] or ["gemini", "kokoro"]:
        {"gemini": run_gemini, "kokoro": run_kokoro}[name]()
