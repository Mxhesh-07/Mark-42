import speech_recognition as sr
import pyttsx3
import os
import time

engine = pyttsx3.init()

def speak(text):
    print(text)
    engine.say(text)
    engine.runAndWait()

contacts = {
    "dad": "8884854683",
    "anish": "9449750959",
    "kaizer": "7795941232",
    "vicky": "9380035961"
}

def call_number(number):
    os.system(f'adb shell am start -a android.intent.action.CALL -d tel:{number}')

def listen():
    r = sr.Recognizer()

    with sr.Microphone() as source:
        print("Listening...")
        r.adjust_for_ambient_noise(source)
        audio = r.listen(source)

    try:
        command = r.recognize_google(audio).lower()
        print("You said:", command)
        return command
    except:
        return ""

while True:
    command = listen()

    if command.startswith("call "):
        name = command.replace("call ", "").strip()

        if name in contacts:
            speak(f"Calling {name}")
            call_number(contacts[name])
        else:
            speak("Contact not found")