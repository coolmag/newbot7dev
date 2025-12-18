// js/store.js
import { render } from './renderer.js';
import * as elements from './elements.js';

// The raw state object. This holds the single source of truth for the app.
const state = {
    // --- Player State ---
    playlist: [],
    currentTrackIndex: -1,
    isPlaying: false,
    
    // --- UI State ---
    currentGenre: null,
    isLoading: false,      // For loading playlists from the API
    isAudioLoading: false, // For loading a single audio track file

    // --- Core Objects ---
    // Storing the audio element in the state is a pragmatic choice here,
    // as its own properties (currentTime, duration) are part of the app's state.
    audio: elements.audio, 
};

// The Proxy handler. This is where the reactivity happens.
const handler = {
    set(target, property, value) {
        // Update the property on the raw state object
        target[property] = value;
        
        // Trigger a re-render of the UI.
        // The renderer itself will use requestAnimationFrame to be efficient.
        render();
        
        return true; // Indicate that the set operation was successful
    }
};

// Create the reactive store by wrapping the state object in a Proxy.
const store = new Proxy(state, handler);

// Export the store so other modules can use it.
export default store;