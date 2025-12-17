document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram.WebApp;
    tg.expand();

    // Elements
    const audio = document.getElementById('audio-player');
    const playBtn = document.getElementById('btn-play-pause');
    const playIcon = document.getElementById('icon-play');
    const nextBtn = document.getElementById('btn-next');
    const prevBtn = document.getElementById('btn-prev');
    const titleEl = document.getElementById('track-title');
    const artistEl = document.getElementById('track-artist');
    const progressEl = document.getElementById('progress-bar');
    const currTimeEl = document.getElementById('curr-time');
    const durTimeEl = document.getElementById('dur-time');
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

    // === CANVAS SETUP ===
    function setupCanvas() {
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        ctx.scale(dpr, dpr);
    }

    function initAudio() {
        if (isInitialized) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioCtx.createAnalyser();
            const src = audioCtx.createMediaElementSource(audio);
            src.connect(analyser);
            analyser.connect(audioCtx.destination);
            analyser.fftSize = 256;
            analyser.smoothingTimeConstant = 0.75;
            
            dataArray = new Uint8Array(analyser.frequencyBinCount);
            
            setupCanvas();
            window.addEventListener('resize', setupCanvas);
            
            isInitialized = true;
            animate();
        } catch(e) { 
            console.warn("Audio init failed:", e);
        }
    }

    // === SUN WITH FLAMES ANIMATION ===
    function animate() {
        requestAnimationFrame(animate);
        
        const w = canvas.getBoundingClientRect().width;
        const h = canvas.getBoundingClientRect().height;
        const cx = w / 2;
        const cy = h / 2;
        
        ctx.clearRect(0, 0, w, h);
        
        // Get audio data
        let avgEnergy = 0;
        if (analyser && dataArray) {
            analyser.getByteFrequencyData(dataArray);
            for (let i = 0; i < dataArray.length; i++) {
                avgEnergy += dataArray[i];
            }
            avgEnergy = avgEnergy / dataArray.length / 255;
        }
        
        const time = Date.now() / 1000;
        const sunRadius = 35 + avgEnergy * 5;
        
        // === OUTER GLOW ===
        const glowSize = sunRadius + 40 + avgEnergy * 20;
        const outerGlow = ctx.createRadialGradient(cx, cy, sunRadius, cx, cy, glowSize);
        outerGlow.addColorStop(0, `rgba(255, 149, 0, ${0.4 + avgEnergy * 0.3})`);
        outerGlow.addColorStop(0.4, `rgba(255, 80, 50, ${0.2 + avgEnergy * 0.2})`);
        outerGlow.addColorStop(1, 'rgba(255, 50, 50, 0)');
        
        ctx.beginPath();
        ctx.arc(cx, cy, glowSize, 0, Math.PI * 2);
        ctx.fillStyle = outerGlow;
        ctx.fill();
        
        // === FLAME TONGUES ===
        const numFlames = 32;
        
        for (let i = 0; i < numFlames; i++) {
            const freqIdx = Math.floor((i / numFlames) * 64);
            const freqValue = dataArray ? dataArray[freqIdx] / 255 : 0.3;
            
            const baseAngle = (i / numFlames) * Math.PI * 2;
            const wobble = Math.sin(time * 3 + i * 0.7) * 0.08;
            const angle = baseAngle + wobble;
            
            // Flame length based on frequency
            const baseLength = 15 + Math.sin(time * 2 + i) * 5;
            const flameLength = baseLength + freqValue * 35;
            
            // Flame thickness
            const flameWidth = 4 + freqValue * 6;
            
            // Start and end points
            const x1 = cx + Math.cos(angle) * sunRadius;
            const y1 = cy + Math.sin(angle) * sunRadius;
            const x2 = cx + Math.cos(angle) * (sunRadius + flameLength);
            const y2 = cy + Math.sin(angle) * (sunRadius + flameLength);
            
            // Control points for curve
            const wave = Math.sin(time * 5 + i * 1.2) * 8 * freqValue;
            const perpAngle = angle + Math.PI / 2;
            const cpx = (x1 + x2) / 2 + Math.cos(perpAngle) * wave;
            const cpy = (y1 + y2) / 2 + Math.sin(perpAngle) * wave;
            
            // Flame gradient
            const gradient = ctx.createLinearGradient(x1, y1, x2, y2);
            gradient.addColorStop(0, '#FFE066');
            gradient.addColorStop(0.3, '#FFAA33');
            gradient.addColorStop(0.6, '#FF6622');
            gradient.addColorStop(1, 'rgba(255, 50, 30, 0)');
            
            // Draw curved flame
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.quadraticCurveTo(cpx, cpy, x2, y2);
            ctx.strokeStyle = gradient;
            ctx.lineWidth = flameWidth;
            ctx.lineCap = 'round';
            ctx.stroke();
        }
        
        // === SECONDARY SMALL FLAMES ===
        const numSmallFlames = 48;
        for (let i = 0; i < numSmallFlames; i++) {
            const angle = (i / numSmallFlames) * Math.PI * 2 + time * 0.3;
            const flicker = Math.sin(time * 8 + i * 2) * 0.5 + 0.5;
            const len = 8 + flicker * 12 + avgEnergy * 10;
            
            const x1 = cx + Math.cos(angle) * sunRadius;
            const y1 = cy + Math.sin(angle) * sunRadius;
            const x2 = cx + Math.cos(angle) * (sunRadius + len);
            const y2 = cy + Math.sin(angle) * (sunRadius + len);
            
            ctx.beginPath();
            ctx.moveTo(x1, y1);
            ctx.lineTo(x2, y2);
            ctx.strokeStyle = `rgba(255, ${180 + Math.floor(flicker * 75)}, 50, ${0.3 + flicker * 0.4})`;
            ctx.lineWidth = 1.5 + flicker;
            ctx.lineCap = 'round';
            ctx.stroke();
        }
        
        // === SUN CORE ===
        const coreGradient = ctx.createRadialGradient(
            cx - sunRadius * 0.2, cy - sunRadius * 0.2, 0,
            cx, cy, sunRadius
        );
        coreGradient.addColorStop(0, '#FFFAE6');
        coreGradient.addColorStop(0.3, '#FFE066');
        coreGradient.addColorStop(0.7, '#FFAA33');
        coreGradient.addColorStop(1, '#FF8822');
        
        ctx.beginPath();
        ctx.arc(cx, cy, sunRadius, 0, Math.PI * 2);
        ctx.fillStyle = coreGradient;
        ctx.shadowColor = '#FF9500';
        ctx.shadowBlur = 20;
        ctx.fill();
        ctx.shadowBlur = 0;
        
        // === CORE HIGHLIGHT ===
        ctx.beginPath();
        ctx.arc(cx - sunRadius * 0.25, cy - sunRadius * 0.25, sunRadius * 0.25, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255, 255, 255, 0.35)';
        ctx.fill();
        
        // === SUNSPOTS (reactive) ===
        if (avgEnergy > 0.5) {
            const spotAngle = time * 2;
            const spotX = cx + Math.cos(spotAngle) * sunRadius * 0.4;
            const spotY = cy + Math.sin(spotAngle) * sunRadius * 0.4;
            ctx.beginPath();
            ctx.arc(spotX, spotY, 3 + avgEnergy * 4, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(255, 100, 50, 0.4)';
            ctx.fill();
        }
    }

    // Start static animation before audio
    setupCanvas();
    animate();

    // === CONTROLS ===
    playBtn.onclick = () => {
        initAudio();
        if (audioCtx && audioCtx.state === 'suspended') {
            audioCtx.resume();
        }
        if (audio.paused) {
            audio.play();
            playIcon.textContent = 'pause';
        } else {
            audio.pause();
            playIcon.textContent = 'play_arrow';
        }
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    };

    nextBtn.onclick = () => {
        api('skip');
        titleEl.textContent = "Loading...";
        artistEl.textContent = "Please wait";
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    };

    prevBtn.onclick = () => {
        if (audio.currentTime > 3) {
            audio.currentTime = 0;
        }
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    };

    window.togglePlaylist = () => {
        playlistDrawer.classList.toggle('active');
    };
    playlistBtn.onclick = window.togglePlaylist;

    // === API ===
    async function api(action) {
        if (!chatId || isProcessing) return;
        isProcessing = true;
        try {
            await fetch(`/api/radio/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chat_id: chatId })
            });
        } catch (e) {}
        setTimeout(() => isProcessing = false, 1000);
    }

    // === SYNC ===
    async function sync() {
        if (!chatId) return;
        try {
            const res = await fetch(`/api/radio/status?chat_id=${chatId}`);
            const data = await res.json();
            const s = data.sessions[chatId];

            if (s && s.current) {
                if (currentId !== s.current.identifier) {
                    titleEl.textContent = s.current.title || 'Unknown';
                    artistEl.textContent = s.current.artist || 'Unknown';
                }
                
                if (s.current.audio_url && currentId !== s.current.identifier) {
                    currentId = s.current.identifier;
                    audio.crossOrigin = "anonymous";
                    audio.src = s.current.audio_url;
                    if (isInitialized) {
                        audio.play().catch(() => {});
                        playIcon.textContent = 'pause';
                    }
                }
            }
        } catch (e) {}
    }

    // === PROGRESS ===
    audio.ontimeupdate = () => {
        if (audio.duration && isFinite(audio.duration)) {
            const p = (audio.currentTime / audio.duration) * 100;
            progressEl.style.width = `${p}%`;
            currTimeEl.textContent = formatTime(audio.currentTime);
            durTimeEl.textContent = formatTime(audio.duration);
        }
    };

    audio.onended = () => api('skip');

    audio.onplay = () => {
        playIcon.textContent = 'pause';
        if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
    };

    audio.onpause = () => {
        playIcon.textContent = 'play_arrow';
    };

    function formatTime(s) {
        if (!s || !isFinite(s)) return '0:00';
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0' + sec : sec}`;
    }

    // Start sync
    setInterval(sync, 2000);
    sync();
});