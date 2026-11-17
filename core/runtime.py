"""
JARVIS Runtime - Central orchestrator
Coordinates all subsystems through the event bus
"""

import asyncio
import threading
import logging
from typing import Optional, Dict, Any

from core.event_bus import event_bus
from core.state_manager import state_manager, JARVISState

logger = logging.getLogger(__name__)


class JARVISRuntime:
    """Central runtime orchestrator for JARVIS"""
    
    def __init__(self):
        self._running = False
        self._loop = None
        self._thread = None
        self._modules = {}
        self._shutdown_event = threading.Event()
        
        # Subscribe to critical events
        self._setup_event_handlers()
    
    def _setup_event_handlers(self):
        """Setup core event handlers"""
        event_bus.subscribe('audio.wake_word_detected', self._on_wake_word)
        event_bus.subscribe('audio.speech_start', self._on_speech_start)
        event_bus.subscribe('audio.speech_end', self._on_speech_end)
        event_bus.subscribe('audio.interrupt', self._on_interrupt)
        event_bus.subscribe('gemini.response_start', self._on_response_start)
        event_bus.subscribe('gemini.response_end', self._on_response_end)
        event_bus.subscribe('gemini.turn_complete', self._on_turn_complete)
        event_bus.subscribe('tool.execution_start', self._on_tool_start)
        event_bus.subscribe('tool.execution_end', self._on_tool_end)
        event_bus.subscribe('error.occurred', self._on_error)
    
    def register_module(self, name: str, module: Any):
        """Register a subsystem module"""
        self._modules[name] = module
        logger.info(f"Registered module: {name}")
    
    def get_module(self, name: str) -> Optional[Any]:
        """Get a registered module"""
        return self._modules.get(name)
    
    def start(self):
        """Start the runtime"""
        if self._running:
            return
        
        logger.info("Starting JARVIS Runtime...")
        self._running = True
        self._shutdown_event.clear()
        
        # Start event loop in separate thread
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="JARVIS-Runtime")
        self._thread.start()
        
        # Transition to standby (already there on a fresh process — don't
        # manufacture an invalid self-transition warning at every startup).
        if state_manager.state != JARVISState.STANDBY:
            state_manager.transition_to(JARVISState.STANDBY)
        
        logger.info("JARVIS Runtime started")
    
    def stop(self):
        """Stop the runtime"""
        if not self._running:
            return
        
        logger.info("Stopping JARVIS Runtime...")
        self._running = False
        self._shutdown_event.set()
        
        # Stop all modules
        for name, module in self._modules.items():
            try:
                if hasattr(module, 'stop'):
                    module.stop()
                elif hasattr(module, 'close'):
                    module.close()
            except Exception as e:
                logger.error(f"Error stopping module {name}: {e}")
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        
        logger.info("JARVIS Runtime stopped")
    
    def _run_loop(self):
        """Main runtime loop"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        event_bus.set_event_loop(self._loop)
        
        try:
            self._loop.run_until_complete(self._async_main())
        except Exception as e:
            logger.error(f"Error in runtime loop: {e}")
        finally:
            self._loop.close()
    
    async def _async_main(self):
        """Async main loop"""
        while self._running and not self._shutdown_event.is_set():
            # Monitor system health
            await asyncio.sleep(1)
            self._health_check()
    
    def _health_check(self):
        """Check health of all modules"""
        for name, module in self._modules.items():
            try:
                if hasattr(module, 'health_check'):
                    status = module.health_check()
                    if status.get('status') != 'ok':
                        logger.warning(f"Module {name} health: {status}")
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
    
    # Event handlers
    def _on_wake_word(self, event):
        """Handle wake word detection"""
        logger.info("Wake word detected")
        if state_manager.state == JARVISState.STANDBY:
            state_manager.transition_to(JARVISState.LISTENING)
            event_bus.publish('ui.show_listening', {}, source='runtime')

    def _on_speech_start(self, event):
        """Handle speech start (idempotent — VAD and Live both report it)."""
        if state_manager.state == JARVISState.STANDBY:
            state_manager.transition_to(JARVISState.LISTENING)

    def _on_speech_end(self, event):
        """Handle speech end"""
        if state_manager.state == JARVISState.LISTENING:
            state_manager.transition_to(JARVISState.UNDERSTANDING)

    def _on_interrupt(self, event):
        """Handle user interruption"""
        logger.info("User interrupted")
        if state_manager.can_interrupt():
            state_manager.transition_to(JARVISState.INTERRUPTED)
            # main.py owns real cancellation; these events are for other
            # subscribers that still need to stop their own playback.
            event_bus.publish('audio.stop_playback', {}, source='runtime')
            event_bus.publish('gemini.cancel', {}, source='runtime')
            state_manager.transition_to(JARVISState.LISTENING)

    def _on_response_start(self, event):
        """Handle response start.

        The trigger is *real audio playback*, not an output transcription (the
        Live model frequently streams speech without one). Playback can begin
        while the user's turn is still open — LISTENING — or proactively from
        STANDBY, so both are accepted here and in the transition table.
        """
        if state_manager.state in (JARVISState.STANDBY, JARVISState.LISTENING,
                                   JARVISState.UNDERSTANDING,
                                   JARVISState.EXECUTING):
            state_manager.transition_to(JARVISState.RESPONDING)

    def _on_response_end(self, event):
        """Handle response end"""
        if state_manager.state == JARVISState.RESPONDING:
            state_manager.transition_to(JARVISState.STANDBY)

    def _on_turn_complete(self, event):
        """A turn with no spoken reply still has to leave UNDERSTANDING."""
        if state_manager.state in (JARVISState.UNDERSTANDING,
                                   JARVISState.LISTENING,
                                   JARVISState.EXECUTING):
            state_manager.transition_to(JARVISState.STANDBY)

    def _on_tool_start(self, event):
        """Handle tool execution start"""
        if state_manager.state in (JARVISState.UNDERSTANDING,
                                   JARVISState.RESPONDING):
            state_manager.transition_to(JARVISState.EXECUTING)

    def _on_tool_end(self, event):
        """Handle tool execution end"""
        if state_manager.state == JARVISState.EXECUTING:
            state_manager.transition_to(JARVISState.UNDERSTANDING)

    def _on_error(self, event):
        """Handle errors without blocking whoever published the event.

        A sync event handler runs on the publisher's thread — which in the
        live app is the audio loop. Sleeping here would stall the microphone.
        """
        logger.error("Error occurred: %s", event.data)
        if state_manager.state != JARVISState.RECOVERING:
            state_manager.transition_to(JARVISState.RECOVERING)
            if self._loop and self._loop.is_running():
                self._loop.call_later(
                    1.0, state_manager.transition_to, JARVISState.STANDBY)
            else:
                threading.Timer(
                    1.0, state_manager.transition_to,
                    args=(JARVISState.STANDBY,)).start()


# Global runtime instance
runtime = JARVISRuntime()
