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
    const playlistDrawer = document.getElementById('playlist-drawer');
    const playlistBtn = document.getElementById('btn-playlist');
    const canvas = document.getElementById('visualizer');
    const ctx = canvas.getContext('2d');
    const sunCore = document.querySelector('.sun-inner');
    const heartBtn = document.getElementById('btn-heart');
    const shuffleBtn = document.getElementById('btn-shuffle');
    const repeatBtn = document.getElementById('btn-repeat');

    let audioCtx, analyser, dataArray;
    let isInitialized = false;
    let currentId = null;
    let isProcessing = false;
    let animationId = null;

    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    // === CANVAS SETUP ===
    function resizeCanvas() {
        const rect = canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
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
            analyser.smoothingTimeConstant = 0.8;
            
            const bufferLength = analyser.frequencyBinCount;
            dataArray = new Uint8Array(bufferLength);

            resizeCanvas();
            window.addEventListener('resize', resizeCanvas);
            
            isInitialized = true;
            renderLoop();
        } catch(e) { 
            console.warn("AudioContext failed:", e); 
        }
    }

    // === SOLAR FLAME VISUALIZER ===
    function renderLoop() {
        animationId = requestAnimationFrame(renderLoop);
        if (!analyser) return;

        analyser.getByteFrequencyData(dataArray);
        
        const w = canvas.width;
        const h = canvas.height;
        const cx = w / 2;
        const cy = h / 2;
        const dpr = window.devicePixelRatio || 1;

        // Calculate average energy for effects
        let totalEnergy = 0;
        for (let i = 0; i < dataArray.length; i++) {
            totalEnergy += dataArray[i];
        }
        const avgEnergy = totalEnergy / dataArray.length / 255;

        // Clear canvas
        ctx.clearRect(0, 0, w, h);

        // === SUN PARAMETERS ===
        const baseRadius = 58 * dpr;
        const sunRadius = baseRadius + (avgEnergy * 8 * dpr);
        const numFlames = 48;
        const baseFlameLength = 25 * dpr;
        const maxFlameLength = 70 * dpr;

        // === OUTER CORONA GLOW ===
        const coronaGradient = ctx.createRadialGradient(cx, cy, sunRadius, cx, cy, sunRadius + maxFlameLength * 1.5);
        coronaGradient.addColorStop(0, `rgba(255, 149, 0, ${0.3 + avgEnergy * 0.3})`);
        coronaGradient.addColorStop(0.5, `rgba(255, 68, 68, ${0.1 + avgEnergy * 0.1})`);
        coronaGradient.addColorStop(1, 'rgba(255, 68, 68, 0)');
        
        ctx.beginPath();
        ctx.arc(cx, cy, sunRadius + maxFlameLength * 1.5, 0, Math.PI * 2);
        ctx.fillStyle = coronaGradient;
        ctx.fill();

        // === DRAW FLAME TONGUES ===
        const time = Date.now() / 1000;

        for (let i = 0; i < numFlames; i++) {
            const freqIndex = Math.floor((i / numFlames) * (dataArray.length / 2));
            const value = dataArray[freqIndex] / 255;
            
            const angle = (i / numFlames) * Math.PI * 2 - Math.PI / 2;
            
            // Flame animation with noise-like movement
            const flameNoise = Math.sin(time * 3 + i * 0.5) * 0.3 + 
                              Math.sin(time * 5 + i * 0.8) * 0.2;
            const flameLength = baseFlameLength + (value * maxFlameLength) + (flameNoise * 10 * dpr);
            
            // Flame width varies with intensity
            const flameWidth = (3 + value * 5) * dpr;
            
            // Starting point on sun's edge
            const startX = cx + Math.cos(angle) * sunRadius;
            const startY = cy + Math.sin(angle) * sunRadius;
            
            // End point of flame
            const endX = cx + Math.cos(angle) * (sunRadius + flameLength);
            const endY = cy + Math.sin(angle) * (sunRadius + flameLength);
            
            // Control points for bezier curve (creates wavy flames)
            const waveOffset = Math.sin(time * 4 + i) * (8 * dpr);
            const perpAngle = angle + Math.PI / 2;
            const cp1x = startX + Math.cos(angle) * (flameLength * 0.3) + Math.cos(perpAngle) * waveOffset;
            const cp1y = startY + Math.sin(angle) * (flameLength * 0.3) + Math.sin(perpAngle) * waveOffset;
            const cp2x = startX + Math.cos(angle) * (flameLength * 0.6) - Math.cos(perpAngle) * waveOffset;
            const cp2y = startY + Math.sin(angle) * (flameLength * 0.6) - Math.sin(perpAngle) * waveOffset;

            // Flame gradient
            const flameGradient = ctx.createLinearGradient(startX, startY, endX, endY);
            flameGradient.addColorStop(0, '#FFD93D');
            flameGradient.addColorStop(0.3, '#FF9500');
            flameGradient.addColorStop(0.6, '#FF6B35');
            flameGradient.addColorStop(1, 'rgba(255, 68, 68, 0)');

            ctx.beginPath();
            ctx.moveTo(startX, startY);
            ctx.bezierCurveTo(cp1x, cp1y, cp2x, cp2y, endX, endY);
            ctx.strokeStyle = flameGradient;
            ctx.lineWidth = flameWidth;
            ctx.lineCap = 'round';
            ctx.stroke();
        }

        // === INNER SUN GLOW ===
        const innerGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, sunRadius);
        innerGlow.addColorStop(0, '#FFF5CC');
        innerGlow.addColorStop(0.3, '#FFD93D');
        innerGlow.addColorStop(0.7, '#FF9500');
        innerGlow.addColorStop(1, '#FF6B35');

        ctx.beginPath();
        ctx.arc(cx, cy, sunRadius * 0.9, 0, Math.PI * 2);
        ctx.fillStyle = innerGlow;
        ctx.shadowColor = '#FF9500';
        ctx.shadowBlur = 30 * dpr;
        ctx.fill();
        ctx.shadowBlur = 0;

        // === SOLAR FLARES (random intense bursts) ===
        const numFlares = 6;
        for (let i = 0; i < numFlares; i++) {
            const flareIndex = Math.floor((i / numFlares) * dataArray.length);
            const flareIntensity = dataArray[flareIndex] / 255;
            
            if (flareIntensity > 0.7) {
                const flareAngle = (i / numFlares) * Math.PI * 2 + time * 0.5;
                const flareLength = flareIntensity * maxFlameLength * 1.5;
                
                const flareStartX = cx + Math.cos(flareAngle) * sunRadius;
                const flareStartY = cy + Math.sin(flareAngle) * sunRadius;
                const flareEndX = cx + Math.cos(flareAngle) * (sunRadius + flareLength);
                const flareEndY = cy + Math.sin(flareAngle) * (sunRadius + flareLength);

                const flareGradient = ctx.createLinearGradient(flareStartX, flareStartY, flareEndX, flareEndY);
                flareGradient.addColorStop(0, 'rgba(255, 255, 255, 0.9)');
                flareGradient.addColorStop(0.2, 'rgba(255, 217, 61, 0.7)');
                flareGradient.addColorStop(1, 'rgba(255, 107, 53, 0)');

                ctx.beginPath();
                ctx.moveTo(flareStartX, flareStartY);
                ctx.lineTo(flareEndX, flareEndY);
                ctx.strokeStyle = flareGradient;
                ctx.lineWidth = (8 + flareIntensity * 6) * dpr;
                ctx.lineCap = 'round';
                ctx.stroke();
            }
        }

        // === HOT CORE SPOTS ===
        ctx.beginPath();
        ctx.arc(cx - sunRadius * 0.25, cy - sunRadius * 0.2, sunRadius * 0.15, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
        ctx.fill();

        // Update sun core scale based on energy
        if (sunCore) {
            const scale = 1 + avgEnergy * 0.15;
            sunCore.style.transform = `scale(${scale})`;
            sunCore.style.boxShadow = `
                0 0 ${60 + avgEnergy * 40}px rgba(255, 149, 0, ${0.6 + avgEnergy * 0.3}),
                0 0 ${100 + avgEnergy * 60}px rgba(255, 107, 53, ${0.4 + avgEnergy * 0.2}),
                inset 0 0 30px rgba(255, 217, 61, 0.5)
            `;
        }
    }

    // === CONTROLS ===
    playBtn.onclick = () => {
        initAudio();
        if (audio.paused) {
            audio.play();
            playIcon.textContent = 'pause';
            document.body.classList.add('playing');
        } else {
            audio.pause();
            playIcon.textContent = 'play_arrow';
            document.body.classList.remove('playing');
        }
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    };

    nextBtn.onclick = () => {
        api('skip');
        titleEl.textContent = "Loading next...";
        artistEl.textContent = "Please wait...";
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    };

    prevBtn.onclick = () => {
        if (audio.currentTime > 3) {
            audio.currentTime = 0;
        }
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
    };

    // Extra buttons
    heartBtn.onclick = () => {
        heartBtn.classList.toggle('active');
        const icon = heartBtn.querySelector('.material-icons-round');
        icon.textContent = heartBtn.classList.contains('active') ? 'favorite' : 'favorite_border';
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    };

    shuffleBtn.onclick = () => {
        shuffleBtn.classList.toggle('active');
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    };

    repeatBtn.onclick = () => {
        repeatBtn.classList.toggle('active');
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    };

    // Playlist toggle
    window.togglePlaylist = () => {
        playlistDrawer.classList.toggle('active');
        if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    };
    playlistBtn.onclick = window.togglePlaylist;

    // Swipe to close playlist
    let touchStartY = 0;
    playlistDrawer.addEventListener('touchstart', (e) => {
        touchStartY = e.touches[0].clientY;
    });

    playlistDrawer.addEventListener('touchmove', (e) => {
        const deltaY = e.touches[0].clientY - touchStartY;
        if (deltaY > 50) {
            playlistDrawer.classList.remove('active');
        }
    });

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
        } catch (e) {
            console.error('API Error:', e);
        }
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
                if (titleEl.textContent !== s.current.title && !titleEl.textContent.includes("Loading")) {
                    titleEl.textContent = s.current.title;
                    artistEl.textContent = s.current.artist;
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
        } catch (e) {
            console.error('Sync Error:', e);
        }
    }

    // === PROGRESS & TIME ===
    audio.ontimeupdate = () => {
        if (audio.duration) {
            const p = (audio.currentTime / audio.duration) * 100;
            progressEl.style.width = `${p}%`;
            currTimeEl.textContent = fmt(audio.currentTime);
            document.getElementById('dur-time').textContent = fmt(audio.duration);
        }
    };

    audio.onended = () => {
        api('skip');
    };

    audio.onplay = () => {
        playIcon.textContent = 'pause';
        if (audioCtx && audioCtx.state === 'suspended') {
            audioCtx.resume();
        }
    };

    audio.onpause = () => {
        playIcon.textContent = 'play_arrow';
    };

    function fmt(s) {
        if (!s || !isFinite(s)) return '0:00';
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0' + sec : sec}`;
    }

    // Start sync loop
    setInterval(sync, 2000);
    sync();

    // Initial canvas render (static sun)
    resizeCanvas();
    
    // Draw static sun when no audio
    function drawStaticSun() {
        if (isInitialized) return;
        
        const w = canvas.width;
        const h = canvas.height;
        const cx = w / 2;
        const cy = h / 2;
        const dpr = window.devicePixelRatio || 1;
        const sunRadius = 58 * dpr;

        ctx.clearRect(0, 0, w, h);

        // Static glow
        const glowGradient = ctx.createRadialGradient(cx, cy, sunRadius * 0.5, cx, cy, sunRadius * 2);
        glowGradient.addColorStop(0, 'rgba(255, 217, 61, 0.3)');
        glowGradient.addColorStop(0.5, 'rgba(255, 149, 0, 0.1)');
        glowGradient.addColorStop(1, 'rgba(255, 107, 53, 0)');
        
        ctx.beginPath();
        ctx.arc(cx, cy, sunRadius * 2, 0, Math.PI * 2);
        ctx.fillStyle = glowGradient;
        ctx.fill();

        // Static rays
        const numRays = 24;
        for (let i = 0; i < numRays; i++) {
            const angle = (i / numRays) * Math.PI * 2;
            const rayLength = 20 * dpr + Math.sin(i * 2) * 10 * dpr;
            
            const startX = cx + Math.cos(angle) * sunRadius;
            const startY = cy + Math.sin(angle) * sunRadius;
            const endX = cx + Math.cos(angle) * (sunRadius + rayLength);
            const endY = cy + Math.sin(angle) * (sunRadius + rayLength);

            ctx.beginPath();
            ctx.moveTo(startX, startY);
            ctx.lineTo(endX, endY);
            ctx.strokeStyle = 'rgba(255, 149, 0, 0.5)';
            ctx.lineWidth = 3 * dpr;
            ctx.lineCap = 'round';
            ctx.stroke();
        }

        requestAnimationFrame(drawStaticSun);
    }
    
    drawStaticSun();
});