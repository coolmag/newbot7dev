document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram.WebApp;
    tg.expand();

    // DOM Elements
    const audio = document.getElementById('audio-player');
    const playBtn = document.getElementById('btn-play-pause');
    const playIcon = document.getElementById('icon-play');
    const nextBtn = document.getElementById('btn-next');
    const prevBtn = document.getElementById('btn-prev');
    const titleEl = document.getElementById('track-title');
    const artistEl = document.getElementById('track-artist');
    const progressBarContainer = document.getElementById('progress-bar-container');
    const progressFill = document.getElementById('progress-fill');
    const currTimeEl = document.getElementById('curr-time');
    const durTimeEl = document.getElementById('dur-time');
    const canvas = document.getElementById('visualizer');
    const ctx = canvas.getContext('2d');

    // State
    let audioCtx, analyser, dataArray, isVisualizerInitialized = false;
    let currentTrackId = null, isCommandProcessing = false;

    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    // --- Audio Visualizer ---
    function initAudioVisualizer() {
        if (isVisualizerInitialized || !audio) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioCtx.createAnalyser();
            const source = audioCtx.createMediaElementSource(audio);
            source.connect(analyser);
            analyser.connect(audioCtx.destination);
            analyser.fftSize = 128;
            dataArray = new Uint8Array(analyser.frequencyBinCount);
            isVisualizerInitialized = true;
            renderVisualizer();
        } catch (e) {
            console.warn("Audio Visualizer failed to initialize. User interaction may be required.", e);
        }
    }

    function renderVisualizer() {
        requestAnimationFrame(renderVisualizer);
        if (!analyser) return;
        analyser.getByteFrequencyData(dataArray);
        const w = canvas.getBoundingClientRect().width, h = canvas.getBoundingClientRect().height;
        const cx = w / 2, cy = h / 2, radius = 110;
        ctx.clearRect(0, 0, w, h);
        ctx.beginPath();
        for (let i = 0; i < dataArray.length; i++) {
            const value = dataArray[i];
            const percent = value / 255;
            const angle = (i / dataArray.length) * Math.PI * 2 - Math.PI / 2;
            const barHeight = 10 + (percent * 50);
            const x1 = cx + Math.cos(angle) * radius, y1 = cy + Math.sin(angle) * radius;
            const x2 = cx + Math.cos(angle) * (radius + barHeight), y2 = cy + Math.sin(angle) * (radius + barHeight);
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
        }
        ctx.lineCap = 'round';
        ctx.lineWidth = 4;
        ctx.strokeStyle = '#00ff88';
        ctx.shadowBlur = 10;
        ctx.shadowColor = '#00ff88';
        ctx.stroke();
    }

    // --- Controls & State ---
    function togglePlay() {
        initAudioVisualizer(); // Redundant call on click ensures it starts
        if (audio.src && !audio.src.includes('undefined')) {
            audio.paused ? audio.play().catch(e => console.warn("Play() failed:", e)) : audio.pause();
        }
    }
    
    // --- Audio Element Event Handlers ---
    audio.onplay = () => { playIcon.textContent = 'pause'; initAudioVisualizer(); };
    audio.onpause = () => { playIcon.textContent = 'play_arrow'; };
    audio.onended = () => sendCommand('skip');
    audio.ontimeupdate = () => {
        if (audio.duration) {
            const p = (audio.currentTime / audio.duration) * 100;
            progressFill.style.width = `${p}%`;
            currTimeEl.textContent = formatTime(audio.currentTime);
            durTimeEl.textContent = formatTime(audio.duration);
        }
        updatePositionState();
    };

    // --- Player Event Listeners ---
    playBtn.addEventListener('click', () => { togglePlay(); tg.HapticFeedback?.impactOccurred('light'); });
    nextBtn.addEventListener('click', () => { sendCommand('skip'); tg.HapticFeedback?.impactOccurred('medium'); });
    prevBtn.addEventListener('click', () => { audio.currentTime = 0; tg.HapticFeedback?.impactOccurred('light'); });
    
    progressBarContainer.addEventListener('click', (e) => {
        if (audio.duration) {
            const rect = progressBarContainer.getBoundingClientRect();
            const offsetX = e.clientX - rect.left;
            audio.currentTime = (offsetX / rect.width) * audio.duration;
        }
    });

    // --- Media Session API for Background Playback ---
    function setupMediaSession(metadata) {
        if ('mediaSession' in navigator) {
            navigator.mediaSession.metadata = new MediaMetadata({
                title: metadata.title, artist: metadata.artist, album: 'Cyber Radio',
                artwork: [{ src: 'https://via.placeholder.com/512.png?text=CR', sizes: '512x512', type: 'image/png' }]
            });
            navigator.mediaSession.setActionHandler('play', togglePlay);
            navigator.mediaSession.setActionHandler('pause', togglePlay);
            navigator.mediaSession.setActionHandler('nexttrack', () => nextBtn.click());
            navigator.mediaSession.setActionHandler('previoustrack', () => prevBtn.click());
        }
    }
    
    function updatePositionState() {
        if ('mediaSession' in navigator && 'setPositionState' in navigator.mediaSession) {
            navigator.mediaSession.setPositionState({
                duration: audio.duration || 0,
                position: audio.currentTime || 0,
            });
        }
    }

    // --- Utils & API ---
    function formatTime(s) {
        if (isNaN(s)) return "0:00";
        const m = Math.floor(s / 60); const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0'+sec : sec}`;
    }

    async function sendCommand(action) {
        if (!chatId || isCommandProcessing) return;
        isCommandProcessing = true;
        try {
            await fetch(`/api/radio/${action}`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({chat_id: chatId}) });
        } catch(e) { console.error(`Failed to send command '${action}':`, e); }
        setTimeout(() => isCommandProcessing = false, 1500);
    }

    async function syncWithBackend() {
        if (!chatId) return;
        try {
            const res = await fetch(`/api/radio/status?chat_id=${chatId}`);
            if (!res.ok) return;
            const data = await res.json();
            const session = data.sessions[chatId];
            if (session?.current) {
                if (currentTrackId !== session.current.identifier) {
                    currentTrackId = session.current.identifier;
                    titleEl.textContent = session.current.title;
                    artistEl.textContent = session.current.artist;
                    setupMediaSession(session.current);
                    audio.src = session.current.audio_url;
                    audio.load();
                    audio.play().catch(e => console.warn("Autoplay prevented."));
                }
            } else if (currentTrackId) {
                titleEl.textContent = "Radio Stopped";
                artistEl.textContent = "Select a genre in chat";
                if (!audio.paused) audio.pause();
                currentTrackId = null;
                audio.removeAttribute('src');
                if ('mediaSession' in navigator) { navigator.mediaSession.metadata = null; }
            }
        } catch(e) { console.error("Sync failed:", e); }
    }

    playIcon.textContent = 'play_arrow';
    setInterval(syncWithBackend, 2000);
    setInterval(updatePositionState, 1000);
    syncWithBackend();
});