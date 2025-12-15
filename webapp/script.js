document.addEventListener('DOMContentLoaded', () => {
    // === SETUP ===
    let audioCtx, analyser, dataArray, canvas, ctx;
    let isPlaying = false;
    let currentTrackId = null;
    let isInitialized = false;
    let isCommandProcessing = false;

    // DOM
    const audio = document.getElementById('audio-player');
    const timeDisplay = document.getElementById('time-display');
    const trackTitle = document.getElementById('track-title');
    const playlistDiv = document.getElementById('playlist');
    const tg = window.Telegram.WebApp;
    tg.expand();

    // Query Params
    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    // === WINAMP VISUALIZER ===
    function initAudio() {
        if (isInitialized) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioCtx.createAnalyser();
            const source = audioCtx.createMediaElementSource(audio);
            source.connect(analyser);
            analyser.connect(audioCtx.destination);
            
            // 32 полосы для классического вида
            analyser.fftSize = 64; 
            const bufferLength = analyser.frequencyBinCount;
            dataArray = new Uint8Array(bufferLength);
            
            canvas = document.getElementById('visualizer');
            ctx = canvas.getContext('2d');
            
            // Retina fix
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            ctx.scale(dpr, dpr);
            
            isInitialized = true;
            renderFrame();
        } catch (e) {
            console.error("Audio init failed:", e);
        }
    }

    function renderFrame() {
        requestAnimationFrame(renderFrame);
        if (!analyser) return;

        analyser.getByteFrequencyData(dataArray);
        
        const width = canvas.getBoundingClientRect().width;
        const height = canvas.getBoundingClientRect().height;
        const bars = 16; // Количество столбиков
        const barWidth = (width / bars) - 1;
        
        ctx.fillStyle = '#000';
        ctx.fillRect(0, 0, width, height);

        for (let i = 0; i < bars; i++) {
            // Масштабируем значение (0-255) в высоту
            const value = dataArray[i]; 
            const percent = value / 255;
            const barHeight = Math.floor(percent * height);
            
            const x = i * (barWidth + 1);
            
            // Рисуем "блоками" по 2px
            for (let y = 0; y < barHeight; y += 3) {
                // Winamp Colors
                let color = '#00e600'; // Green
                const relativeY = y / height;
                
                if (relativeY > 0.8) color = '#e60000'; // Red top
                else if (relativeY > 0.6) color = '#dcdc00'; // Yellow mid

                ctx.fillStyle = color;
                ctx.fillRect(x, height - y - 2, barWidth, 2);
            }
            
            // "Пик" (падающая точка) - упрощенно просто верхний блок
            if (barHeight > 0) {
                ctx.fillStyle = '#fff';
                ctx.fillRect(x, height - barHeight - 2, barWidth, 2);
            }
        }
    }

    // === CONTROLS ===
    const btn = (id, fn) => {
        document.getElementById(id).onclick = () => {
            if (tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
            fn();
        };
    };

    btn('btn-play', () => { initAudio(); audio.play(); });
    btn('btn-pause', () => audio.pause());
    btn('btn-stop', () => { 
        sendCommand('stop'); 
        audio.pause(); 
        audio.currentTime = 0; 
        timeDisplay.innerText = "00:00";
    });
    btn('btn-next', () => { 
        sendCommand('skip'); 
        trackTitle.innerText = "*** BUFFERING ***"; 
    });
    btn('btn-prev', () => audio.currentTime = 0);

    document.getElementById('volume-slider').oninput = (e) => {
        audio.volume = e.target.value / 100;
    };

    audio.ontimeupdate = () => {
        const m = Math.floor(audio.currentTime / 60);
        const s = Math.floor(audio.currentTime % 60);
        timeDisplay.innerText = `${m < 10 ? '0' : ''}${m}:${s < 10 ? '0' : ''}${s}`;
    };

    audio.onended = () => sendCommand('skip');

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
        if (!chatId) return;
        try {
            const res = await fetch(`/api/radio/status?chat_id=${chatId}`);
            const data = await res.json();
            const session = data.sessions[chatId];

            if (session && session.current) {
                const fullTitle = `${session.current.artist} - ${session.current.title}`;
                const displayTitle = `*** ${fullTitle} *** (${session.current.duration}s)`;
                
                if (trackTitle.innerText !== displayTitle && !trackTitle.innerText.includes("BUFFERING")) {
                    trackTitle.innerText = displayTitle;
                }

                // Playlist Render
                let pl = `<div class="pl-item current">1. ${fullTitle}</div>`;
                pl += `<div class="pl-item">2. [Buffering next track...]</div>`;
                pl += `<div class="pl-item">   ${session.query} Radio</div>`;
                
                if (playlistDiv.innerHTML !== pl) playlistDiv.innerHTML = pl;

                // Audio Load
                if (session.current.audio_url && currentTrackId !== session.current.identifier) {
                    currentTrackId = session.current.identifier;
                    audio.crossOrigin = "anonymous";
                    audio.src = session.current.audio_url;
                    if (isInitialized) audio.play().catch(()=>{});
                }
            } else {
                trackTitle.innerText = "WINAMP STOPPED";
            }
        } catch (e) {}
    }

    setInterval(sync, 2000);
    sync();
});