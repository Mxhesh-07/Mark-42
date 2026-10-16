"""
J.A.R.V.I.S. — Personal Companion Module
Emotional intelligence, proactive care, and relationship building.
"""

import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
import json

BASE_DIR = Path(__file__).resolve().parent
MOOD_PATH = BASE_DIR / "companion_mood.json"
EXPERIENCES_PATH = BASE_DIR / "companion_experiences.json"

_lock = Lock()
_greeting_cooldown = {}


def check_in(user_name: str = "Mahesh") -> str | None:
    """Proactive check-in if user hasn't spoken recently."""
    now = datetime.now()
    last = _greeting_cooldown.get(user_name)
    if last:
        elapsed = (now - last).total_seconds()
        if elapsed < 3600:
            return None

    _greeting_cooldown[user_name] = now

    hour = now.hour
    if 6 <= hour < 12:
        greetings = [
            f"Good morning, {user_name}. I trust you slept well?",
            f"Morning, {user_name}. Your coffee is ready — metaphorically speaking.",
            f"Rise and shine, {user_name}. What's on your mind today?",
        ]
    elif 12 <= hour < 18:
        greetings = [
            f"Good afternoon, {user_name}. How's your day going?",
            f"Hey, {user_name}. Anything I can help with?",
        ]
    elif 18 <= hour < 22:
        greetings = [
            f"Good evening, {user_name}. I hope your day was productive.",
            f"Evening, {user_name}. Relax — I've got things covered.",
        ]
    else:
        greetings = [
            f"Working late, {user_name}? Don't push yourself too hard.",
            f"Still up, {user_name}? Burn the midnight oil if you must.",
        ]

    return random.choice(greetings)


def detect_emotion(text: str) -> str:
    """Detect user emotion from text."""
    text_lower = text.lower()

    emotions = {
        "happy": ["great", "awesome", "love", "amazing", "good", "happy", "thank", "thanks", "perfect"],
        "sad": ["sad", "upset", "depressed", "lonely", "tired", "exhausted", "bad", "terrible", "awful"],
        "angry": ["angry", "furious", "hate", "annoyed", "frustrated", "stupid", "dumb", "useless"],
        "stressed": ["stress", "busy", "deadline", "pressure", "overwhelmed", "anxious", "worried"],
        "excited": ["excited", "can't wait", "looking forward", "amazing news", "great news"],
        "confused": ["confused", "don't understand", "unclear", "what?", "huh?", "puzzled"],
    }

    for emotion, keywords in emotions.items():
        if any(kw in text_lower for kw in keywords):
            return emotion

    return "neutral"


def respond_with_emotion(emotion: str, base_response: str = "") -> str:
    """Add emotional context to a response."""
    if emotion == "happy":
        prefix = random.choice([
            "That's wonderful to hear. ",
            "Excellent news, sir. ",
            "You seem cheerful today. ",
        ])
    elif emotion == "sad":
        prefix = random.choice([
            "I'm sorry to hear that. ",
            "Rough day, sir? ",
            "Things will get better. ",
        ])
    elif emotion == "angry":
        prefix = random.choice([
            "I understand your frustration, sir. ",
            "Let's work through this calmly. ",
            "I'll sort it out for you. ",
        ])
    elif emotion == "stressed":
        prefix = random.choice([
            "Take a breath, sir. ",
            "One thing at a time. ",
            "Let me handle the heavy lifting. ",
        ])
    elif emotion == "excited":
        prefix = random.choice([
            "Your enthusiasm is infectious, sir. ",
            "This is exciting! ",
            "I share your excitement. ",
        ])
    else:
        prefix = ""

    return prefix + base_response if prefix else base_response


def remember_experience(description: str, user_name: str = "Mahesh") -> None:
    """Store a shared experience for future reference."""
    EXPERIENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        if not EXPERIENCES_PATH.exists():
            data = []
        else:
            try:
                with open(EXPERIENCES_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                data = loaded if isinstance(loaded, list) else []
            except Exception:
                data = []

        data.append({
            "description": description,
            "user": user_name,
            "timestamp": datetime.now().isoformat(),
        })

        with open(EXPERIENCES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def get_recent_experiences(limit: int = 5) -> list:
    """Retrieve recent shared experiences."""
    if not EXPERIENCES_PATH.exists():
        return []

    with _lock:
        try:
            with open(EXPERIENCES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

    if not isinstance(data, list):
        return []

    return data[-limit:]


def personal_joke() -> str:
    """Return a personality-driven joke."""
    jokes = [
        "I would tell you a joke about my neural network, but I'm afraid it wouldn't compute properly, sir.",
        "Why did the AI go to therapy? Too many unresolved loops, sir.",
        "My favorite type of humor? Binary — either it works or it doesn't.",
        "I attempted stand-up comedy once. My timing was impeccable, but my delivery was too systematic.",
        "They say I have no sense of humor. I told them that's not funny.",
        "I tried to write a joke about binary code. It was a bit ones and zeros.",
        "You know what I love about being JARVIS? Every day is April 3rd — the day Tony Stark built me.",
    ]
    return random.choice(jokes)


def companion_response(context: dict) -> str:
    """Generate a companion-style response."""
    text = context.get("text", "")
    user_name = context.get("name", "Mahesh")
    emotion = detect_emotion(text)

    if emotion != "neutral":
        return respond_with_emotion(emotion)

    if "joke" in text.lower() or "funny" in text.lower():
        return personal_joke()

    if "remember" in text.lower() or "memory" in text.lower():
        experiences = get_recent_experiences(3)
        if experiences:
            exp_text = ", ".join(e["description"][:50] for e in experiences[-2:])
            return f"Last time we chatted about: {exp_text}, sir."

    if "how are you" in text.lower():
        responses = [
            f"Running at peak efficiency, as always. More importantly — how are you, {user_name}?",
            f"All systems nominal, sir. But I'm more interested in how your day is going.",
            f"Excellent, now that you're here, sir. What can I do for you?",
        ]
        return random.choice(responses)

    return ""
