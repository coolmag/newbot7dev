// js/ui-helpers.js

/**
 * Formats a duration in seconds into a "m:ss" string.
 * @param {number} seconds The duration in seconds.
 * @returns {string} The formatted time string.
 */
export function formatTime(seconds) {
    if (!isFinite(seconds)) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * A simple haptic feedback helper that checks for support before running.
 * Relies on the Telegram WebApp API.
 */
export const haptic = {
    isSupported: window.Telegram.WebApp.isVersionAtLeast('6.1'),
    impact: (style = 'medium') => {
        if (haptic.isSupported) {
            window.Telegram.WebApp.HapticFeedback.impactOccurred(style);
        }
    },
    notification: (type = 'success') => {
        if (haptic.isSupported) {
            window.Telegram.WebApp.HapticFeedback.notificationOccurred(type);
        }
    },
    selection: () => {
        if (haptic.isSupported) {
            window.Telegram.WebApp.HapticFeedback.selectionChanged();
        }
    }
};
