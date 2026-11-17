"""
Voice Activity Detection using Silero VAD
"""

import numpy as np
import torch
import logging
from typing import Optional, Callable

try:
    from silero_vad import load_silero_vad, read_audio, get_speech_timestamps, VADIterator
    SILERO_AVAILABLE = True
except ImportError:
    SILERO_AVAILABLE = False

from core.event_bus import event_bus
from perception.audio_engine import audio_engine

logger = logging.getLogger(__name__)


class VoiceActivityDetector:
    """Voice Activity Detection using Silero VAD"""
    
    def __init__(self):
        self.model = None
        self.vad_iterator = None
        self.running = False
        self.speech_active = False
        self.threshold = 0.5
        self.sampling_rate = 16000
        
        if SILERO_AVAILABLE:
            try:
                self.model = load_silero_vad()
                self.vad_iterator = VADIterator(
                    self.model,
                    threshold=self.threshold,
                    sampling_rate=self.sampling_rate,
                    min_silence_duration_ms=100
                )
                logger.info("Silero VAD loaded")
            except Exception as e:
                logger.error(f"Failed to load Silero VAD: {e}")
                self.model = None
        else:
            logger.warning("Silero VAD not available")
        
        event_bus.subscribe('audio.mic_level', self._on_audio)
    
    def start(self):
        """Start VAD"""
        if not self.model or self.running:
            return
        self.running = True
        logger.info("VAD started")
    
    def stop(self):
        """Stop VAD"""
        self.running = False
        if self.vad_iterator:
            self.vad_iterator.reset_states()
        logger.info("VAD stopped")
    
    def _on_audio(self, event):
        """Process audio for VAD"""
        if not self.running or not self.vad_iterator:
            return
        
        # The chunk rides in the event. The queue fallback is only for
        # level-only producers: VAD and wake word must see the *same* chunk in
        # the live app, not race each other to drain the shared queue.
        audio_chunk = (event.data or {}).get('chunk') or \
            audio_engine.get_audio_chunk(timeout=0.01)
        if audio_chunk is None:
            return
        
        try:
            # Convert to float tensor
            audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
            audio_float = audio_array.astype(np.float32) / 32768.0
            audio_tensor = torch.from_numpy(audio_float)
            
            # Process
            speech_dict = self.vad_iterator(audio_tensor, return_seconds=False)
            
            if speech_dict:
                if 'start' in speech_dict and not self.speech_active:
                    self.speech_active = True
                    logger.debug("Speech started (VAD)")
                    event_bus.publish('audio.speech_start', {'source': 'vad'}, source='vad')
                
                elif 'end' in speech_dict and self.speech_active:
                    self.speech_active = False
                    logger.debug("Speech ended (VAD)")
                    event_bus.publish('audio.speech_end', {'source': 'vad'}, source='vad')
            
        except Exception as e:
            logger.error(f"Error in VAD: {e}")
    
    def health_check(self):
        """Health check"""
        return {
            'status': 'ok' if self.running and self.model else 'stopped',
            'model_loaded': self.model is not None,
            'speech_active': self.speech_active
        }


# Global VAD instance
vad_detector = VoiceActivityDetector()
