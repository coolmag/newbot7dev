// js/renderer.js

import store from './store.js';
import * as elements from './elements.js';
import { formatTime } from './ui-helpers.js';

function renderPlayerState() {
    if (!elements.vinylRecord) return; // Guard against elements not present
    elements.vinylRecord.classList.toggle('playing', store.isPlaying);
    elements.tonearm.classList.toggle('playing', store.isPlaying);
    elements.sunRays.classList.toggle('playing', store.isPlaying);
    elements.vinylGlow.classList.toggle('active', store.isPlaying);
    elements.playIcon.textContent = store.isPlaying ? 'pause' : 'play_arrow';
}

function renderTrackInfo() {
    if (!elements.titleEl) return;
    const track = store.playlist[store.currentTrackIndex];
    if (track) {
        elements.titleEl.textContent = track.title || 'Unknown';
        elements.artistEl.textContent = track.artist || 'Unknown';
    } else {
        elements.titleEl.textContent = "Select a genre";
        elements.artistEl.textContent = "Tap 🎵 to browse music";
    }
}

function renderLoadingState() {
    if (!elements.titleEl) return;
    if (store.isLoading) {
        elements.titleEl.textContent = "Loading playlist...";
        elements.artistEl.textContent = "Accessing the Grid...";
    } else if (store.isAudioLoading) {
        const track = store.playlist[store.currentTrackIndex];
        // Only show "Loading audio..." if we have track info to display
        if (track) {
             elements.titleEl.textContent = track.title || 'Loading...';
             elements.artistEl.textContent = "Loading audio...";
        }
    }
}

function renderProgress() {
    if (!elements.progressEl || !store.audio) return;
    if (store.audio.duration) {
        const progress = (store.audio.currentTime / store.audio.duration) * 100;
        elements.progressEl.style.width = progress + '%';
        elements.progressHandle.style.left = progress + '%';
        elements.currTimeEl.textContent = formatTime(store.audio.currentTime);
        elements.durTimeEl.textContent = formatTime(store.audio.duration);
    }
}

/**
 * The main render function for the application.
 * It reads from the global store and updates the DOM to reflect the current state.
 */
export function render() {
    // We request animation frame for performance, to ensure DOM updates are smooth
    // and batched together by the browser.
    window.requestAnimationFrame(() => {
        console.log('[Renderer] Re-rendering UI with new state.');
        
        renderPlayerState();
        renderTrackInfo();
        renderLoadingState(); // This should be called after track info to override it if loading
        renderProgress();
    });
}
