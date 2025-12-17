document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram.WebApp;
    tg.expand();

    // Elements
    const audio = document.getElementById('audio-player');
    const playBtn = document.getElementById('btn-play-pause');
    const playIcon = document.getElementById('icon-play');
    const nextBtn = document.getElementById('btn-next');
    const titleEl = document.getElementById('track-title');
    const artistEl = document.getElementById('track-artist');
    const progressEl = document.getElementById('progress-bar');
    const currTimeEl = document.getElementById('curr-time');
    const playlistDrawer = document.getElementById('playlist-drawer');
    const playlistBtn = document.getElementById('btn-playlist');
    const canvas = document.getElementById('visualizer');
    const ctx = canvas.getContext('2d');

    let audioCtx, analyser, dataArray;
    let isInitialized = false;
    let currentId = null;
    let isProcessing = false;

    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    // === ARCHITECTURAL VISUALIZER REFACTOR ===

    function resizeCanvas() {
        // Get the size of the canvas in CSS pixels.
        const rect = canvas.getBoundingClientRect();
        // Get the device pixel ratio.
        const dpr = window.devicePixelRatio || 1;

        // Set the canvas's internal resolution to match the screen's actual pixels.
        // This is the key to a crisp image on HiDPI/Retina screens.
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;

        // We do NOT scale the context. Instead, we'll draw using the new, high-res coordinates.
        // This avoids coordinate system confusion.
    }

    function initAudio() {
        if (isInitialized) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioCtx.createAnalyser();
            const src = audioCtx.createMediaElementSource(audio);
            src.connect(analyser);
            analyser.connect(audioCtx.destination);
            analyser.fftSize = 128;
            
            const bufferLength = analyser.frequencyBinCount;
            dataArray = new Uint8Array(bufferLength);

            // Set initial size and listen for future size changes.
            resizeCanvas();
            window.addEventListener('resize', resizeCanvas);
            
            isInitialized = true;
            renderLoop(); // Start the animation loop.
        } catch(e) { console.warn("AudioContext failed to initialize:", e); }
    }

    function renderLoop() {
        requestAnimationFrame(renderLoop);
        if (!analyser) return;

        analyser.getByteFrequencyData(dataArray);
        
        const w = canvas.width;
        const h = canvas.height;
        const cx = w / 2;
        const cy = h / 2;
        const dpr = window.devicePixelRatio || 1;

        // --- Musical Sun Properties ---
        const sunRadius = 55 * dpr;
        const maxRayLength = 60 * dpr;
        const numRays = dataArray.length / 2; // Use lower frequencies for more stable rays

        ctx.clearRect(0, 0, w, h);
        
        // 1. Draw the central sun circle with gradient
        const gradient = ctx.createRadialGradient(cx, cy, sunRadius * 0.5, cx, cy, sunRadius);
        gradient.addColorStop(0, '#FFD700');
        gradient.addColorStop(1, '#FFA500');

        ctx.beginPath();
        ctx.arc(cx, cy, sunRadius, 0, 2 * Math.PI);
        ctx.fillStyle = gradient;
        ctx.shadowColor = '#FFA500';
        ctx.shadowBlur = 25 * dpr;
        ctx.fill();
        ctx.shadowBlur = 0;

        // 2. Draw the music-reactive rays
        ctx.beginPath();
        for (let i = 0; i < numRays; i++) {
            const value = dataArray[i]; // 0-255
            const percent = value / 255;
            const angle = (i / numRays) * 2 * Math.PI - Math.PI / 2;

            const rayLength = percent * maxRayLength;
            const startX = cx + Math.cos(angle) * sunRadius;
            const startY = cy + Math.sin(angle) * sunRadius;
            const endX = cx + Math.cos(angle) * (sunRadius + rayLength);
            const endY = cy + Math.sin(angle) * (sunRadius + rayLength);

            ctx.moveTo(startX, startY);
            ctx.lineTo(endX, endY);
        }
        ctx.strokeStyle = '#FFA500';
        ctx.lineWidth = 4 * dpr;
        ctx.lineCap = 'round';
        ctx.stroke();
    }

    // === LOGIC ===
    playBtn.onclick = () => {
        initAudio();
        if(audio.paused) {
            audio.play();
            playIcon.textContent = 'pause';
        } else {
            audio.pause();
            playIcon.textContent = 'play_arrow';
        }
        if(tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    }

    nextBtn.onclick = () => {
        api('skip');
        titleEl.textContent = "Loading next...";
        if(tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    }

    window.togglePlaylist = () => playlistDrawer.classList.toggle('active');
    playlistBtn.onclick = window.togglePlaylist;

    async function api(action) {
        if(!chatId || isProcessing) return;
        isProcessing = true;
        try {
            await fetch(`/api/radio/${action}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({chat_id: chatId})
            });
        } catch(e){}
        setTimeout(()=> isProcessing = false, 1000);
    }

    // === SYNC ===
    async function sync() {
        if(!chatId) return;
        try {
            const res = await fetch(`/api/radio/status?chat_id=${chatId}`);
            const data = await res.json();
            const s = data.sessions[chatId];

            if(s && s.current) {
                if(titleEl.textContent !== s.current.title && !titleEl.textContent.includes("Loading")) {
                    titleEl.textContent = s.current.title;
                    artistEl.textContent = s.current.artist;
                }
                
                if(s.current.audio_url && currentId !== s.current.identifier) {
                    currentId = s.current.identifier;
                    audio.crossOrigin = "anonymous";
                    audio.src = s.current.audio_url;
                    if(isInitialized) audio.play().catch(()=>{});
                    playIcon.textContent = 'pause';
                }
            }
        } catch(e){}
    }

    audio.ontimeupdate = () => {
        const p = (audio.currentTime / audio.duration) * 100;
        progressEl.style.width = `${p}%`;
        currTimeEl.textContent = fmt(audio.currentTime);
    };
    audio.onended = () => api('skip');

    function fmt(s) {
        const m = Math.floor(s/60);
        const sec = Math.floor(s%60);
        return `${m}:${sec<10?'0'+sec:sec}`;
    }

    setInterval(sync, 2000);
    sync();
});