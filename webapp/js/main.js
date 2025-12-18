// js/main.js
import { initializeEventListeners } from './events.js';
import { initializeVisualizer, resumeAudioContext } from './visualizer.js';
import { haptic } from './ui-helpers.js';
import * as elements from './elements.js';

function initializeApp() {
    console.log('[Main] DOM content loaded. Initializing app...');
    
    // Set up all the button clicks and UI interactions.
    // This also builds the static parts of the genre list.
    initializeEventListeners();

    // The visualizer's AudioContext can only be started after a user gesture.
    // We'll hook into the first click on the play button to initialize it fully.
    const initVisualizerOnFirstPlay = () => {
        console.log('[Main] First play action, initializing visualizer...');
        initializeVisualizer();
        // Once initialized, we can remove this specific listener.
        elements.playBtn.removeEventListener('click', initVisualizerOnFirstPlay);
    };
    
    elements.playBtn.addEventListener('click', initVisualizerOnFirstPlay);
    
    // It's also good practice to try resuming the audio context on any user interaction,
    // as browsers might suspend it.
    document.body.addEventListener('click', resumeAudioContext, { once: true });
    
    // Initialize Telegram WebApp features, if available.
    try {
        if (window.Telegram && window.Telegram.WebApp) {
            window.Telegram.WebApp.expand();
            console.log('[Main] Telegram WebApp interface expanded.');
        }
    } catch (e) {
        console.warn('Telegram WebApp script not found or failed to load:', e);
    }

    console.log('[Main] App initialization complete.');
}

// Wait for the DOM to be fully loaded before running the app.
document.addEventListener('DOMContentLoaded', initializeApp);