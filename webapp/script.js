document.addEventListener('DOMContentLoaded', () => {
    // ===== CONFIG & STATE =====
    let audioCtx, analyser, dataArray, canvas, canvasCtx;
    let isPlaying = false;
    let chatId = null;
    let updateInterval;
    let hasInteracted = false; // Для автоплея

    // DOM Elements
    const audioPlayer = document.getElementById('audio-player');
    const playBtn = document.getElementById('btn-play');
    const prevBtn = document.getElementById('btn-prev');
    const nextBtn = document.getElementById('btn-next');
    const stopBtn = document.getElementById('btn-stop');
    const trackTitle = document.getElementById('track-title');
    const trackArtist = document.getElementById('track-artist');
    const currentTimeEl = document.getElementById('current-time');
    const totalTimeEl = document.getElementById('total-time');
    const progressBar = document.getElementById('progress-fill');
    const progressContainer = document.getElementById('progress-container');
    const statusText = document.getElementById('status-text');
    const reels = document.querySelectorAll('.reel');
    
    // Telegram WebApp Init
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
    
    // ===== HAPTIC FEEDBACK HELPER =====
    function haptic(style = 'light') {
        // Проверяем, поддерживает ли текущая версия Телеграма вибрацию
        if (tg.HapticFeedback && tg.isVersionAtLeast('6.1')) {
            tg.HapticFeedback.impactOccurred(style);
        }
    }

    // ===== AUDIO VISUALIZER (THE COOL PART) =====
    function initAudioContext() {
        if (audioCtx) return;
        
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            audioCtx = new AudioContext();
            analyser = audioCtx.createAnalyser();
            
            // Connect DOM audio element to analyser
            const source = audioCtx.createMediaElementSource(audioPlayer);
            source.connect(analyser);
            analyser.connect(audioCtx.destination);
            
            analyser.fftSize = 64; // Количество столбиков (меньше = шире)
            const bufferLength = analyser.frequencyBinCount;
            dataArray = new Uint8Array(bufferLength);
            
            canvas = document.getElementById('visualizer-canvas');
            canvasCtx = canvas.getContext('2d');
            
            drawVisualizer();
        } catch (e) {
            console.warn("Visualizer init failed (likely CORS or browser policy):", e);
        }
    }

    function drawVisualizer() {
        if (!isPlaying) {
             // Рисуем плоскую линию если пауза
             canvasCtx.clearRect(0, 0, canvas.width, canvas.height);
             canvasCtx.fillStyle = 'rgba(51, 255, 51, 0.1)';
             canvasCtx.fillRect(0, canvas.height/2, canvas.width, 1);
             requestAnimationFrame(drawVisualizer);
             return;
        }

        requestAnimationFrame(drawVisualizer);
        analyser.getByteFrequencyData(dataArray);

        canvasCtx.clearRect(0, 0, canvas.width, canvas.height);

        const barWidth = (canvas.width / dataArray.length) * 2.5;
        let barHeight;
        let x = 0;

        for (let i = 0; i < dataArray.length; i++) {
            barHeight = dataArray[i] / 2; // Масштабирование высоты

            // Цвет столбиков (Градиент от зеленого к ярко-зеленому)
            const g = barHeight + (25 * (i / dataArray.length));
            canvasCtx.fillStyle = `rgb(0, ${g + 100}, 0)`;
            
            // Эффект "зеркала" (сверху и снизу)
            canvasCtx.fillRect(x, canvas.height / 2 - barHeight / 2, barWidth, barHeight);

            x += barWidth + 1;
        }
    }

    // ===== PLAYER LOGIC =====
    
    // 1. Play/Pause
    playBtn.addEventListener('click', () => {
        haptic('medium');
        if (!audioCtx) initAudioContext();
        
        if (audioPlayer.paused) {
            audioPlayer.play().then(() => {
                setPlayingState(true);
            }).catch(e => console.error("Play error:", e));
        } else {
            audioPlayer.pause();
            setPlayingState(false);
        }
        hasInteracted = true;
    });

    function setPlayingState(playing) {
        isPlaying = playing;
        if (playing) {
            playBtn.classList.add('playing');
            playBtn.innerHTML = '<i class="icon">⏸</i>';
            statusText.textContent = 'PLAYING >>';
            reels.forEach(r => r.classList.add('active'));
        } else {
            playBtn.classList.remove('playing');
            playBtn.innerHTML = '<i class="icon">▶</i>';
            statusText.textContent = 'PAUSED ||';
            reels.forEach(r => r.classList.remove('active'));
        }
    }

    // 2. Next/Skip (Backend Call)
    nextBtn.addEventListener('click', async () => {
        haptic('heavy');
        await sendCommand('skip');
        // Сброс UI пока грузится
        statusText.textContent = 'SEEKING...';
    });
    
    // 3. Stop
    stopBtn.addEventListener('click', async () => {
        haptic('heavy');
        await sendCommand('stop');
        audioPlayer.pause();
        audioPlayer.currentTime = 0;
        setPlayingState(false);
    });
    
    // 4. Prev (Restart track)
    prevBtn.addEventListener('click', () => {
        haptic('light');
        audioPlayer.currentTime = 0;
    });

    // 5. Volume
    document.getElementById('volume-slider').addEventListener('input', (e) => {
        audioPlayer.volume = e.target.value / 100;
    });

    // 6. Progress Bar Click
    progressContainer.addEventListener('click', (e) => {
        haptic('light');
        const width = progressContainer.clientWidth;
        const clickX = e.offsetX;
        const duration = audioPlayer.duration;
        audioPlayer.currentTime = (clickX / width) * duration;
    });

    // 7. Time Update
    audioPlayer.addEventListener('timeupdate', () => {
        if (!isNaN(audioPlayer.duration)) {
            const percent = (audioPlayer.currentTime / audioPlayer.duration) * 100;
            progressBar.style.width = `${percent}%`;
            currentTimeEl.textContent = formatTime(audioPlayer.currentTime);
            totalTimeEl.textContent = formatTime(audioPlayer.duration);
        }
    });

    // 8. Auto-Next on End (Crucial for queue!)
    audioPlayer.addEventListener('ended', () => {
        console.log("Track ended. Requesting skip...");
        sendCommand('skip');
    });

    // ===== BACKEND SYNC =====
    async function sendCommand(action) {
        if (!chatId) return;
        try {
            await fetch(`/api/radio/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chat_id: chatId })
            });
        } catch (e) {
            console.error(e);
        }
    }

    async function syncState() {
        if (!chatId) return;
        try {
            const res = await fetch(`/api/radio/status?chat_id=${chatId}`);
            const data = await res.json();
            const session = data.sessions ? data.sessions[chatId] : null;

            if (session && session.current) {
                // Update Metadata
                const title = session.current.title;
                if (trackTitle.innerText !== title) {
                     trackTitle.innerText = "DATA UPLINK..."; // Показываем загрузку перед названием
                     trackTitle.classList.remove('animate'); // Убрать анимацию, пока идет загрузка
                     trackArtist.innerText = session.current.artist || "Unknown Artist"; // Обновляем артиста сразу
                     
                     setTimeout(() => {
                         trackTitle.innerText = title;
                         trackTitle.classList.add('animate');
                     }, 500); // Небольшая задержка для эффекта
                     
                     // New Track Source
                     // Важно: crossOrigin="anonymous" нужен для Canvas Visualizer!
                     if (audioPlayer.src !== session.current.audio_url) {
                         audioPlayer.crossOrigin = "anonymous"; 
                         audioPlayer.src = session.current.audio_url;
                         if (hasInteracted) {
                             audioPlayer.play().catch(console.warn);
                             setPlayingState(true);
                         }
                     }
                }
            }
        } catch (e) {
            console.error("Sync error:", e);
        }
    }

    // ===== UTILS =====
    function formatTime(s) {
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0' : ''}${sec}`;
    }

    // ===== INIT =====
    const urlParams = new URLSearchParams(window.location.search);
    chatId = urlParams.get('chat_id');
    
    // Start Polling
    setInterval(syncState, 3000); // Check server every 3s
    syncState(); // Initial check
});