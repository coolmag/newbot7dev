console.log("script.js loaded and running");

let currentTrack = null;
let isPlaying = false;
let isUpdating = false;

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

function truncateText(text, maxLength = 30) {
  if (!text) return '---';
  return text.length > maxLength ? text.substring(0, maxLength) + '...' : text;
}

// ===== ОБНОВЛЕНИЕ UI =====
function updateUI() {
  // Кнопка Play/Pause
  playIcon.textContent = isPlaying ? '⏸' : '▶';
  btnPlay.querySelector('.btn-label').textContent = isPlaying ? 'PAUSE' : 'PLAY';
  
  // Визуализатор
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

    trackTitle.innerHTML = `<span>${truncateText(title, 40)}</span>`;
  
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

// ===== ПРОГРЕСС БАР =====
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
    const width = rect.width;
    audioPlayer.currentTime = (clickX / width) * audioPlayer.duration;
  }
});

// ===== УПРАВЛЕНИЕ ВОСПРОИЗВЕДЕНИЕМ =====
btnPlay.addEventListener('click', async () => {
  if (audioPlayer.paused && audioPlayer.src) {
    try {
      await audioPlayer.play();
    } catch (error) {
      console.warn('Autoplay was prevented:', error);
      // Может потребоваться показать пользователю кнопку "Play"
    }
  } else {
    audioPlayer.pause();
  }
});

btnStop.addEventListener('click', async () => {
  try {
    await fetch('/api/radio/stop', { method: 'POST' });
  } catch (e) {
    console.error('Stop error:', e);
  }
});

btnNext.addEventListener('click', async () => {
  try {
    await fetch('/api/radio/skip', { method: 'POST' });
  } catch (e) {
    console.error('Skip error:', e);
  }
});

btnPrev.addEventListener('click', () => {
  audioPlayer.currentTime = 0;
});

// ===== TOGGLE КНОПКИ =====
btnShuffle.addEventListener('click', () => {
  btnShuffle.classList.toggle('active');
});

btnRepeat.addEventListener('click', () => {
  btnRepeat.classList.toggle('active');
  audioPlayer.loop = btnRepeat.classList.contains('active');
});

// ===== ГРОМКОСТЬ =====
volumeSlider.addEventListener('input', (e) => {
  const value = e.target.value;
  audioPlayer.volume = value / 100;
  volumeValue.textContent = value;
});


// ===== СОБЫТИЯ АУДИО =====
audioPlayer.addEventListener('play', () => {
  isPlaying = true;
  updateUI();
});

audioPlayer.addEventListener('pause', () => {
  isPlaying = false;
  updateUI();
});

audioPlayer.addEventListener('ended', async () => {
  if (!audioPlayer.loop) {
    try {
      await fetch('/api/radio/skip', { method: 'POST' });
    } catch (e) {
      console.error('Auto-skip error:', e);
    }
  }
});

// ===== ПОЛУЧЕНИЕ СТАТУСА =====
async function tick() {
  console.log("Tick function called");
  if (isUpdating) return;
  isUpdating = true;
  
  try {
    const response = await fetch('/api/radio/status');
    const data = await response.json();
    
    const sessions = data.sessions || {};
    const sessionKeys = Object.keys(sessions);
    const session = sessionKeys.length > 0 ? sessions[sessionKeys[0]] : null;
    
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
        // Если сессий нет, останавливаем плеер
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

// ===== TELEGRAM WEBAPP & INIT =====
function initialize() {
    audioPlayer.volume = volumeSlider.value / 100;

    if (window.Telegram && window.Telegram.WebApp) {
      const tg = window.Telegram.WebApp;
      tg.ready();
      tg.expand();
      document.body.style.setProperty('--tg-theme-bg-color', tg.themeParams.bg_color || '#1a1a2e');
    }

    updateUI();
    tick();
    setInterval(tick, 3000);

    const bars = visualizer.querySelectorAll('.bar');
    bars.forEach((bar, index) => {
      bar.style.height = `${Math.random() * 20 + 5}px`;
    });
}

initialize();