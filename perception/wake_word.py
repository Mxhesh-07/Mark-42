"""
Wake Word Detection - Always listening for "Hey JARVIS"
"""

import numpy as np
import threading
import time
import logging
from typing import Optional, Callable

try:
    import openwakeword
    from openwakeword.model import Model
    OWW_AVAILABLE = True
except ImportError:
    OWW_AVAILABLE = False

from core.event_bus import event_bus
from perception.audio_engine import audio_engine

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Wake word detection using openWakeWord"""
    
    #: openWakeWord resolves these names against its bundled model directory.
    #: Passing ``None`` is *not* equivalent to the library default of ``[]``:
    #: its constructor calls ``len(wakeword_models)`` and dies with
    #: ``object of type 'NoneType' has no len()`` before any audio is read.
    DEFAULT_MODELS = ("hey_jarvis",)

    def __init__(self, model_path: Optional[str] = None):
        self.model = None
        self.running = False
        self.detected = False
        self.cooldown = 2.0  # seconds between detections
        self.last_detection = 0
        self.on_detected = None

        if OWW_AVAILABLE:
            try:
                # Download/use the pinned models (a no-op when already cached).
                openwakeword.utils.download_models()
                if isinstance(model_path, str) and model_path:
                    models = [model_path]
                elif isinstance(model_path, (list, tuple)) and model_path:
                    models = list(model_path)
                else:
                    models = list(self.DEFAULT_MODELS)
                self.model = Model(
                    wakeword_models=models,
                    inference_framework='onnx'
                )
                logger.info("Wake word model loaded: %s", ", ".join(models))
            except Exception as e:
                logger.error(f"Failed to load wake word model: {e}")
                self.model = None
        else:
            logger.warning("openWakeWord not available")

        event_bus.subscribe('audio.mic_level', self._on_mic_audio)
    
    def start(self):
        """Start wake word detection"""
        if not self.model or self.running:
            return
        
        self.running = True
        logger.info("Wake word detection started - listening for 'Hey JARVIS'")
    
    def stop(self):
        """Stop wake word detection"""
        self.running = False
        logger.info("Wake word detection stopped")
    
    def _on_mic_audio(self, event):
        """Process audio for wake word detection"""
        if not self.running or not self.model:
            return
        
        # Check cooldown
        if time.time() - self.last_detection < self.cooldown:
            return
        
        # The chunk rides in the event so VAD and wake word both see the same
        # samples; only level-only producers need the shared queue fallback.
        audio_chunk = (event.data or {}).get('chunk') or \
            audio_engine.get_audio_chunk(timeout=0.01)
        if audio_chunk is None:
            return
        
        try:
            # Convert to numpy array (16-bit PCM)
            audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
            audio_array = audio_array.astype(np.float32) / 32768.0
            
            # Predict
            prediction = self.model.predict(audio_array)
            
            # Check for wake word
            for wakeword, score in prediction.items():
                if score > 0.5:  # Threshold
                    logger.info(f"Wake word detected: {wakeword} (score: {score:.3f})")
                    self.last_detection = time.time()
                    
                    # Publish event
                    event_bus.publish('audio.wake_word_detected', {
                        'wakeword': wakeword,
                        'score': score
                    }, source='wake_word')
                    
                    if self.on_detected:
                        self.on_detected(wakeword, score)
                    
                    break
        except Exception as e:
            logger.error(f"Error in wake word detection: {e}")
    
    def health_check(self):
        """Health check"""
        return {
            'status': 'ok' if self.running and self.model else 'stopped',
            'model_loaded': self.model is not None
        }


# Global wake word detector instance
wake_word_detector = WakeWordDetector()
