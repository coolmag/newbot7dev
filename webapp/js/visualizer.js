// js/visualizer.js

import * as elements from './elements.js';

let audioCtx;
let analyser;
let dataArray;
let isInitialized = false;

function initAudioAnalyser() {
    if (isInitialized || !elements.audio) return;
    try {
        console.log('[Visualizer] Initializing AudioContext...');
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 64; // Keep it low-res for this visual effect
        
        const source = audioCtx.createMediaElementSource(elements.audio);
        source.connect(analyser);
        analyser.connect(audioCtx.destination);
        
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        isInitialized = true;
        
        // Start the animation loop
        animateSunRays();
    } catch (e) {
        console.error('Audio visualizer initialization failed:', e);
    }
}

function animateSunRays() {
    if (!isInitialized || !elements.sunRays) return;
    
    // Keep the loop going
    requestAnimationFrame(animateSunRays);
    
    analyser.getByteFrequencyData(dataArray);
    const rays = elements.sunRays.querySelectorAll('.sun-ray');
    if (!rays) return;
    
    rays.forEach((ray, i) => {
        const dataIndex = Math.floor((i / rays.length) * dataArray.length);
        const value = dataArray[dataIndex] || 0;
        
        // Map the 0-255 value to a height and opacity
        const height = 80 + (value / 255) * 60; // 80-140px
        const opacity = 0.4 + (value / 255) * 0.6; // 0.4-1.0
        
        ray.style.height = height + 'px';
        ray.style.opacity = opacity;
    });
}

function generateSunRays() {
    if (!elements.sunRays) return;
    elements.sunRays.innerHTML = '';
    const rayCount = 16;
    for (let i = 0; i < rayCount; i++) {
        const ray = document.createElement('div');
        ray.className = 'sun-ray';
        ray.style.transform = `rotate(${i * (360 / rayCount)}deg)`;
        elements.sunRays.appendChild(ray);
    }
}

/**
 * Initializes the entire visualizer system.
 * Should be called once after a user interaction (like a click).
 */
export function initializeVisualizer() {
    generateSunRays();
    // The AudioContext can only be started after a user gesture.
    // We'll call the analyser init from the first play-button click.
    initAudioAnalyser();
}

/**
 * Call this to resume the AudioContext if it was suspended.
 */
export function resumeAudioContext() {
    if (isInitialized && audioCtx?.state === 'suspended') {
        console.log('[Visualizer] Resuming AudioContext.');
        audioCtx.resume();
    }
}
