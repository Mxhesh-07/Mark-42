"""
Audio Engine - Independent real-time audio subsystem
Handles mic input, speaker output, VAD, echo guard, noise gating
"""

import asyncio
import threading
import time
import queue
import numpy as np
import pyaudio
from typing import Optional, Callable
import logging

from core.event_bus import event_bus
from core.state_manager import state_manager, JARVISState
from agent import audio

logger = logging.getLogger(__name__)

# Audio config
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

ECHO_GUARD = True
ECHO_GUARD_TAIL_S = 0.55

PLAYBACK_BLOCK_S = 0.12
PLAYBACK_IDLE_S = 0.08


class AudioEngine:
    """Independent audio engine for JARVIS"""
    
    def __init__(self):
        self.pya = audio.open_pyaudio()
        self.input_stream = None
        self.output_stream = None
        self.running = False
        self.listening = False
        self.speaking = False
        self.fed_mode = False       # True when main.py supplies captured chunks
        self.fed_chunks = 0

        # Queues
        self.input_queue = queue.Queue(maxsize=100)
        self.output_queue = queue.Queue(maxsize=50)
        
        # Echo guard
        self._last_play_ts = 0.0
        self._play_lock = threading.Lock()
        
        # Callbacks
        self.on_audio_input = None
        self.on_speech_start = None
        self.on_speech_end = None
        
        # Threads
        self._input_thread = None
        self._output_thread = None
        
        event_bus.subscribe('audio.stop_playback', self._on_stop_playback)
        event_bus.subscribe('audio.start_playback', self._on_start_playback)
    
    def start(self, *, capture: bool = True, playback: bool = True):
        """Start audio engine.

        ``capture=False, playback=False`` puts the engine in *fed* mode: it owns
        no PyAudio streams at all and is driven by :meth:`feed_input`. That is
        how the live app uses it — Gemini Live already owns the microphone and
        speaker, and a second pair of streams would fight over both devices.
        """
        if self.running:
            return

        logger.info("Starting Audio Engine (capture=%s, playback=%s)",
                    capture, playback)
        self.running = True
        self.fed_mode = not (capture or playback)

        # Start input thread
        if capture:
            self._input_thread = threading.Thread(
                target=self._input_loop, daemon=True, name="AudioInput")
            self._input_thread.start()

        # Start output thread
        if playback:
            self._output_thread = threading.Thread(
                target=self._output_loop, daemon=True, name="AudioOutput")
            self._output_thread.start()

        logger.info("Audio Engine started")
    
    def stop(self):
        """Stop audio engine"""
        if not self.running:
            return
        
        logger.info("Stopping Audio Engine...")
        self.running = False
        
        if self.input_stream:
            try:
                self.input_stream.stop_stream()
                self.input_stream.close()
            except:
                pass
        
        if self.output_stream:
            try:
                self.output_stream.stop_stream()
                self.output_stream.close()
            except:
                pass
        
        logger.info("Audio Engine stopped")
    
    def _input_loop(self):
        """Capture audio from microphone"""
        try:
            # Try to open input stream
            self.input_stream = self.pya.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=SEND_SAMPLE_RATE,
                input=True,
                frames_per_buffer=CHUNK_SIZE,
            )
            logger.info("Microphone opened")
            
            while self.running:
                try:
                    data = self.input_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                    
                    # Check echo guard
                    if self._output_playing():
                        continue
                    
                    # Calculate level
                    samples = np.frombuffer(data, dtype=np.int16)
                    level = min(np.abs(samples).mean() / 5000, 1.0)
                    
                    self._accept_input(data, level)
                        
                except Exception as e:
                    logger.error(f"Error in input loop: {e}")
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"Failed to open microphone: {e}")
    
    def _output_loop(self):
        """Play audio to speaker"""
        try:
            self.output_stream = self.pya.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RECEIVE_SAMPLE_RATE,
                output=True,
            )
            logger.info("Speaker opened")
            
            block_size = int(RECEIVE_SAMPLE_RATE * PLAYBACK_BLOCK_S) * 2
            buffer = bytearray()
            
            while self.running:
                try:
                    try:
                        chunk = self.output_queue.get(timeout=PLAYBACK_IDLE_S)
                    except queue.Empty:
                        if buffer:
                            self._play_chunk(bytes(buffer))
                            buffer.clear()
                        if self.speaking:
                            self.speaking = False
                            event_bus.publish('audio.playback_end', {}, source='audio_engine')
                        continue
                    
                    if not self.speaking:
                        self.speaking = True
                        event_bus.publish('audio.playback_start', {}, source='audio_engine')
                    
                    self._mark_output_playing()
                    buffer.extend(chunk)
                    
                    while len(buffer) >= block_size:
                        self._play_chunk(bytes(buffer[:block_size]))
                        del buffer[:block_size]
                        
                except Exception as e:
                    logger.error(f"Error in output loop: {e}")
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"Failed to open speaker: {e}")
    
    def _play_chunk(self, data: bytes):
        """Play a chunk of audio"""
        try:
            self._mark_output_playing()
            self.output_stream.write(data)
        except Exception as e:
            logger.error(f"Error playing audio: {e}")
    
    def _accept_input(self, data: bytes, level: float | None = None) -> None:
        """Queue one captured chunk and announce it on the event bus.

        The chunk travels *in the event* as well as the queue. VAD and wake
        word both listen to ``audio.mic_level``; if each pulled its own copy
        from the queue they would see every other chunk and consume it twice.
        """
        if level is None:
            samples = np.frombuffer(data, dtype=np.int16)
            level = min(np.abs(samples).mean() / 5000, 1.0) if samples.size else 0.0

        event_bus.publish('audio.mic_level',
                          {'level': float(level), 'chunk': data},
                          source='audio_engine')
        try:
            self.input_queue.put_nowait(data)
        except queue.Full:
            try:
                self.input_queue.get_nowait()
                self.input_queue.put_nowait(data)
            except Exception:
                pass

        if self.on_audio_input:
            self.on_audio_input(data)

    def feed_input(self, data: bytes, level: float | None = None) -> None:
        """Accept a 16 kHz PCM chunk captured by the app's own stream.

        No-op unless :meth:`start` was called. Never blocks the caller: the
        audio capture loop must stay at PyAudio's cadence.
        """
        if not self.running or not data:
            return
        self.fed_chunks += 1
        self._accept_input(data, level)

    def play_audio(self, data: bytes):
        """Queue audio for playback"""
        try:
            self.output_queue.put_nowait(data)
        except queue.Full:
            try:
                self.output_queue.get_nowait()
                self.output_queue.put_nowait(data)
            except:
                pass
    
    def get_audio_chunk(self, timeout=1.0):
        """Get audio chunk from input queue"""
        try:
            return self.input_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def _mark_output_playing(self):
        """Mark that audio is playing (for echo guard)"""
        with self._play_lock:
            self._last_play_ts = time.monotonic()
    
    def _output_playing(self) -> bool:
        """Check if audio is currently playing"""
        if not ECHO_GUARD:
            return False
        with self._play_lock:
            return (time.monotonic() - self._last_play_ts) < ECHO_GUARD_TAIL_S
    
    def _on_stop_playback(self, event):
        """Stop playback on interrupt"""
        # Clear output queue
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except:
                break
        if self.speaking:
            self.speaking = False
            event_bus.publish('audio.playback_end', {}, source='audio_engine')
    
    def _on_start_playback(self, event):
        """Start playback"""
        pass
    
    def health_check(self):
        """Health check"""
        return {
            'status': 'ok' if self.running else 'stopped',
            'mode': 'fed' if self.fed_mode else 'standalone',
            'input_stream': self.input_stream is not None,
            'output_stream': self.output_stream is not None,
            'speaking': self.speaking,
            'fed_chunks': self.fed_chunks,
        }


# Global audio engine instance
audio_engine = AudioEngine()
