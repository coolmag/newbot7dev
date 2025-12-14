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
let chatId = null;

// ===== ИНИЦИАЛИЗАЦИЯ =====
function initialize() {
    const urlParams = new URLSearchParams(window.location.search);
    chatId = urlParams.get('chat_id');
    if (!chatId) {
        console.error("chat_id is missing from URL");
        statusText.textContent = 'ERROR: chat_id missing';
    }

    updateUI();
    tick();
    setInterval(tick, 3000);

    // Анимация визуализатора при загрузке
    const bars = visualizer.querySelectorAll('.bar');
    bars.forEach((bar, index) => {
        bar.style.height = `${Math.random() * 20 + 5}px`;
    });

    if (window.Telegram && window.Telegram.WebApp) {
        const tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();
        document.body.style.setProperty('--tg-theme-bg-color', tg.themeParams.bg_color || '#1a1a2e');
    }
}

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
  
  if (!chatId) return;
  try {
    await fetch('/api/radio/stop', { 
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_id: chatId })
    });
  } catch (e) {
    console.error('Stop error:', e);
  }
});

btnNext.addEventListener('click', async () => {
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
  
  if (!chatId) return;
  // Автоматический skip
  if (!audioPlayer.loop) {
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

// ===== ПОЛУЧЕНИЕ СТАТУСА =====
async function tick() {
  if (isUpdating || !chatId) return;
  isUpdating = true;
  
  try {
    const response = await fetch(`/api/radio/status?chat_id=${chatId}`);
    const data = await response.json();
    
    const session = data.sessions ? data.sessions[chatId] : null;

    if (session) {
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
    
    currentTrack = session;
    
  } catch (error) {
    console.error('Status fetch error:', error);
    statusIcon.textContent = '❌';
    statusText.textContent = 'CONNECTION ERROR';
  } finally {
    isUpdating = false;
  }
}

// ===== TELEGRAM WEBAPP =====
// Заменено на вызов в initialize
initialize();