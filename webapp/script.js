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
    const progressBar = document.getElementById('progress-bar');
    const currTimeEl = document.getElementById('curr-time');
    const durTimeEl = document.getElementById('dur-time');
    const canvas = document.getElementById('visualizer');
    const ctx = canvas.getContext('2d');

    // State
    let audioCtx, analyser, dataArray, isVisualizerInitialized = false;
    let currentTrackId = null, isCommandProcessing = false;

    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    function initAudioVisualizer() {
        if (isVisualizerInitialized) return;
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
        } catch(e) { console.warn("Audio Visualizer failed to initialize:", e); }
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

    function togglePlay() {
        if (audio.src && !audio.src.includes('undefined')) {
            initAudioVisualizer();
            audio.paused ? audio.play().catch(e => console.warn("Play() failed:", e)) : audio.pause();
        }
    }
    
    audio.onplay = () => { playIcon.textContent = 'pause'; initAudioVisualizer(); };
    audio.onpause = () => { playIcon.textContent = 'play_arrow'; };
    audio.onended = () => sendCommand('skip');
    audio.onloadedmetadata = () => {
        progressBar.max = audio.duration;
        durTimeEl.textContent = formatTime(audio.duration);
    };

    audio.ontimeupdate = () => {
        progressBar.value = audio.currentTime;
        currTimeEl.textContent = formatTime(audio.currentTime);
        // Style the progress bar fill
        const percentage = (audio.currentTime / audio.duration) * 100;
        progressBar.style.background = `linear-gradient(to right, var(--primary) ${percentage}%, var(--glass-bg) ${percentage}%)`;
    };

    // --- Event Listeners ---
    playBtn.addEventListener('click', () => { togglePlay(); tg.HapticFeedback?.impactOccurred('light'); });
    nextBtn.addEventListener('click', () => { sendCommand('skip'); titleEl.textContent = "Loading next..."; artistEl.textContent = "Please wait..."; tg.HapticFeedback?.impactOccurred('medium'); });
    prevBtn.addEventListener('click', () => { audio.currentTime = 0; tg.HapticFeedback?.impactOccurred('light'); });
    
    progressBar.addEventListener('input', () => {
        audio.currentTime = progressBar.value;
    });

    function formatTime(s) {
        if (isNaN(s)) return "0:00";
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0'+sec : sec}`;
    }

    async function sendCommand(action) {
        if (!chatId || isCommandProcessing) return;
        isCommandProcessing = true;
        try {
            await fetch(`/api/radio/${action}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({chat_id: chatId})
            });
        } catch(e) { console.error(`Failed to send command '${action}':`, e); }
        setTimeout(() => isCommandProcessing = false, 1000);
    }
    
    async function syncWithBackend() {
        if (!chatId) return;
        try {
            const res = await fetch(`/api/radio/status?chat_id=${chatId}`);
            if (!res.ok) return;
            const data = await res.json();
            const session = data.sessions[chatId];
            if (session?.current) {
                if (titleEl.textContent !== session.current.title) {
                    titleEl.textContent = session.current.title;
                    artistEl.textContent = session.current.artist;
                }
                if (session.current.identifier && currentTrackId !== session.current.identifier) {
                    currentTrackId = session.current.identifier;
                    audio.src = session.current.audio_url;
                    audio.load();
                    audio.play().catch(e => console.warn("Autoplay was prevented."));
                }
            } else {
                titleEl.textContent = "Radio Stopped";
                artistEl.textContent = "Select a genre in chat";
                if (!audio.paused) audio.pause();
                currentTrackId = null;
                audio.removeAttribute('src');
            }
        } catch(e) { console.error("Sync failed:", e); }
    }

    playIcon.textContent = 'play_arrow';
    setInterval(syncWithBackend, 2000);
    syncWithBackend();
});