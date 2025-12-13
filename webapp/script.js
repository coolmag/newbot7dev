const audioPlayer = document.getElementById("audio-player");
const playPauseButton = document.getElementById("play-pause-button");
const prevButton = document.getElementById("prev-button");
const nextButton = document.getElementById("next-button");
const trackTitle = document.getElementById("track-title");
const trackArtist = document.getElementById("track-artist");
const trackCover = document.getElementById("track-cover");
const progressBar = document.getElementById("progress-bar");
const progressBarContainer = document.getElementById("progress-bar-container");

let currentTrack = null;
let isPlaying = false;

// Функция для обновления UI
function updateUI() {
  if (currentTrack) {
    trackTitle.textContent = currentTrack.current || "Нет трека";
    trackArtist.textContent = currentTrack.artist || ""; // Предполагаем, что API будет возвращать artist
    trackCover.src = currentTrack.cover_url || ""; // Предполагаем, что API будет возвращать cover_url
    if (currentTrack.cover_url) {
        trackCover.style.display = 'block';
    } else {
        trackCover.style.display = 'none'; // Скрыть, если нет обложки
    }
  } else {
    trackTitle.textContent = "Нет трека";
    trackArtist.textContent = "";
    trackCover.src = "";
    trackCover.style.display = 'none';
  }

  playPauseButton.textContent = isPlaying ? "⏸" : "▶";
}

// Функция для запроса к API бота
async function sendBotCommand(command, query = "") {
  // В реальном приложении здесь будет AJAX-запрос к вашему бэкенду,
  // который затем отправит команду боту Telegram.
  // Для простоты, здесь мы просто имитируем отправку команды.
  console.log(`Отправлена команда боту: ${command} ${query}`);
  // Временная имитация ответа для тестирования UI
  if (command === "play" || command === "radio") {
    // В реальном сценарии, бот отправит трек в чат, и мы должны будем получить его URL для воспроизведения.
    // Пока что, просто имитируем
    // currentTrack = {
    //   current: `Имитация трека для ${query}`,
    //   artist: "Неизвестный",
    //   cover_url: "https://via.placeholder.com/150",
    //   audio_url: "URL_НА_АУДИО_ТРЕК", // Здесь должен быть реальный URL аудио
    // };
    // updateUI();
    // audioPlayer.src = currentTrack.audio_url;
    // audioPlayer.play();
    // isPlaying = true;
  }
  if (command === "stop") {
    audioPlayer.pause();
    isPlaying = false;
    updateUI();
  }
}

// Обработчики событий
playPauseButton.addEventListener("click", () => {
  if (isPlaying) {
    audioPlayer.pause();
    isPlaying = false;
  } else {
    audioPlayer.play();
    isPlaying = true;
  }
  updateUI();
});

prevButton.addEventListener("click", () => {
  // Здесь можно будет реализовать логику "предыдущий трек",
  // возможно, через команду боту или управление плейлистом на клиенте.
  console.log("Предыдущий трек");
});

nextButton.addEventListener("click", () => {
  // Здесь можно будет реализовать логику "следующий трек",
  // возможно, через команду боту или управление плейлистом на клиенте.
  // Или просто отправить /skip боту.
  sendBotCommand("skip");
});

audioPlayer.addEventListener("play", () => {
  isPlaying = true;
  updateUI();
});

audioPlayer.addEventListener("pause", () => {
  isPlaying = false;
  updateUI();
});

audioPlayer.addEventListener("ended", () => {
  isPlaying = false;
  updateUI();
  // Автоматический переход к следующему треку (если реализовано)
  sendBotCommand("skip");
});

audioPlayer.addEventListener("timeupdate", () => {
  const progress = (audioPlayer.currentTime / audioPlayer.duration) * 100;
  progressBar.style.width = `${progress}%`;
});

// Обновление прогресса при клике на полосу
progressBarContainer.addEventListener("click", (e) => {
  const width = progressBarContainer.clientWidth;
  const clickX = e.offsetX;
  const duration = audioPlayer.duration;
  audioPlayer.currentTime = (clickX / width) * duration;
});


// Периодическое получение статуса радио и обновление UI
async function tick() {
  try {
    const r = await fetch("/api/radio/status");
    const j = await r.json();

    // Проверяем, есть ли активные сессии
    const sessions = j.sessions;
    if (Object.keys(sessions).length > 0) {
      // Берем первую попавшуюся сессию (или ту, что активна для текущего пользователя, если есть такая логика)
      const firstSessionKey = Object.keys(sessions)[0];
      const session = sessions[firstSessionKey];

      // Если текущий трек изменился или его еще нет
      if (!currentTrack || currentTrack.current !== session.current) {
        currentTrack = {
          current: session.current,
          artist: session.artist || "Неизвестный", // Добавляем artist, если API предоставляет
          cover_url: session.cover_url || "https://via.placeholder.com/150", // Добавляем cover_url, если API предоставляет
          audio_url: session.audio_url || "", // Здесь должен быть URL для воспроизведения
        };
        updateUI();

        // Если есть audio_url и он отличается от текущего, начать воспроизведение
        if (currentTrack.audio_url && audioPlayer.src !== currentTrack.audio_url) {
            audioPlayer.src = currentTrack.audio_url;
            audioPlayer.load(); // Перезагрузить аудио
            try {
                await audioPlayer.play();
                isPlaying = true;
            } catch (error) {
                console.warn("Автоматическое воспроизведение заблокировано браузером. Нажмите Play.", error);
                isPlaying = false;
            }
        }
      }
    } else {
      // Если нет активных сессий, сбросить UI
      currentTrack = null;
      audioPlayer.pause();
      audioPlayer.src = "";
      isPlaying = false;
      updateUI();
    }
  } catch (e) {
    console.error("Ошибка при получении статуса радио:", e);
    // В случае ошибки можно показать сообщение об ошибке в UI
    trackTitle.textContent = "Ошибка загрузки";
    trackArtist.textContent = "";
    trackCover.style.display = 'none';
    isPlaying = false;
    updateUI();
  }
}

// Инициализация и запуск опроса
updateUI(); // Первичное обновление UI
tick();
setInterval(tick, 3000);