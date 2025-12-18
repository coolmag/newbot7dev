// js/events.js

import store from './store.js';
import * as elements from './elements.js';
import * as player from './player.js';
import * as api from './api.js';
import { haptic } from './ui-helpers.js';
import { GENRES, TRENDING, DECADES, MOODS } from './constants.js';

// --- Reusable Logic ---

async function selectGenre(name, searchQuery) {
    if (store.isLoading) {
        console.log("Ignoring genre selection, already loading.");
        return;
    }
    store.isLoading = true;
    store.currentGenre = name;
    
    closeGenresScreen();
    closeDrawers();
    haptic.impact('medium');

    try {
        const playlist = await api.fetchPlaylistByQuery(searchQuery);
        store.playlist = playlist; // The store's proxy will trigger a re-render
        if (playlist.length > 0) {
            player.playTrack(0);
        } else {
            // The renderer should handle showing "No tracks found"
        }
    } catch (e) {
        console.error('Failed to select genre:', e);
        // The renderer should handle showing an error state
    } finally {
        store.isLoading = false;
    }
}

function closeDrawers() {
    elements.subgenreDrawer?.classList.remove('active');
    elements.playlistDrawer?.classList.remove('active');
    elements.overlay?.classList.remove('active');
}

function openGenresScreen() {
    elements.screenGenres?.classList.add('active'); // Add active to the genre drawer
    elements.screenPlayer?.classList.add('blurred'); // Blur the player screen
    elements.overlay?.classList.add('active'); // Activate the overlay
}

function closeGenresScreen() {
    elements.screenGenres?.classList.remove('active'); // Remove active from the genre drawer
    elements.screenPlayer?.classList.remove('blurred'); // Unblur the player screen
    elements.overlay?.classList.remove('active'); // Deactivate the overlay
}


// --- UI Component Builders ---
// These functions are called once at initialization to build the static parts of the UI.

function createChips(container, items) {
    if (!container) return;
    container.innerHTML = '';
    items.forEach(item => {
        const chip = document.createElement('button');
        chip.className = 'chip';
        chip.textContent = item.name;
        chip.onclick = () => {
            selectGenre(item.name, item.search);
            haptic.selection();
        };
        container.appendChild(chip);
    });
}

function renderStaticGenres() {
    if (!elements.genreGrid) return;
    elements.genreGrid.innerHTML = '';
    Object.values(GENRES).forEach(genre => {
        const card = document.createElement('button');
        card.className = 'genre-card';
        card.style.setProperty('--genre-color', genre.color);
        card.innerHTML = `<div class="genre-icon">${genre.icon}</div><div class="genre-name">${genre.name}</div>`;
        
        card.onclick = () => {
            elements.drawerTitle.textContent = genre.name;
            elements.drawerIcon.textContent = genre.icon;
            elements.subgenreList.innerHTML = '';
            Object.values(genre.subgenres).forEach(sub => {
                const item = document.createElement('button');
                item.className = 'subgenre-item';
                item.innerHTML = `<div><div class="subgenre-name">${sub.name}</div><div class="subgenre-styles">${sub.styles}</div></div><span class="material-icons">arrow_forward</span>`;
                item.onclick = () => selectGenre(sub.name, sub.search);
                elements.subgenreList.appendChild(item);
            });
            elements.subgenreDrawer.classList.add('active');
            elements.overlay.classList.add('active');
            haptic.impact('medium');
        };
        elements.genreGrid.appendChild(card);
    });
}

/**
 * Attaches all the application's event listeners to the DOM elements.
 */
export function initializeEventListeners() {
    console.log('[Events] Initializing event listeners...');

    // Player Controls
    elements.playBtn?.addEventListener('click', () => {
        player.togglePlayPause();
        haptic.impact('light');
    });
    elements.nextBtn?.addEventListener('click', () => {
        player.playNext();
        haptic.impact('medium');
    });
    elements.prevBtn?.addEventListener('click', () => {
        player.playPrev();
        haptic.impact('medium');
    });
    elements.rewindBtn?.addEventListener('click', () => {
        player.seek(-10);
        haptic.impact('light');
    });
    elements.forwardBtn?.addEventListener('click', () => {
        player.seek(10);
        haptic.impact('light');
    });

    // Speed Control
    elements.playbackSpeed?.addEventListener('change', (e) => {
        elements.audio.playbackRate = parseFloat(e.target.value);
        haptic.selection();
    });

    // Progress Bar Seeking
    elements.progressContainer?.addEventListener('click', (e) => {
        const audio = elements.audio;
        if (!audio.duration) return;
        const rect = elements.progressContainer.getBoundingClientRect();
        const percent = (e.clientX - rect.left) / rect.width;
        audio.currentTime = percent * audio.duration;
        haptic.impact('light');
    });
    
    // Navigation
    elements.btnGenres?.addEventListener('click', () => {
        openGenresScreen();
        haptic.impact('medium');
    });
    elements.btnBackPlayer?.addEventListener('click', () => {
        closeGenresScreen();
        haptic.impact('medium');
    });
    elements.overlay?.addEventListener('click', closeDrawers);
    
    // --- Initialize static UI parts ---
    createChips(elements.trendingChips, TRENDING);
    createChips(elements.decadeChips, DECADES);
    createChips(elements.moodChips, MOODS);
    renderStaticGenres();
    
    // Genre search (for filtering displayed genre cards)
    elements.genreSearch?.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        if (!elements.genreGrid) return; // Ensure genreGrid exists
        const cards = elements.genreGrid.querySelectorAll('.genre-card');
        cards.forEach(card => {
            const name = card.querySelector('.genre-name')?.textContent.toLowerCase() || '';
            card.style.display = name.includes(query) ? 'flex' : 'none';
        });
    });

    // New event listener for initiating a playlist search on Enter key press
    elements.genreSearch?.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter') {
            const query = e.target.value.trim();
            if (query) {
                // Call the existing selectGenre function with the query
                // Using a generic "Search Results" as the genre name for this dynamic search
                await selectGenre("Search Results", query);
                e.target.value = ''; // Clear the input field after search
            }
            haptic.impact('medium');
            e.preventDefault(); // Prevent form submission or other default behavior
        }
    });

    // Show genres screen initially if no playlist has been loaded
    if (store.playlist.length === 0) {
        openGenresScreen();
    }
}
