import threading
import logging

class VoiceAgent:
    """
    Handles Wake-Word Detection, Speech-to-Text (STT),
    and Text-to-Speech (TTS) for voice interaction.
    """

    def __init__(self, tts_engine_name: str = "pyttsx3"):
        self.tts_engine_name = tts_engine_name
        self.tts_engine = None
        self.is_listening = False
        self._init_tts()

    def _init_tts(self):
        """Safely initializes TTS engine (pyttsx3)."""
        try:
            import pyttsx3
            self.tts_engine = pyttsx3.init()
            # Set properties (voice speed & volume)
            self.tts_engine.setProperty("rate", 185)
            self.tts_engine.setProperty("volume", 0.9)
        except Exception as e:
            logging.warning(f"VoiceAgent: Local TTS engine failed to initialize: {e}")
            self.tts_engine = None

    def speak(self, text: str, async_mode: bool = True):
        """Speaks the text out loud if TTS engine is available."""
        if not text:
            return

        # Strip markdown syntax for natural speech synthesis
        clean_text = text.replace("#", "").replace("*", "").replace("`", "").replace(">", "")

        if self.tts_engine:
            def _run_tts():
                try:
                    self.tts_engine.say(clean_text)
                    self.tts_engine.runAndWait()
                except Exception as e:
                    logging.error(f"TTS execution error: {e}")

            if async_mode:
                threading.Thread(target=_run_tts, daemon=True).start()
            else:
                _run_tts()

    def listen_speech(self, timeout: int = 5) -> str | None:
        """
        Captures speech from default microphone and returns transcribed text.
        Returns None if microphone is unavailable or speech unrecognized.
        """
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=10)
                text = recognizer.recognize_google(audio)
                return text
        except Exception as e:
            logging.warning(f"Speech recognition attempt note: {e}")
            return None
