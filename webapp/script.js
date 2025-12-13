const audioPlayer = document.getElementById("audio-player");
const playPauseButton = document.getElementById("play-pause-button");
const prevButton = document.getElementById("prev-button");
const nextButton = document.getElementById("next-button");
const trackTitle = document.getElementById("track-title");
const trackArtist = document.getElementById("track-artist");
const trackCover = document.getElementById("track-cover");
const progressBar = document.getElementById("progress-bar");
const progressBarContainer = document.getElementById("progress-bar-container");
const lcdText = document.getElementById("lcd-text");
const leftReel = document.querySelector(".left-reel");
const rightReel = document.querySelector(".right-reel");

let currentTrack = null;
let isPlaying = false; // Состояние воспроизведения
let isUpdating = false; // Флаг, чтобы избежать множественных запросов на изменение трека

// Функция для обновления UI
function updateUI() {
  if (currentTrack && currentTrack.current) {
    trackTitle.textContent = currentTrack.current.title || "Неизвестный трек";
    trackArtist.textContent = currentTrack.current.artist || "Неизвестный исполнитель";
    trackCover.src = currentTrack.current.cover_url || "https://via.placeholder.com/150";
    if (currentTrack.current.cover_url) {
      trackCover.style.display = 'block';
    } else {
      trackCover.style.display = 'none';
    }
    lcdText.textContent = `${currentTrack.current.artist || "Неизв."} - ${currentTrack.current.title || "Неизв. трек"}`;
  } else {
    trackTitle.textContent = "Нет трека";
    trackArtist.textContent = "";
    trackCover.src = "";
    trackCover.style.display = 'none';
    lcdText.textContent = "Привет! Я твой Walkman!";
  }

  playPauseButton.textContent = isPlaying ? "⏸" : "▶";

  if (isPlaying) {
    leftReel.classList.add("playing");
    rightReel.classList.add("playing");
  } else {
    leftReel.classList.remove("playing");
    rightReel.classList.remove("playing");
  }
}

// Отправка команд боту (для Skip и Stop)
async function sendBotCommand(command, query = "") {
  // Для Telegram-бота FastAPI нужно будет создать эндпоинты для этих команд.
  // Пока что, это заглушка.
  console.log(`Отправлена команда боту: ${command} ${query}`);
  // В реальном приложении здесь должен быть запрос к API FastAPI,
  // который затем передаст команду боту Telegram.
  // Например: fetch(`/api/command/${command}`, { method: 'POST', body: JSON.stringify({ query }) });
}

// Обработчики событий
playPauseButton.addEventListener("click", async () => {
  if (audioPlayer.paused && audioPlayer.src) {
    try {
      await audioPlayer.play();
      isPlaying = true;
    } catch (error) {
      console.warn("Автоматическое воспроизведение заблокировано браузером. Нажмите Play вручную.", error);
      isPlaying = false; // Не удалось воспроизвести
    }
  } else {
    audioPlayer.pause();
    isPlaying = false;
  }
  updateUI();
});

prevButton.addEventListener("click", () => {
  // sendBotCommand("prev"); // если есть API для "предыдущего трека"
  console.log("Предыдущий трек (функционал пока не реализован)");
});

nextButton.addEventListener("click", () => {
  sendBotCommand("skip"); // Отправляем команду Skip боту
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
  sendBotCommand("skip"); // Автоматический переход к следующему треку
});

audioPlayer.addEventListener("timeupdate", () => {
  if (audioPlayer.duration) {
    const progress = (audioPlayer.currentTime / audioPlayer.duration) * 100;
    progressBar.style.width = `${progress}%`;
  }
});

progressBarContainer.addEventListener("click", (e) => {
  if (audioPlayer.duration) {
    const width = progressBarContainer.clientWidth;
    const clickX = e.offsetX;
    const duration = audioPlayer.duration;
    audioPlayer.currentTime = (clickX / width) * duration;
  }
});

// Периодическое получение статуса радио и обновление UI
async function tick() {
    if (isUpdating) return;
    isUpdating = true;

    try {
        const r = await fetch("/api/radio/status");
        const j = await r.json();

        const sessions = j.sessions;
        if (Object.keys(sessions).length > 0) {
            const firstSessionKey = Object.keys(sessions)[0];
            const session = sessions[firstSessionKey];

            if (session.current) {
                // Если трек изменился или это первый трек
                if (!currentTrack || currentTrack.current.id !== session.current.id) {
                    console.log("Новый трек:", session.current);
                    currentTrack = session; // Сохраняем всю сессию для удобства
                    updateUI();

                    if (currentTrack.current.audio_url && audioPlayer.src !== currentTrack.current.audio_url) {
                        audioPlayer.src = currentTrack.current.audio_url;
                        audioPlayer.load();
                        try {
                            // Попытка автоматического воспроизведения. Может быть заблокирована браузером.
                            await audioPlayer.play();
                            isPlaying = true;
                        } catch (error) {
                            console.warn("Автоматическое воспроизведение заблокировано браузером. Нажмите Play вручную.", error);
                            isPlaying = false;
                        }
                    }
                }
            } else {
                // Нет текущего трека в сессии
                if (currentTrack) {
                    console.log("Текущий трек исчез из сессии");
                    currentTrack = null;
                    audioPlayer.pause();
                    audioPlayer.src = "";
                    isPlaying = false;
                    updateUI();
                }
            }
        } else {
            // Нет активных сессий
            if (currentTrack) {
                console.log("Нет активных сессий");
                currentTrack = null;
                audioPlayer.pause();
                audioPlayer.src = "";
                isPlaying = false;
                updateUI();
            }
        }
    } catch (e) {
        console.error("Ошибка при получении статуса радио:", e);
        lcdText.textContent = "Ошибка загрузки статуса...";
        trackTitle.textContent = "Ошибка загрузки";
        trackArtist.textContent = "";
        trackCover.style.display = 'none';
        isPlaying = false;
        updateUI();
    } finally {
        isUpdating = false;
    }
}

// Инициализация и запуск опроса
updateUI(); // Первичное обновление UI
tick();
setInterval(tick, 3000);