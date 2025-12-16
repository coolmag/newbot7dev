document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram.WebApp;
    tg.expand();

    // DOM
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
    let isPlaying = false;
    let isInitialized = false;
    let currentId = null;
    let isCommandProcessing = false;

    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    // === CIRCULAR VISUALIZER ===
    function initAudio() {
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
            
            // Resize canvas
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            ctx.scale(dpr, dpr);
            
            isInitialized = true;
            render();
        } catch(e) { console.warn(e); }
    }

    function render() {
        requestAnimationFrame(render);
        if(!analyser) return;

        analyser.getByteFrequencyData(dataArray);
        const w = canvas.getBoundingClientRect().width;
        const h = canvas.getBoundingClientRect().height;
        const cx = w / 2;
        const cy = h / 2;
        const radius = 110; // Радиус вокруг обложки

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

    // === CONTROLS ===
    function togglePlay() {
        initAudio();
        if (audio.paused) {
            audio.play();
            playIcon.textContent = 'pause';
            if(tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
        } else {
            audio.pause();
            playIcon.textContent = 'play_arrow';
            if(tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
        }
    }

    playBtn.onclick = togglePlay;
    
    nextBtn.onclick = () => {
        sendCommand('skip');
        titleEl.textContent = "Loading next...";
        if(tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    };

    prevBtn.onclick = () => {
        audio.currentTime = 0;
        if(tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    };

    // Playlist Drawer
    window.togglePlaylist = () => drawer.classList.toggle('open');
    playlistBtn.onclick = window.togglePlaylist;

    // Time Update
    audio.ontimeupdate = () => {
        const p = (audio.currentTime / audio.duration) * 100;
        progressFill.style.width = `${p}%`;
        
        currTimeEl.textContent = formatTime(audio.currentTime);
        durTimeEl.textContent = formatTime(audio.duration || 0);
    };

    audio.onended = () => sendCommand('skip');

    function formatTime(s) {
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0'+sec : sec}`;
    }

    // === SYNC ===
    async function sendCommand(action) {
        if (!chatId || isCommandProcessing) return;
        isCommandProcessing = true;
        try {
            await fetch(`/api/radio/${action}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({chat_id: chatId})
            });
        } catch(e) {}
        setTimeout(() => isCommandProcessing = false, 1000);
    }

    async function sync() {
        if(!chatId) return;
        try {
            const res = await fetch(`/api/radio/status?chat_id=${chatId}`);
            const data = await res.json();
            const s = data.sessions[chatId];

            if (s && s.current) {
                if (titleEl.textContent !== s.current.title && !titleEl.textContent.includes("Loading")) {
                    titleEl.textContent = s.current.title;
                    artistEl.textContent = s.current.artist;
                }

                if (s.current.audio_url && currentId !== s.current.identifier) {
                    currentId = s.current.identifier;
                    audio.crossOrigin = "anonymous";
                    audio.src = s.current.audio_url;
                    if(isInitialized) audio.play().catch(()=>{});
                    
                    // Reset UI
                    playIcon.textContent = 'pause';
                }
            }
        } catch(e) {}
    }

    setInterval(sync, 2000);
    sync();
});