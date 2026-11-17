"""
State Manager - Conversation state machine for JARVIS
Manages states: STANDBY, LISTENING, UNDERSTANDING, EXECUTING, RESPONDING, INTERRUPTED, RECOVERING
"""

import time
import threading
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

from core.event_bus import event_bus

logger = logging.getLogger(__name__)


class JARVISState(Enum):
    STANDBY = "standby"           # Waiting for wake word
    LISTENING = "listening"       # Actively listening to user
    UNDERSTANDING = "understanding" # Processing user input
    EXECUTING = "executing"       # Running tools/actions
    RESPONDING = "responding"     # Speaking response
    INTERRUPTED = "interrupted"   # User interrupted
    RECOVERING = "recovering"     # Recovering from error


@dataclass
class StateContext:
    """Context for current state"""
    user_input: str = ""
    intent: str = ""
    tools_to_run: list = None
    response_text: str = ""
    error: str = ""
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.tools_to_run is None:
            self.tools_to_run = []
        if self.metadata is None:
            self.metadata = {}


class StateManager:
    """Manages JARVIS conversation state machine"""
    
    def __init__(self):
        self._state = JARVISState.STANDBY
        self._previous_state = JARVISState.STANDBY
        self._context = StateContext()
        self._lock = threading.RLock()
        self._state_history = []
        self._max_history = 100
        self._state_entered_at = time.time()
        
        # Valid transitions.
        #
        # Gemini Live streams the model's audio back *while the user's turn is
        # still open* — there is no discrete "understanding" phase to wait for.
        # So a real playback start can move LISTENING (or even STANDBY, for a
        # proactive reminder) straight to RESPONDING. Without those two edges
        # the shadow state machine sits in LISTENING while the speaker is
        # clearly talking, which is exactly what /api/state showed in testing.
        self._transitions = {
            JARVISState.STANDBY: [JARVISState.LISTENING, JARVISState.RESPONDING,
                                  JARVISState.RECOVERING],
            JARVISState.LISTENING: [JARVISState.UNDERSTANDING, JARVISState.RESPONDING,
                                    JARVISState.STANDBY, JARVISState.INTERRUPTED],
            JARVISState.UNDERSTANDING: [JARVISState.EXECUTING, JARVISState.RESPONDING,
                                        JARVISState.STANDBY, JARVISState.RECOVERING],
            JARVISState.EXECUTING: [JARVISState.UNDERSTANDING,
                                    JARVISState.RESPONDING, JARVISState.STANDBY,
                                    JARVISState.INTERRUPTED, JARVISState.RECOVERING],
            JARVISState.RESPONDING: [JARVISState.STANDBY, JARVISState.LISTENING,
                                     JARVISState.INTERRUPTED, JARVISState.RECOVERING],
            JARVISState.INTERRUPTED: [JARVISState.LISTENING, JARVISState.STANDBY,
                                      JARVISState.RECOVERING],
            JARVISState.RECOVERING: [JARVISState.STANDBY, JARVISState.LISTENING]
        }
    
    @property
    def state(self) -> JARVISState:
        return self._state
    
    @property
    def context(self) -> StateContext:
        return self._context
    
    def transition_to(self, new_state: JARVISState, context_update: Dict[str, Any] = None) -> bool:
        """Transition to a new state if valid"""
        with self._lock:
            if new_state not in self._transitions.get(self._state, []):
                logger.warning(f"Invalid transition: {self._state.value} -> {new_state.value}")
                return False
            
            self._previous_state = self._state
            self._state = new_state
            self._state_entered_at = time.time()
            
            # Update context
            if context_update:
                for key, value in context_update.items():
                    if hasattr(self._context, key):
                        setattr(self._context, key, value)
                    else:
                        self._context.metadata[key] = value
            
            # Record history
            self._state_history.append({
                'from': self._previous_state.value,
                'to': self._state.value,
                'timestamp': self._state_entered_at,
                'context': self._context
            })
            if len(self._state_history) > self._max_history:
                self._state_history.pop(0)
            
            logger.info(f"State transition: {self._previous_state.value} -> {self._state.value}")
            
            # Publish event
            event_bus.publish('state.changed', {
                'previous': self._previous_state.value,
                'current': self._state.value,
                'context': {
                    'user_input': self._context.user_input,
                    'intent': self._context.intent
                }
            }, source='state_manager')
            
            return True
    
    def get_state_duration(self) -> float:
        """Get time spent in current state"""
        return time.time() - self._state_entered_at
    
    def reset_context(self):
        """Reset context for new interaction"""
        with self._lock:
            self._context = StateContext()
    
    def get_history(self):
        """Get state history"""
        with self._lock:
            return list(self._state_history)
    
    def is_busy(self) -> bool:
        """Check if JARVIS is busy (not in standby)"""
        return self._state not in [JARVISState.STANDBY]
    
    def can_interrupt(self) -> bool:
        """Check if current state can be interrupted"""
        return self._state in [JARVISState.RESPONDING, JARVISState.EXECUTING]


# Global state manager instance
state_manager = StateManager()
