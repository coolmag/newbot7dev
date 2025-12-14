console.log("script.js loaded and running");

document.addEventListener('DOMContentLoaded', () => {
    console.log("DOM fully loaded and parsed");

    // ===== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ =====
    let currentTrack = null;
    let isPlaying = false;
    let isUpdating = false;
    let chatId = null;

    // ===== DOM ЭЛЕМЕНТЫ =====
    const audioPlayer = document.getElementById('audio-player');
    const btnPlay = document.getElementById('btn-play');
    const btnStop = document.getElementById('btn-stop');
    const btnPrev = document.getElementById('btn-prev');
    const btnNext = document.getElementById('btn-next');
    const btnShuffle = document.getElementById('btn-shuffle');
    const btnRepeat = document.getElementById('btn-repeat');
    const playIcon = document.getElementById('play-icon');
    const volumeSlider = document.getElementById('volume-slider');
    const volumeValue = document.getElementById('volume-value');
    const trackTitle = document.getElementById('track-title');
    const trackArtist = document.getElementById('track-artist');
    const statusIcon = document.getElementById('status-icon');
    const statusText = document.getElementById('status-text');
    const genreText = document.getElementById('genre-text');
    const genreIcon = document.querySelector('.genre-icon');
    const currentTimeEl = document.getElementById('current-time');
    const totalTimeEl = document.getElementById('total-time');
    const progressBar = document.getElementById('progress-bar');
    const progressHead = document.getElementById('progress-head');
    const progressContainer = document.getElementById('progress-container');
    const queryText = document.getElementById('query-text');
    const queueCount = document.getElementById('queue-count');
    const visualizer = document.getElementById('visualizer');
    const leftReel = document.getElementById('left-reel');
    const rightReel = document.getElementById('right-reel');

    // ===== МАППИНГ ЖАНРОВ =====
    const genreMapping = {
        'rock': { icon: '🎸', name: 'ROCK' },
        'pop': { icon: '🎤', name: 'POP' },
        'jazz': { icon: '🎷', name: 'JAZZ' },
        'classical': { icon: '🎻', name: 'CLASSICAL' },
        'electronic': { icon: '🎹', name: 'ELECTRONIC' },
        'hip-hop': { icon: '🎧', name: 'HIP-HOP' },
        'rap': { icon: '🎤', name: 'RAP' },
        'metal': { icon: '🤘', name: 'METAL' },
        'blues': { icon: '🎺', name: 'BLUES' },
        'country': { icon: '🤠', name: 'COUNTRY' },
        'reggae': { icon: '🌴', name: 'REGGAE' },
        'soul': { icon: '💜', name: 'SOUL' },
        'funk': { icon: '🕺', name: 'FUNK' },
        'disco': { icon: '🪩', name: 'DISCO' },
        'punk': { icon: '⚡', name: 'PUNK' },
        'indie': { icon: '🎵', name: 'INDIE' },
        'alternative': { icon: '🔊', name: 'ALT' },
        'default': { icon: '📻', name: 'RADIO' }
    };

    // ===== УТИЛИТЫ =====
    function formatTime(seconds) {
        if (!seconds || isNaN(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    function detectGenre(query) {
        if (!query) return genreMapping['default'];
        const q = query.toLowerCase();
        for (const [key, value] of Object.entries(genreMapping)) {
            if (q.includes(key)) return value;
        }
        return genreMapping['default'];
    }

    function truncateText(text, maxLength = 40) {
        if (!text) return '---';
        return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
    }

    // ===== ОБНОВЛЕНИЕ UI =====
    function updateUI() {
        if (!btnPlay) return; // Защита, если DOM еще не готов
        playIcon.textContent = isPlaying ? '⏸' : '▶';
        btnPlay.querySelector('.btn-label').textContent = isPlaying ? 'PAUSE' : 'PLAY';
        if (isPlaying) {
            visualizer.classList.add('playing');
            leftReel.classList.add('spinning');
            rightReel.classList.add('spinning');
            statusIcon.textContent = '▶️';
            statusText.textContent = 'NOW PLAYING';
        } else {
            visualizer.classList.remove('playing');
            leftReel.classList.remove('spinning');
            rightReel.classList.remove('spinning');
            statusIcon.textContent = '⏸️';
            statusText.textContent = 'PAUSED';
        }
    }

    function updateTrackInfo(session) {
        if (!session || !session.current) {
            trackTitle.innerHTML = '<span>Ожидание трека...</span>';
            trackTitle.classList.remove('scrolling');
            trackArtist.textContent = '---';
            queryText.textContent = '---';
            queueCount.textContent = '0';
            totalTimeEl.textContent = '0:00';
            currentTimeEl.textContent = '0:00';
            progressBar.style.width = '0%';
            progressHead.style.left = '0%';
            const genre = detectGenre(session ? session.query : '');
            genreIcon.textContent = genre.icon;
            genreText.textContent = genre.name;
            return;
        }

        const title = session.current.title || 'Загрузка...';
        const artist = session.current.artist || 'Неизвестен';
        trackTitle.innerHTML = `<span>${truncateText(title)}</span>`;
        if (title.length > 25) {
            trackTitle.classList.add('scrolling');
        } else {
            trackTitle.classList.remove('scrolling');
        }
        trackArtist.textContent = artist;
        const genre = detectGenre(session.query);
        genreIcon.textContent = genre.icon;
        genreText.textContent = genre.name;
        queryText.textContent = truncateText(session.query, 15);
        queueCount.textContent = session.playlist_len || 0;
        if (session.last_error) {
            statusIcon.textContent = '⚠️';
            statusText.textContent = 'ERROR';
        } else {
            statusIcon.textContent = '📻';
            statusText.textContent = 'RADIO MODE';
        }
    }

    // ===== ОБРАБОТЧИКИ СОБЫТИЙ =====
    audioPlayer.addEventListener('timeupdate', () => {
        if (audioPlayer.duration) {
            const progress = (audioPlayer.currentTime / audioPlayer.duration) * 100;
            progressBar.style.width = `${progress}%`;
            progressHead.style.left = `${progress}%`;
            currentTimeEl.textContent = formatTime(audioPlayer.currentTime);
        }
    });

    audioPlayer.addEventListener('durationchange', () => {
        totalTimeEl.textContent = formatTime(audioPlayer.duration);
    });

    progressContainer.addEventListener('click', (e) => {
        if (audioPlayer.duration) {
            const rect = progressContainer.getBoundingClientRect();
            const clickX = e.clientX - rect.left;
            audioPlayer.currentTime = (clickX / rect.width) * audioPlayer.duration;
        }
    });

    btnPlay.addEventListener('click', async () => {
        console.log('Play button clicked'); // Логирование клика
        userGestureMade = true; // Пользователь нажал кнопку
        if (audioPlayer.paused && audioPlayer.src) {
            try {
                await audioPlayer.play();
            } catch (error) {
                console.warn('Play failed:', error);
            }
        } else {
            audioPlayer.pause();
        }
    });

    btnStop.addEventListener('click', async () => {
        console.log('Stop button clicked'); // Логирование клика
        if (!chatId) return;
        try {
            await fetch('/api/radio/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chat_id: chatId })
            });
            audioPlayer.pause(); // Мгновенная пауза на фронте
            audioPlayer.src = ''; // Очистка источника
        } catch (e) {
            console.error('Stop error:', e);
        }
    });

    btnNext.addEventListener('click', async () => {
        console.log('Next button clicked'); // Логирование клика
        if (!chatId) return;
        try {
            await fetch('/api/radio/skip', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ chat_id: chatId })
            });
        } catch (e) {
            console.error('Skip error:', e);
        }
    });

    btnPrev.addEventListener('click', () => {
        audioPlayer.currentTime = 0;
    });

    btnShuffle.addEventListener('click', () => { btnShuffle.classList.toggle('active'); });
    btnRepeat.addEventListener('click', () => {
        btnRepeat.classList.toggle('active');
        audioPlayer.loop = btnRepeat.classList.contains('active');
    });

    volumeSlider.addEventListener('input', (e) => {
        const value = e.target.value;
        audioPlayer.volume = value / 100;
        volumeValue.textContent = value;
    });

    audioPlayer.addEventListener('play', () => { isPlaying = true; updateUI(); });
    audioPlayer.addEventListener('pause', () => { isPlaying = false; updateUI(); });
    audioPlayer.addEventListener('ended', async () => {
        if (!audioPlayer.loop && chatId) {
            try {
                await fetch('/api/radio/skip', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ chat_id: chatId })
                });
            } catch (e) {
                console.error('Auto-skip error:', e);
            }
        }
    });

    // ===== СЕТЕВЫЕ ЗАПРОСЫ =====
    async function tick() {
        console.log("Tick function called");
        if (isUpdating || !chatId) return;
        isUpdating = true;
        try {
            const response = await fetch(`/api/radio/status?chat_id=${chatId}`);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            const session = data.sessions ? data.sessions[chatId] : null;

            if (session && session._debug_info) {
                console.log("Debug Info:", session._debug_info);
            }
            updateTrackInfo(session);

            if (session && session.current && session.current.audio_url) {
                if (audioPlayer.src !== session.current.audio_url) {
                    console.log("New track detected. Updating src:", session.current.audio_url);
                    audioPlayer.src = session.current.audio_url;
                    audioPlayer.load();
                    try {
                        await audioPlayer.play();
                    } catch (error) {
                        console.warn('Autoplay was prevented. User must interact with the page first.');
                    }
                }
            } else if (!session && audioPlayer.src) {
                audioPlayer.pause();
                audioPlayer.src = '';
            }
        } catch (error) {
            console.error('Status fetch error:', error);
            statusIcon.textContent = '❌';
            statusText.textContent = 'CONNECTION ERROR';
        } finally {
            isUpdating = false;
        }
    }

    // ===== ИНИЦИАЛИЗАЦИЯ =====
    function initialize() {
        const urlParams = new URLSearchParams(window.location.search);
        chatId = urlParams.get('chat_id');
        console.log("Initialized with chatId:", chatId);

        audioPlayer.volume = volumeSlider.value / 100;
        volumeValue.textContent = volumeSlider.value;

        if (window.Telegram && window.Telegram.WebApp) {
            const tg = window.Telegram.WebApp;
            tg.ready();
            tg.expand();
            document.body.style.setProperty('--tg-theme-bg-color', tg.themeParams.bg_color || '#1a1a2e');
        }

        updateUI();
        tick();
        setInterval(tick, 5000);

        const bars = visualizer.querySelectorAll('.bar');
        bars.forEach((bar, index) => {
            bar.style.height = `${Math.random() * 20 + 5}px`;
        });
    }

    initialize();
});