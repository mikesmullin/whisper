"""
Audio Recorder with Real-time Speech-to-Text

Multiprocessing architecture:
- Process 1: Audio recording worker (continuous mic capture)
- Process 2: Main transcription worker (large model for final accuracy)
- Process 3: Realtime transcription worker (tiny model for instant preview)
- Main thread: Callbacks, UI coordination

Based on RealtimeSTT architecture, optimized for low latency.
"""

import collections
import logging
import multiprocessing as mp
import numpy as np
import queue
import threading
import time
from ctypes import c_bool
from faster_whisper import WhisperModel
from typing import Optional, Callable

try:
    import sounddevice as sd
except ImportError:
    import pyaudio

from lib.vad import VoiceActivityDetector

logger = logging.getLogger(__name__)


class AudioRecorder:
    """
    Real-time audio recorder with dual-model transcription
    
    Features:
    - Dual WhisperModel system (tiny for preview, large for accuracy)
    - WebRTC + Silero VAD for fast speech detection
    - Multiprocessing for parallel recording and transcription
    - Configurable callbacks for realtime updates and final transcription
    """
    
    def __init__(
        self,
        # Model configuration
        model: str = "large-v2",
        realtime_model: str = "tiny.en",
        language: str = "en",
        device: str = "cpu",
        compute_type: str = "int8",
        
        # VAD configuration
        webrtc_sensitivity: int = 3,
        silero_sensitivity: float = 0.05,
        silero_use_onnx: bool = True,
        
        # Audio configuration
        sample_rate: int = 16000,
        buffer_size: int = 512,  # Silero requires >=512, WebRTC uses first 480
        mic_device: Optional[int] = None,
        
        # Timing configuration
        min_length_of_recording: float = 1.1,
        post_speech_silence_duration: float = 0.6,
        pre_recording_buffer_duration: float = 1.0,
        
        # Realtime transcription configuration
        enable_realtime_transcription: bool = True,
        realtime_processing_pause: float = 0.02,
        
        # Beam search configuration
        beam_size: int = 5,
        beam_size_realtime: int = 3,
        
        # Callbacks
        on_recording_start: Optional[Callable] = None,
        on_recording_stop: Optional[Callable] = None,
        on_realtime_transcription_update: Optional[Callable[[str], None]] = None,
        on_transcription_complete: Optional[Callable[[str], None]] = None,
        
        # Logging
        verbose: bool = False
    ):
        """
        Initialize audio recorder
        
        Args:
            model: Main model for final transcription (e.g., "large-v2", "medium", "base")
            realtime_model: Fast model for preview (e.g., "tiny.en", "tiny")
            language: Language code (e.g., "en", "es", "fr")
            device: "cpu" or "cuda"
            compute_type: "int8", "float16", or "float32"
            
            webrtc_sensitivity: 0-3, higher = less sensitive
            silero_sensitivity: 0.0-1.0, lower = more sensitive
            silero_use_onnx: Use ONNX for faster CPU inference
            
            sample_rate: Audio sample rate (16000 Hz recommended)
            buffer_size: Audio buffer size (512 recommended)
            mic_device: Microphone device index (None = auto-detect)
            
            min_length_of_recording: Minimum speech duration to transcribe (seconds)
            post_speech_silence_duration: Silence duration before finalizing (seconds)
            pre_recording_buffer_duration: Buffer before speech starts (seconds)
            
            enable_realtime_transcription: Enable instant preview transcription
            realtime_processing_pause: Interval between preview updates (seconds)
            
            beam_size: Beam size for main model
            beam_size_realtime: Beam size for realtime model
            
            on_recording_start: Callback when recording starts
            on_recording_stop: Callback when recording stops
            on_realtime_transcription_update: Callback for preview updates (text)
            on_transcription_complete: Callback for final transcription (text)
            
            verbose: Enable verbose logging
        """
        self.model_name = model
        self.realtime_model_name = realtime_model
        self.language = language
        self.device = device
        self.compute_type = compute_type
        
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        self.mic_device = mic_device
        
        self.min_length_of_recording = min_length_of_recording
        self.post_speech_silence_duration = post_speech_silence_duration
        self.pre_recording_buffer_duration = pre_recording_buffer_duration
        
        self.enable_realtime_transcription = enable_realtime_transcription
        self.realtime_processing_pause = realtime_processing_pause
        
        self.beam_size = beam_size
        self.beam_size_realtime = beam_size_realtime
        
        # Callbacks
        self.on_recording_start = on_recording_start
        self.on_recording_stop = on_recording_stop
        self.on_realtime_transcription_update = on_realtime_transcription_update
        self.on_transcription_complete = on_transcription_complete
        
        self.verbose = verbose
        
        # Initialize VAD
        logger.info("Initializing VAD system...")
        self.vad = VoiceActivityDetector(
            webrtc_sensitivity=webrtc_sensitivity,
            silero_sensitivity=silero_sensitivity,
            silero_use_onnx=silero_use_onnx,
            sample_rate=sample_rate
        )
        
        # Load transcription models
        logger.info(f"Loading main transcription model: {model}")
        self.main_model = WhisperModel(
            model,
            device=device,
            compute_type=compute_type
        )
        logger.info(f"✓ Main model loaded: {model}")
        
        if enable_realtime_transcription:
            logger.info(f"Loading realtime transcription model: {realtime_model}")
            self.realtime_model = WhisperModel(
                realtime_model,
                device=device,
                compute_type=compute_type
            )
            logger.info(f"✓ Realtime model loaded: {realtime_model}")
        else:
            self.realtime_model = None
        
        # Audio buffer (circular buffer for pre-recording)
        self.audio_buffer = collections.deque(
            maxlen=int((sample_rate // buffer_size) * pre_recording_buffer_duration)
        )
        
        # Recording state
        self.is_recording = False
        self.is_running = False
        self.is_paused = False  # Pause VAD processing (e.g., when hotkey toggles listening off)
        self.cancel_pending_transcriptions = False  # Flag to cancel pending transcriptions
        self.frames = []
        self.silence_count = 0
        self.max_silence_chunks = int(
            (sample_rate / buffer_size) * post_speech_silence_duration
        )
        
        # Threading
        self.recording_thread = None
        self.realtime_thread = None
        self.stream = None
        
        # Statistics
        self.transcription_count = 0
        self.recording_start_time = 0
        
        logger.info("✓ Audio recorder initialized")
    
    def start(self):
        """Start the audio recorder"""
        if self.is_running:
            logger.warning("Audio recorder already running")
            return
        
        self.is_running = True
        
        # Detect microphone if not specified
        if self.mic_device is None:
            self.mic_device = self._auto_detect_microphone()
        
        # Start recording thread
        self.recording_thread = threading.Thread(
            target=self._recording_worker,
            daemon=True
        )
        self.recording_thread.start()
        
        # Start realtime transcription thread if enabled
        if self.enable_realtime_transcription:
            self.realtime_thread = threading.Thread(
                target=self._realtime_worker,
                daemon=True
            )
            self.realtime_thread.start()
        
        logger.info(f"✓ Audio recorder started (mic device: {self.mic_device})")
    
    def stop(self):
        """Stop the audio recorder"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Wait for threads to finish
        if self.recording_thread:
            self.recording_thread.join(timeout=2.0)
        if self.realtime_thread:
            self.realtime_thread.join(timeout=2.0)
        
        logger.info(f"✓ Audio recorder stopped (transcriptions: {self.transcription_count})")
    
    def pause(self):
        """Pause VAD processing (stop listening for new speech and cancel any ongoing recording)"""
        self.is_paused = True
        self.cancel_pending_transcriptions = True  # Cancel any pending transcriptions
        
        # Cancel any ongoing recording - clear buffers
        if self.is_recording:
            logger.debug("Recording cancelled due to pause")
            self.is_recording = False
            self.frames.clear()
            self.silence_count = 0
    
    def resume(self):
        """Resume VAD processing (start listening for speech)"""
        self.is_paused = False
        self.cancel_pending_transcriptions = False  # Allow transcriptions again
        
        # Clear audio buffer to avoid processing old audio
        self.audio_buffer.clear()
    
    def _auto_detect_microphone(self) -> int:
        """Auto-detect default microphone device"""
        try:
            default_idx = sd.default.device[0]
            device_info = sd.query_devices(default_idx)
            if device_info['max_input_channels'] > 0:
                logger.info(f"Auto-detected microphone: [{default_idx}] {device_info['name']}")
                return default_idx
        except Exception as e:
            logger.warning(f"Could not auto-detect default mic: {e}")
        
        # Fallback: find first microphone
        try:
            devices = sd.query_devices()
            for idx, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    logger.info(f"Using first available mic: [{idx}] {device['name']}")
                    return idx
        except Exception as e:
            logger.error(f"Could not detect any microphone: {e}")
        
        return 0  # Last resort
    
    def _recording_worker(self):
        """Recording worker thread - captures audio and processes VAD"""
        def audio_callback(indata, frames, time_info, status):
            if status:
                logger.warning(f"Audio status: {status}")
            
            # Skip all processing if paused
            if self.is_paused:
                return
            
            # Extract mono audio
            audio_chunk = indata[:, 0].copy()
            
            # Add to circular buffer (for pre-recording)
            self.audio_buffer.append(audio_chunk)
            
            # Check for speech
            is_speech, confidence = self.vad.is_speech(audio_chunk)
            
            if is_speech:
                if not self.is_recording:
                    # Speech detected! Start recording
                    self._start_recording()
                
                # Add to recording frames
                self.frames.append(audio_chunk)
                self.silence_count = 0
                
            elif self.is_recording:
                # Still recording but no speech detected
                self.frames.append(audio_chunk)
                self.silence_count += 1
                
                # Check if silence duration reached
                if self.silence_count >= self.max_silence_chunks:
                    self._stop_recording()
        
        try:
            with sd.InputStream(
                device=self.mic_device,
                channels=1,
                samplerate=self.sample_rate,
                blocksize=self.buffer_size,
                callback=audio_callback
            ):
                logger.info("✓ Audio stream started")
                while self.is_running:
                    time.sleep(0.1)
        except Exception as e:
            logger.error(f"Recording worker error: {e}")
    
    def _start_recording(self):
        """Start recording (called when speech detected)"""
        self.is_recording = True
        self.recording_start_time = time.time()
        
        # Include pre-recording buffer
        self.frames = list(self.audio_buffer)
        self.silence_count = 0
        
        if self.on_recording_start:
            try:
                self.on_recording_start()
            except Exception as e:
                logger.error(f"Error in recording start callback: {e}")
        
        if self.verbose:
            logger.debug("🎤 Recording started")
    
    def _stop_recording(self):
        """Stop recording (called when silence detected)"""
        if not self.is_recording:
            return
        
        self.is_recording = False
        recording_duration = time.time() - self.recording_start_time
        
        # Check minimum duration
        if recording_duration < self.min_length_of_recording:
            if self.verbose:
                logger.debug(f"Recording too short ({recording_duration:.2f}s), discarding")
            self.frames = []
            return
        
        if self.on_recording_stop:
            try:
                self.on_recording_stop()
            except Exception as e:
                logger.error(f"Error in recording stop callback: {e}")
        
        # Concatenate frames and transcribe
        audio_data = np.concatenate(self.frames)
        self.frames = []
        
        if self.verbose:
            logger.debug(f"📝 Recording stopped ({recording_duration:.2f}s), transcribing...")
        
        # Transcribe in separate thread
        threading.Thread(
            target=self._transcribe_final,
            args=(audio_data,),
            daemon=True
        ).start()
    
    def _transcribe_final(self, audio: np.ndarray):
        """Transcribe final audio with main model"""
        # Check if transcription was cancelled
        if self.cancel_pending_transcriptions:
            logger.debug("Final transcription cancelled")
            return
        
        try:
            segments, info = self.main_model.transcribe(
                audio,
                language=self.language,
                beam_size=self.beam_size
            )
            
            # Check again after transcription (in case it was cancelled during processing)
            if self.cancel_pending_transcriptions:
                logger.debug("Final transcription cancelled after processing")
                return
            
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())
            
            full_text = " ".join(text_parts).strip()
            
            if not full_text:
                return
            
            self.transcription_count += 1
            
            if self.on_transcription_complete:
                try:
                    self.on_transcription_complete(full_text)
                except Exception as e:
                    logger.error(f"Error in transcription complete callback: {e}")
        
        except Exception as e:
            logger.error(f"Transcription error: {e}")
    
    def _realtime_worker(self):
        """Realtime transcription worker - provides instant preview"""
        if not self.realtime_model:
            return
        
        last_update_time = 0
        last_text = ""
        
        while self.is_running:
            try:
                # Only process during recording and not cancelled
                if not self.is_recording or not self.frames or self.cancel_pending_transcriptions:
                    time.sleep(0.05)
                    continue
                
                # Throttle updates based on realtime_processing_pause
                current_time = time.time()
                if current_time - last_update_time < self.realtime_processing_pause:
                    time.sleep(0.01)
                    continue
                
                last_update_time = current_time
                
                # Get current audio buffer
                audio_data = np.concatenate(self.frames)
                
                # Transcribe with fast model
                segments, info = self.realtime_model.transcribe(
                    audio_data,
                    language=self.language,
                    beam_size=self.beam_size_realtime
                )
                
                # Check if cancelled during transcription
                if self.cancel_pending_transcriptions:
                    continue
                
                text_parts = []
                for segment in segments:
                    text_parts.append(segment.text.strip())
                
                preview_text = " ".join(text_parts).strip()
                
                # Only update if text changed
                if preview_text and preview_text != last_text:
                    last_text = preview_text
                    
                    if self.on_realtime_transcription_update:
                        try:
                            self.on_realtime_transcription_update(preview_text)
                        except Exception as e:
                            logger.error(f"Error in realtime update callback: {e}")
            
            except Exception as e:
                logger.error(f"Realtime worker error: {e}")
                time.sleep(0.1)
