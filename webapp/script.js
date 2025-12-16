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
    const progressFill = document.getElementById('progress-fill');
    const currTimeEl = document.getElementById('curr-time');
    const durTimeEl = document.getElementById('dur-time');
    const playlistBtn = document.getElementById('btn-playlist');
    const drawer = document.getElementById('playlist-drawer');
    const canvas = document.getElementById('visualizer');
    const ctx = canvas.getContext('2d');

    // State
    let audioCtx, analyser, dataArray;
    let isInitialized = false;
    let currentTrackId = null;
    let isCommandProcessing = false;

    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    // --- Audio Visualizer ---
    function initAudioVisualizer() {
        if (isInitialized) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioCtx.createAnalyser();
            const source = audioCtx.createMediaElementSource(audio);
            source.connect(analyser);
            analyser.connect(audioCtx.destination);
            
            analyser.fftSize = 128; 
            const bufferLength = analyser.frequencyBinCount;
            dataArray = new Uint8Array(bufferLength);
            
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            ctx.scale(dpr, dpr);
            
            isInitialized = true;
            renderVisualizer();
        } catch(e) { console.warn("Audio Visualizer failed to initialize:", e); }
    }

    function renderVisualizer() {
        requestAnimationFrame(renderVisualizer);
        if (!analyser) return;

        analyser.getByteFrequencyData(dataArray);
        const w = canvas.getBoundingClientRect().width;
        const h = canvas.getBoundingClientRect().height;
        const cx = w / 2;
        const cy = h / 2;
        const radius = 110;

        ctx.clearRect(0, 0, w, h);
        ctx.beginPath();
        for (let i = 0; i < dataArray.length; i++) {
            const value = dataArray[i];
            const percent = value / 255;
            const angle = (i / dataArray.length) * Math.PI * 2 - Math.PI / 2;
            const barHeight = 10 + (percent * 50);
            
            const x1 = cx + Math.cos(angle) * radius;
            const y1 = cy + Math.sin(angle) * radius;
            const x2 = cx + Math.cos(angle) * (radius + barHeight);
            const y2 = cy + Math.sin(angle) * (radius + barHeight);

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

    // --- Controls & State Management (The Core Fix) ---
    function togglePlay() {
        initAudioVisualizer();
        if (audio.src && !audio.src.includes('undefined')) {
            if (audio.paused) {
                audio.play().catch(e => console.warn("Play() failed:", e));
            } else {
                audio.pause();
            }
        }
    }
    
    // UI updates are now driven by the audio element itself - this is the source of truth.
    audio.onplay = () => {
        playIcon.textContent = 'pause';
    };

    audio.onpause = () => {
        playIcon.textContent = 'play_arrow';
    };

    audio.onended = () => {
        // When one track ends, immediately request the next one.
        sendCommand('skip');
    };

    audio.ontimeupdate = () => {
        const p = (audio.currentTime / audio.duration) * 100;
        progressFill.style.width = `${p}%`;
        currTimeEl.textContent = formatTime(audio.currentTime);
        durTimeEl.textContent = formatTime(audio.duration || 0);
    };

    playBtn.addEventListener('click', () => {
        togglePlay();
        if(tg.HapticFeedback.impactOccurred) tg.HapticFeedback.impactOccurred('light');
    });
    
    nextBtn.addEventListener('click', () => {
        sendCommand('skip');
        titleEl.textContent = "Loading next...";
        artistEl.textContent = "Please wait...";
        if(tg.HapticFeedback.impactOccurred) tg.HapticFeedback.impactOccurred('medium');
    });

    prevBtn.addEventListener('click', () => {
        audio.currentTime = 0;
        if(tg.HapticFeedback.impactOccurred) tg.HapticFeedback.impactOccurred('light');
    });

    // --- Utils ---
    function formatTime(s) {
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0'+sec : sec}`;
    }

    // --- API Communication ---
    async function sendCommand(action) {
        if (!chatId || isCommandProcessing) return;
        isCommandProcessing = true;
        try {
            await fetch(`/api/radio/${action}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({chat_id: chatId})
            });
        } catch(e) {
            console.error(`Failed to send command '${action}':`, e);
        }
        // Give the backend time to process before allowing another command
        setTimeout(() => isCommandProcessing = false, 1000);
    }

    async function syncWithBackend() {
        if (!chatId) return;
        try {
            const res = await fetch(`/api/radio/status?chat_id=${chatId}`);
            if (!res.ok) return; // Don't process bad responses

            const data = await res.json();
            const session = data.sessions[chatId];

            if (session && session.current) {
                // Update text only if it has changed
                if (titleEl.textContent !== session.current.title) {
                    titleEl.textContent = session.current.title;
                    artistEl.textContent = session.current.artist;
                }

                // Update audio source only if track ID has changed
                if (session.current.identifier && currentTrackId !== session.current.identifier) {
                    currentTrackId = session.current.identifier;
                    audio.src = session.current.audio_url;
                    audio.load(); // Explicitly load the new source
                    
                    // Attempt to play the new track.
                    audio.play().catch(e => {
                        // This is expected if autoplay is blocked by the browser.
                        // The UI will correctly show the 'play' icon because the 'onpause' event will fire.
                        console.warn("Autoplay was prevented by the browser.");
                    });
                }
            } else {
                 // No session or no current track, reset UI
                titleEl.textContent = "Radio Stopped";
                artistEl.textContent = "Select a genre in chat";
                if (!audio.paused) audio.pause();
                currentTrackId = null;
                audio.removeAttribute('src');
            }
        } catch(e) {
            console.error("Sync failed:", e);
        }
    }

    // Initial state setup
    playIcon.textContent = 'play_arrow';
    setInterval(syncWithBackend, 2000);
    syncWithBackend();
});