document.addEventListener('DOMContentLoaded', () => {
    // === CONFIG ===
    let audioCtx, analyser, dataArray, canvas, canvasCtx;
    let isPlaying = false;
    let currentTrackId = null;
    let isInitialized = false;
    let isCommandProcessing = false; // Защита от спама кнопками

    // DOM Elements
    const audioPlayer = document.getElementById('audio-player');
    const playBtn = document.getElementById('btn-play');
    const pauseBtn = document.getElementById('btn-pause');
    const stopBtn = document.getElementById('btn-stop');
    const prevBtn = document.getElementById('btn-prev');
    const nextBtn = document.getElementById('btn-next');
    const timeDisplay = document.getElementById('time-display');
    const trackTitle = document.getElementById('track-title');
    const playlistDiv = document.getElementById('playlist');
    const volumeSlider = document.getElementById('volume-slider');
    
    // Telegram WebApp
    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();
    
    // Получаем chat_id
    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    // === ВИЗУАЛИЗАТОР WINAMP ===
    function initAudioContext() {
        if (isInitialized) return;
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            audioCtx = new AudioContext();
            analyser = audioCtx.createAnalyser();
            
            const source = audioCtx.createMediaElementSource(audioPlayer);
            source.connect(analyser);
            analyser.connect(audioCtx.destination);
            
            // FFT Size 64 дает "блочный" вид как в старом Winamp
            analyser.fftSize = 64; 
            const bufferLength = analyser.frequencyBinCount;
            dataArray = new Uint8Array(bufferLength);
            
            canvas = document.getElementById('visualizer');
            canvasCtx = canvas.getContext('2d');
            
            // Фикс для Retina экранов
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            canvasCtx.scale(dpr, dpr);
            
            isInitialized = true;
            drawVisualizer();
        } catch (e) {
            console.warn("Visualizer init warning:", e);
        }
    }

    function drawVisualizer() {
        requestAnimationFrame(drawVisualizer);
        if (!analyser) return;

        analyser.getByteFrequencyData(dataArray);
        
        // Очистка (черный фон)
        canvasCtx.fillStyle = '#000';
        canvasCtx.clearRect(0, 0, canvas.width, canvas.height);

        // Параметры отрисовки
        const bufferLength = analyser.frequencyBinCount;
        const width = canvas.getBoundingClientRect().width;
        const height = canvas.getBoundingClientRect().height;
        const barWidth = (width / bufferLength) * 1.5;
        
        let x = 0;

        for (let i = 0; i < bufferLength; i++) {
            let barHeight = (dataArray[i] / 255) * height;

            // Цвета Winamp: Зеленый -> Желтый -> Красный
            // Рисуем не сплошной линией, а "блоками" (по 2px)
            for(let y = 0; y < barHeight; y+=3) {
                let r = 0;
                let g = 255;
                let b = 0;

                // Если высоко - делаем красным/желтым
                if (y > height * 0.7) { r = 255; g = 0; }
                else if (y > height * 0.5) { r = 255; g = 255; }

                canvasCtx.fillStyle = `rgb(${r},${g},${b})`;
                canvasCtx.fillRect(x, height - y, barWidth - 1, 2);
            }
            x += barWidth;
        }
    }

    // === УПРАВЛЕНИЕ ===
    playBtn.onclick = () => {
        initAudioContext();
        audioPlayer.play();
        if(tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    };

    pauseBtn.onclick = () => {
        audioPlayer.pause();
        if(tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
    };

    stopBtn.onclick = () => {
        sendCommand('stop');
        audioPlayer.pause();
        audioPlayer.currentTime = 0;
        timeDisplay.innerText 