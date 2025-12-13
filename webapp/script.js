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

// Дисплей
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
const cassetteLabel = document.getElementById('cassette-label');

// Катушки
const leftReel = document.getElementById('left-reel');
const rightReel = document.getElementById('right-reel');

// ===== СОСТОЯНИЕ =====
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
  if (!session) {
    trackTitle.innerHTML = '<span>Ожидание трека...</span>';
    trackArtist.textContent = '---';
    queryText.textContent = '---';
    queueCount.textContent = '0';
    return;
  }

  // Название и исполнитель
  const title = session.current || 'Загрузка...';
  trackTitle.innerHTML = `<span>${truncateText(title, 40)}</span>`;
  
  // Если название длинное - включаем прокрутку
  if (title.length > 25) {
    trackTitle.classList.add('scrolling');
  } else {
    trackTitle.classList.remove('scrolling');
  }
  
  trackArtist.textContent = session.query || '---';
  
  // Жанр
  const genre = detectGenre(session.query);
  genreIcon.textContent = genre.icon;
  genreText.textContent = genre.name;
  
  // Очередь
  queryText.textContent = truncateText(session.query, 15);
  queueCount.textContent = session.playlist_len || 0;
  
  // Статус
  if (session.last_error) {
    statusIcon.textContent = '⚠️';
    statusText.textContent = 'ERROR';
  } else if (session.current) {
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
    totalTimeEl.textContent = formatTime(audioPlayer.duration);
  }
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
      isPlaying = true;
    } catch (error) {
      console.warn('Autoplay blocked:', error);
      isPlaying = false;
    }
  } else {
    audioPlayer.pause();
    isPlaying = false;
  }
  updateUI();
});

btnStop.addEventListener('click', async () => {
  audioPlayer.pause();
  audioPlayer.currentTime = 0;
  isPlaying = false;
  updateUI();
  
  // Отправляем команду stop на сервер
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
  // Перемотка в начало текущего трека
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

// Инициализация громкости
audioPlayer.volume = volumeSlider.value / 100;

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
  isPlaying = false;
  updateUI();
  
  // Автоматический skip
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
  if (isUpdating) return;
  isUpdating = true;
  
  try {
    const response = await fetch('/api/radio/status');
    const data = await response.json();
    
    const sessions = data.sessions || {};
    const sessionKeys = Object.keys(sessions);
    
    if (sessionKeys.length > 0) {
      const session = sessions[sessionKeys[0]];
      updateTrackInfo(session);
      
      // Если есть audio_url и он изменился
      if (session.audio_url && audioPlayer.src !== session.audio_url) {
        audioPlayer.src = session.audio_url;
        audioPlayer.load();
        try {
          await audioPlayer.play();
          isPlaying = true;
        } catch (error) {
          console.warn('Autoplay blocked:', error);
          isPlaying = false;
        }
        updateUI();
      }
    } else {
      updateTrackInfo(null);
      if (currentTrack) {
        audioPlayer.pause();
        audioPlayer.src = '';
        isPlaying = false;
        updateUI();
      }
    }
    
    currentTrack = sessionKeys.length > 0 ? sessions[sessionKeys[0]] : null;
    
  } catch (error) {
    console.error('Status fetch error:', error);
    statusIcon.textContent = '❌';
    statusText.textContent = 'CONNECTION ERROR';
  } finally {
    isUpdating = false;
  }
}

// ===== TELEGRAM WEBAPP =====
if (window.Telegram && window.Telegram.WebApp) {
  const tg = window.Telegram.WebApp;
  tg.ready();
  tg.expand();
  
  // Применяем тему Telegram
  document.body.style.setProperty('--tg-theme-bg-color', tg.themeParams.bg_color || '#1a1a2e');
}

// ===== ИНИЦИАЛИЗАЦИЯ =====
updateUI();
tick();
setInterval(tick, 3000);

// Анимация визуализатора при загрузке
const bars = visualizer.querySelectorAll('.bar');
bars.forEach((bar, index) => {
  bar.style.height = `${Math.random() * 20 + 5}px`;
});