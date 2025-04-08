import threading
import faulthandler
faulthandler.enable()
import time
import cv2
import socket
import struct
import lgpio
import pyaudio
import numpy as np
from google.cloud import speech
from gtts import gTTS
import google.generativeai as genai
import signal
import sys
import os
import subprocess
from openai import OpenAI
# Configuration Constants
SERVER_HOST = '100.103.107.56'
SERVER_PORT = 5000
BUZZER_PIN = 17
TRIG_PIN = 23
ECHO_PIN = 24
OPENAI_API_KEY = ""  # Replace with your actual OpenAI API key
openai_client = OpenAI(api_key=OPENAI_API_KEY)
# Global State Management
system_events = {
    'program_running': threading.Event(),
    'speech_running': threading.Event(),
    'system_active': threading.Event(),
    'guidance_active': threading.Event(),
    'chat_active': threading.Event(),
    'stop_answer': threading.Event() # Added stop answer event
}

# Hardware Handles
gpio_handle = None
audio_resources = {
    'pyaudio': None,
    'stream': None
}

# Initialize Google Services


def cleanup_resources():
    """Comprehensive resource cleanup with proper ordering"""
    print("System: Cleaning up all resources...")

    # Clear all events
    for event in system_events.values():
        event.clear()

    # Clean up audio resources
    if audio_resources['stream']:
        try:
            audio_resources['stream'].stop_stream()
            audio_resources['stream'].close()
        except Exception as e:
            print(f"Audio stream cleanup error: {e}")
        audio_resources['stream'] = None

    if audio_resources['pyaudio']:
        try:
            audio_resources['pyaudio'].terminate()
        except Exception as e:
            print(f"PyAudio cleanup error: {e}")
        audio_resources['pyaudio'] = None

    # Clean up GPIO resources
    global gpio_handle
    if gpio_handle:
        try:
            lgpio.gpio_write(gpio_handle, BUZZER_PIN, 0)
            lgpio.gpiochip_close(gpio_handle)
        except Exception as e:
            print(f"GPIO cleanup error: {e}")
        gpio_handle = None

def shutdown_program():
    """Orderly shutdown procedure"""
    print("\nSystem: Initiating shutdown sequence...")

    # Signal all components to stop
    for event in system_events.values():
        event.clear()

    cleanup_resources()

    # Allow threads to terminate
    time.sleep(1)
    print("System: Clean shutdown complete.")
    os._exit(0)
system_events['tts_interrupt'] = threading.Event()
def text_to_speech(text):
    """Robust TTS with interrupt capability"""
    temp_path = os.path.abspath("temp.mp3")
    try:
        # Generate speech
        tts = gTTS(text=text, lang='en', slow=False)
        tts.save(temp_path)

        if not os.path.exists(temp_path):
            raise FileNotFoundError("TTS file not created")

        # Play audio with interrupt check
        process = None
        for _ in range(3):
            # Use subprocess to allow killing the playback
            process = subprocess.Popen(['mpg123', '-q', temp_path],
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)

            while process.poll() is None:  # While process is running
                if system_events['stop_answer'].is_set() or system_events['tts_interrupt'].is_set():
                    process.terminate()
                    system_events['stop_answer'].clear()
                    system_events['tts_interrupt'].clear()
                    return
                time.sleep(0.05)  # Check frequently for interruption

            if process.returncode == 0:
                break

    except Exception as e:
        print(f"TTS Error: {e}")
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:
                print(f"File cleanup error: {e}")
        if 'process' in locals() and process.poll() is None:
            process.terminate()

