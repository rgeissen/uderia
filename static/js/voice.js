/**
 * voice.js
 * * This module handles the client-side voice recognition functionality.
 * It uses the browser's SpeechRecognition API to capture voice, convert it to text,
 * and manage the UI state of the voice input button.
 */

import * as DOM from './domElements.js';
import { state } from './state.js';
import * as UI from './ui.js';
import { handleChatSubmit } from './eventHandlers.js?v=3.4';
import { classifyConfirmation } from './utils.js';

// --- Speech Recognition Setup ---

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition;

if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';
} else {
    if (DOM.voiceInputButton) {
        DOM.voiceInputButton.style.display = 'none';
    }
}

let isListening = false;
let isStopping = false;
let silenceTimer = null;
let lastTranscript = '';
const SILENCE_TIMEOUT = 1200; // 1.2 seconds of silence
let confirmationCallback = null;

// --- Event Handlers for Recognition ---

/**
 * Handles the 'result' event from the SpeechRecognition API.
 * It processes transcriptions and uses a timeout to detect when the user has stopped speaking.
 * @param {SpeechRecognitionEvent} event - The event object from the API.
 */
const onRecognitionResult = (event) => {
    if (isStopping) {
        // console.log("Ignoring result because recognition is stopping.");
        return;
    }
    clearTimeout(silenceTimer);

    let interim_transcript = '';
    let final_transcript_part = '';

    for (let i = event.resultIndex; i < event.results.length; ++i) {
        const transcript_part = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
            final_transcript_part += transcript_part;
        } else {
            interim_transcript += transcript_part;
        }
    }

    const currentTranscript = (final_transcript_part + interim_transcript).trim();
    lastTranscript = currentTranscript;


    if (state.ttsState === 'AWAITING_OBSERVATION_CONFIRMATION') {
        const confirmationStatus = classifyConfirmation(currentTranscript);
        if (confirmationStatus === 'yes' || confirmationStatus === 'no') {
            isStopping = true;
            stopRecognition();
            return;
        }
    }

    DOM.userInput.value = lastTranscript;

    if (final_transcript_part.trim()) {
        const dummyEvent = new Event('submit');
        Object.defineProperty(dummyEvent, 'preventDefault', { value: () => {} });
        handleChatSubmit(dummyEvent, 'voice');
        lastTranscript = '';
    } else if (lastTranscript) {
        silenceTimer = setTimeout(() => {
            stopRecognition();
        }, SILENCE_TIMEOUT);
    }
};


/**
 * Handles the 'end' event from the SpeechRecognition API.
 * Submits any buffered transcript and restarts recognition if the voice mode is locked.
 */
const onRecognitionEnd = async () => {
    isListening = false;
    isStopping = false;
    clearTimeout(silenceTimer);

    // --- State machine for confirmation flow ---
    if (state.ttsState === 'AWAITING_OBSERVATION_CONFIRMATION') {
        const finalConfirmationText = lastTranscript; // Capture the final text

        // Clear buffers immediately to prevent any bleed-over
        lastTranscript = '';
        DOM.userInput.value = '';

        // Await the callback (e.g., audio playback) to complete
        if (confirmationCallback) {
            await confirmationCallback(finalConfirmationText);
            confirmationCallback = null; // Clear callback after use
        }

        // NOW it's safe to reset the state
        state.ttsState = 'IDLE';
        state.ttsObservationBuffer = '';

        // --- MODIFICATION START: Prevent automatic restart after confirmation ---
        // After a confirmation, we always stop listening, regardless of key state,
        // and reset any temporary voice mode.
        if (state.isTempVoiceMode) {
            state.isTempVoiceMode = false;
        }
        UI.updateVoiceModeUI();
        // --- MODIFICATION END ---

        return; // IMPORTANT: End the function here to prevent normal chat submission
    }
    // --- End of confirmation flow logic ---

    // --- Normal chat submission flow ---
    if (lastTranscript) {
        const dummyEvent = new Event('submit');
        Object.defineProperty(dummyEvent, 'preventDefault', { value: () => {} });
        handleChatSubmit(dummyEvent, 'voice');
        lastTranscript = '';
    }

    if (state.isVoiceModeLocked) {
        setTimeout(() => {
            if (state.isVoiceModeLocked) startRecognition();
        }, 100);
    } else {
        UI.updateVoiceModeUI();
    }
};


/**
 * Handles errors from the SpeechRecognition API.
 * @param {SpeechRecognitionErrorEvent} event - The error event object.
 */
const onRecognitionError = (event) => {
    console.error('Speech recognition error:', event.error);
    if (event.error === 'not-allowed') {
        if (window.showAppBanner) {
            window.showAppBanner('Microphone access denied. Please allow microphone access in your browser settings to use the voice feature.', 'error');
        }
    }
    if (confirmationCallback) {
        confirmationCallback('error');
        confirmationCallback = null;
    }
};

// --- Public API ---

/**
 * Starts the speech recognition process for a normal chat query.
 */
export function startRecognition() {
    if (!recognition || isListening) {
        return;
    }
    try {
        isStopping = false;
        lastTranscript = '';
        DOM.userInput.value = '';
        recognition.start();
        isListening = true;
    } catch (e) {
    }
}

/**
 * Starts a one-time recognition process to capture a user's confirmation.
 * @param {function(string): void} callback - The function to call with the transcribed text.
 */
export function startConfirmationRecognition(callback) {
    if (!recognition || isListening) {
        if (callback) callback('busy');
        return;
    }
    confirmationCallback = callback;
    try {
        isStopping = false;
        lastTranscript = '';
        recognition.start();
        isListening = true;
    } catch (e) {
        if (confirmationCallback) {
            confirmationCallback('error');
            confirmationCallback = null;
        }
    }
}

/**
 * Stops the speech recognition process.
 */
export function stopRecognition() {
    if (!recognition || !isListening) {
        return;
    }
    clearTimeout(silenceTimer);
    recognition.stop();
    isListening = false;
}

/**
 * Initializes the voice module.
 */
export function initializeVoiceRecognition() {
    if (recognition) {
        recognition.addEventListener('result', onRecognitionResult);
        recognition.addEventListener('end', onRecognitionEnd);
        recognition.addEventListener('error', onRecognitionError);
    }
}

