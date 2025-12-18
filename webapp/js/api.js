// js/api.js

/**
 * Fetches a playlist from the backend API based on a search query.
 * @param {string} searchQuery The genre or search term.
 * @returns {Promise<Array>} A promise that resolves to the playlist array.
 * @throws {Error} Throws an error if the network request fails or the API returns an error.
 */
export async function fetchPlaylistByQuery(searchQuery) {
    console.log(`[API] Fetching playlist for query: "${searchQuery}"`);
    try {
        const response = await fetch(`/api/player/playlist?query=${encodeURIComponent(searchQuery)}`);
        
        if (!response.ok) {
            // Create a detailed error message
            const errorBody = await response.text();
            throw new Error(
                `HTTP error! Status: ${response.status} - ${response.statusText}. Body: ${errorBody}`
            );
        }
        
        const data = await response.json();
        console.log('[API] Playlist response received:', data);
        
        return data.playlist || [];
    } catch (error) {
        console.error('[API] Failed to fetch playlist:', error);
        // Re-throw the error so the calling function can handle it,
        // for example, by showing an error message to the user.
        throw error;
    }
}