def query_openai(prompt):
    """Query OpenAI API for unrecognized commands."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",  # You can use "gpt-4" if you have access
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error querying OpenAI: {e}")
        return "Sorry, I couldn't process that."

def handle_transcript(transcript):
    """Enhanced voice command processing with immediate response stopping"""
    transcript = transcript.lower()

    # Check for interrupt first, regardless of state
    if "okay" in transcript and system_events['chat_active'].is_set():
        system_events['tts_interrupt'].set()
        text_to_speech("Response stopped. What's next?")
        return

    if "hi siri" in transcript:
        system_events['system_active'].set()
        text_to_speech("System activated. Say 'guide me', 'chat', or 'system exit'.")

    elif system_events['system_active'].is_set():
        if "guide me" in transcript:
            system_events['guidance_active'].set()
            text_to_speech("Guidance mode activated.")
        elif "stop guidance" in transcript:
            system_events['guidance_active'].clear()
            text_to_speech("Guidance stopped.")
        elif "chat" in transcript:
            system_events['chat_active'].set()
            text_to_speech("Chat mode activated. Say 'okay' to stop a response, 'exit' to end chat.")
        elif "system exit" in transcript:
            shutdown_program()
        elif system_events['chat_active'].is_set():
            if "exit" in transcript:
                system_events['chat_active'].clear()
                text_to_speech("Chat mode stopped.")
            else:
                # Process Gemini query in a separate thread to allow interruption
                def process_gemini_response():
                    response = query_openai(transcript)
                    if not system_events['tts_interrupt'].is_set():
                        text_to_speech(response)

                gemini_thread = threading.Thread(target=process_gemini_response)
                gemini_thread.start()

def audio_stream_generator(stream, chunk, max_duration):
    """Audio generator with duration limit"""
    start_time = time.time()
    while (time.time() - start_time) < max_duration and system_events['program_running'].is_set():
        try:
            data = stream.read(chunk, exception_on_overflow=False)
            yield speech.StreamingRecognizeRequest(audio_content=data)
        except Exception as e:
            print(f"Audio stream error: {e}")
            break

def speech_recognition():
    """Long-running speech recognition with connection recycling"""
    system_events['speech_running'].set()

    while system_events['program_running'].is_set():
        client = None
        try:
            # Reinitialize client every 4 minutes (240 seconds)
            client = speech.SpeechClient()
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code="en-US",
                enable_automatic_punctuation=True,
            )
            streaming_config = speech.StreamingRecognitionConfig(
                config=config,
                interim_results=True
            )

            # Initialize audio resources once
            if not audio_resources['pyaudio']:
                audio_resources['pyaudio'] = pyaudio.PyAudio()

            if not audio_resources['stream']:
                audio_resources['stream'] = audio_resources['pyaudio'].open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=16000,
                    input=True,
                    frames_per_buffer=1024,
                    start=False,
                    input_device_index=0
                )
                audio_resources['stream'].start_stream()

            # Create new generator with 4-minute limit
            generator = audio_stream_generator(audio_resources['stream'], 1024, 240)
            responses = client.streaming_recognize(streaming_config, generator)

            for response in responses:
                if not system_events['program_running'].is_set():
                    break

                if response.results and response.results[0].is_final:
                    transcript = response.results[0].alternatives[0].transcript
                    print(f"Speech: {transcript}")
                    handle_transcript(transcript)

        except Exception as e:
            print(f"Speech recognition error: {e}")
            time.sleep(1)  # Brief pause before reconnecting
        finally:
            # Clean up client while keeping audio resources alive
            if client:
                del client  # Ensure proper cleanup of the client

    system_events['speech_running'].clear()
    print("Speech recognition thread stopped")

def camera_operations():
    """Power-efficient camera processing with frame delay"""
    print("Camera: Starting...")
    try:
        while system_events['program_running'].is_set() and system_events['guidance_active'].is_set():
            start_time = time.time()

            # Capture frame only when needed
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                print("Camera: Open error")
                time.sleep(1)
                continue

            ret, frame = cap.read()
            cap.release()

            if not ret:
                print("Camera: Frame read error")
                time.sleep(1)
                continue

            # Process and send frame
            response = send_frame(frame, SERVER_HOST, SERVER_PORT)
            if response and "Error" not in response:
                text_to_speech(response)

            # Maintain 1 FPS with precise delay
            elapsed = time.time() - start_time
            delay = max(2.0 - elapsed, 0)  # 0.5 FPS
            time.sleep(delay)

    except Exception as e:
        print(f"Camera error: {e}")
    print("Camera: Resources released")


def ultrasonic_operations():
    """Thread-safe ultrasonic operations with dedicated GPIO context"""
    print("Ultrasonic: Starting...")
    local_gpio = None

    try:
        # Create local GPIO handle for thread safety
        local_gpio = lgpio.gpiochip_open(0)
        lgpio.gpio_claim_output(local_gpio, BUZZER_PIN)
        lgpio.gpio_claim_output(local_gpio, TRIG_PIN)
        lgpio.gpio_claim_input(local_gpio, ECHO_PIN)

        last_valid_distance = None

        while system_events['program_running'].is_set() and system_events['guidance_active'].is_set():
            current_time = time.time()

            # Measurement logic with thread-safe GPIO access
            dist = measure_distance(local_gpio, TRIG_PIN, ECHO_PIN)  # Pass local GPIO handle
            if dist is not None:
                if last_valid_distance is None or abs(dist - last_valid_distance) > 5:
                    beep_based_on_distance(local_gpio, dist)  # Pass local GPIO handle
                    last_valid_distance = dist

            time.sleep(0.1)  # Maintain 10Hz refresh rate

    except Exception as e:
        print(f"Ultrasonic thread error: {e}")
    finally:
        if local_gpio:
            lgpio.gpio_write(local_gpio, BUZZER_PIN, 0)
            lgpio.gpiochip_close(local_gpio)
        print("Ultrasonic: Resources released")
def measure_distance(gpio_handle, trig_pin, echo_pin):
    """Accurate distance measurement with error handling"""
    try:
        lgpio.gpio_write(gpio_handle, trig_pin, 0)
        time.sleep(0.00001)

        lgpio.gpio_write(gpio_handle, trig_pin, 1)
        time.sleep(1e-5)
        lgpio.gpio_write(gpio_handle, trig_pin, 0)

        timeout = time.time() + 0.1
        pulse_start = pulse_end = time.time()

        # Wait for echo to go low
        while lgpio.gpio_read(gpio_handle, echo_pin) == 0 and time.time() < timeout:
            pulse_start = time.time()

        # Wait for echo to go high
        while lgpio.gpio_read(gpio_handle, echo_pin) == 1 and time.time() < timeout:
            pulse_end = time.time()

        if time.time() > timeout:
            return None

        pulse_duration = pulse_end - pulse_start
        distance = (pulse_duration * 34300) / 2  # Calculate distance in cm

        # Sanity check
        if distance < 2 or distance > 400:
            return None

        return distance
    except Exception as e:
        print(f"Distance measurement error: {e}")
        return None

def beep_based_on_distance(gpio_handle, distance):
    """Correct PWM configuration for buzzer"""
    try:
        if distance < 50:
            lgpio.gpio_write(gpio_handle, BUZZER_PIN, 1)
            time.sleep(0.1)
            lgpio.gpio_write(gpio_handle, BUZZER_PIN, 0)
            time.sleep(0.05)
        # No else clause needed as we want nothing to happen when distance >= 50
    except Exception as e:
        print(f"Buzzer error: {str(e)}")
def send_frame(frame, host, port):
    """Network operation with proper cleanup"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((host, port))

            _, img_encoded = cv2.imencode('.jpg', frame)
            img_bytes = img_encoded.tobytes()

            s.sendall(struct.pack('>L', len(img_bytes)))
            s.sendall(img_bytes)

            response_size = struct.unpack('>L', s.recv(4))[0]
            return s.recv(response_size).decode()
    except Exception as e:
        print(f"Network error: {e}")
        return None

def main():
    """Main application controller"""
    signal.signal(signal.SIGINT, lambda s, f: shutdown_program())
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google-services.json"
    global gpio_handle
    gpio_handle = lgpio.gpiochip_open(0)
    system_events['program_running'].set()

    try:
        # Start speech recognition thread
        speech_thread = threading.Thread(target=speech_recognition, daemon=True)
        speech_thread.start()

        # Main control loop
        while system_events['program_running'].is_set():
            if system_events['guidance_active'].is_set():
                # Start guidance threads
                camera_thread = threading.Thread(target=camera_operations, daemon=True)
                ultrasonic_thread = threading.Thread(target=ultrasonic_operations, daemon=True)

                camera_thread.start()
                ultrasonic_thread.start()

                # Wait while guidance is active
                while system_events['guidance_active'].is_set():
                    time.sleep(0.5)

                # Cleanup guidance threads
                camera_thread.join(timeout=1)
                ultrasonic_thread.join(timeout=1)
            else:
                time.sleep(0.5)

    except Exception as e:
        print(f"Main error: {e}")
    finally:
        shutdown_program()

if __name__ == "__main__":
    print("System: Starting assistive device...")
    text_to_speech("Assistive system ready. Say Hi siri to begin.")
    main()