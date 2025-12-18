// js/player.js

import store from './store.js';
import * as elements from './elements.js';

let audioLoadTimeout = null;

function cleanupAudioListeners() {
    const audio = elements.audio;
    if (!audio) return;
    audio.removeEventListener('canplay', handleCanPlay);
    audio.removeEventListener('error', handleError);
    audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
    audio.removeEventListener('ended', playNext);
    audio.removeEventListener('timeupdate', handleTimeUpdate);
    audio.removeEventListener('play', handlePlay);
    audio.removeEventListener('pause', handlePause);
}

// --- Audio Event Handlers ---
// These functions are called by the audio element's events.
// Their only job is to update the central store.

function handleCanPlay() {
    console.log('[Player] Event: canplay');
    clearTimeout(audioLoadTimeout);
    store.isAudioLoading = false;
    safePlay(); // Attempt to play now that it's ready
}

function handleError(e) {
    console.error("[Player] Event: error", e);
    clearTimeout(audioLoadTimeout);
    store.isAudioLoading = false;
    // We could add an error message to the store here
    setTimeout(playNext, 1500); // Try the next track after a short delay
}

function handleLoadedMetadata() {
    console.log('[Player] Event: loadedmetadata');
    clearTimeout(audioLoadTimeout);
    // The renderer will handle updating the duration from the audio element
}

function handleTimeUpdate() {
    // This event fires rapidly. Instead of setting state here and causing
    // too many re-renders, we let the renderer read directly from the
    // audio element's properties inside a requestAnimationFrame loop.
    // This is a performance optimization.
}

function handlePlay() {
    store.isPlaying = true;
}

function handlePause() {
    store.isPlaying = false;
}

// --- Player Control Functions ---
// These functions are called by user actions (e.g., button clicks).
// They control the player logic and update the state.

export function playTrack(index) {
    if (store.isAudioLoading || index < 0 || index >= store.playlist.length) {
        if (index >= store.playlist.length) {
            console.log('[Player] Playlist finished.');
            store.isPlaying = false;
            store.currentTrackIndex = -1;
        }
        return;
    }

    store.currentTrackIndex = index;
    store.isAudioLoading = true;
    
    const track = store.playlist[index];
    const audio = elements.audio;
    
    audio.pause();
    cleanupAudioListeners(); // Important: remove old listeners first

    const audioUrl = track.url || `/audio/${track.identifier}`; 
    console.log('[Player] Setting audio src:', audioUrl);
    audio.src = audioUrl;
    
    // Set a timeout to prevent getting stuck on a bad track
    clearTimeout(audioLoadTimeout);
    audioLoadTimeout = setTimeout(() => {
        if (store.isAudioLoading) {
            console.warn("[Player] Track load timeout, skipping...");
            playNext();
        }
    }, 10000); 

    // Add new listeners
    audio.addEventListener('canplay', handleCanPlay);
    audio.addEventListener('error', handleError);
    audio.addEventListener('loadedmetadata', handleLoadedMetadata);
    audio.addEventListener('ended', playNext);
    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('play', handlePlay);
    audio.addEventListener('pause', handlePause);

    audio.load();
    updateMediaSessionMetadata();
}

export function playNext() {
    playTrack(store.currentTrackIndex + 1);
}

export function playPrev() {
    if (elements.audio.currentTime > 3) {
        elements.audio.currentTime = 0;
    } else {
        playTrack(store.currentTrackIndex - 1);
    }
}

export async function safePlay() {
    const audio = elements.audio;
    if (!audio.src) return;
    try {
        await audio.play();
    } catch (err) {
        console.error("Playback error:", err.name, err.message);
        store.isPlaying = false; // Ensure state is correct on error
        if (err.name === 'NotAllowedError') {
            // The renderer should display a message based on this state
            console.log("Playback was prevented by browser autoplay policy.");
        }
    }
}

export function togglePlayPause() {
    if (store.isPlaying) {
        elements.audio.pause();
    } else {
        safePlay();
    }
}

export function seek(offset) {
    const audio = elements.audio;
    if (!isFinite(audio.duration)) return;
    audio.currentTime = Math.max(0, Math.min(audio.duration, audio.currentTime + offset));
}

function updateMediaSessionMetadata() {
    if ('mediaSession' in navigator && store.currentTrackIndex >= 0) {
        const track = store.playlist[store.currentTrackIndex];
        navigator.mediaSession.metadata = new MediaMetadata({
            title: track.title || 'Unknown',
            artist: track.artist || 'Unknown',
            album: store.currentGenre || 'Music',
        });
        
        navigator.mediaSession.setActionHandler('play', togglePlayPause);
        navigator.mediaSession.setActionHandler('pause', togglePlayPause);
        navigator.mediaSession.setActionHandler('previoustrack', playPrev);
        navigator.mediaSession.setActionHandler('nexttrack', playNext);
    }
}
