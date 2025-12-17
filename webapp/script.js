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

    // === VISUALIZER ===
    function initAudio() {
        if(isInitialized) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioCtx.createAnalyser();
            const src = audioCtx.createMediaElementSource(audio);
            src.connect(analyser);
            analyser.connect(audioCtx.destination);
            
            analyser.fftSize = 128;
            const bufferLength = analyser.frequencyBinCount;
            dataArray = new Uint8Array(bufferLength);
            
            // Resize
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            ctx.scale(dpr, dpr);
            
            isInitialized = true;
            renderLoop();
        } catch(e) { console.warn(e); }
    }

    function renderLoop() {
        requestAnimationFrame(renderLoop);
        if(!analyser) return;
        analyser.getByteFrequencyData(dataArray);
        
        const w = canvas.getBoundingClientRect().width;
        const h = canvas.getBoundingClientRect().height;
        const cx = w/2; 
        const cy = h/2;
        const radius = 95;

        ctx.clearRect(0, 0, w, h);
        
        // Draw Circle Waves
        ctx.beginPath();
        for(let i=0; i<dataArray.length; i++) {
            const val = dataArray[i];
            const angle = (i / dataArray.length) * Math.PI * 2;
            const r = radius + (val / 4);
            
            const x = cx + Math.cos(angle) * r;
            const y = cy + Math.sin(angle) * r;
            
            if(i===0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = '#00ff88';
        ctx.lineWidth = 3;
        ctx.shadowBlur = 15;
        ctx.shadowColor = '#00ff88';
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