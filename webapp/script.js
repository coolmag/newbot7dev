document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram.WebApp;
    tg.expand();

    // === HAPTIC FEEDBACK HELPER ===
    const haptic = {
        isSupported: tg.isVersionAtLeast('6.1'),
        impact: (style = 'medium') => {
            if (haptic.isSupported) {
                tg.HapticFeedback.impactOccurred(style);
            }
        },
        notification: (type = 'success') => {
            if (haptic.isSupported) {
                tg.HapticFeedback.notificationOccurred(type);
            }
        },
        selection: () => {
            if (haptic.isSupported) {
                tg.HapticFeedback.selectionChanged();
            }
        }
    };

    // === ELEMENTS ===
    const audio = document.getElementById('audio-player');
    const playBtn = document.getElementById('btn-play-pause');
    const playIcon = document.getElementById('icon-play');
    const vinylRecord = document.getElementById('vinyl-record');
    const tonearm = document.getElementById('tonearm');
    const sunRays = document.getElementById('sun-rays');
    const vinylGlow = document.getElementById('vinyl-glow');
    const nextBtn = document.getElementById('btn-next');
    const prevBtn = document.getElementById('btn-prev');
    const rewindBtn = document.getElementById('btn-rewind');
    const forwardBtn = document.getElementById('btn-forward');
    const titleEl = document.getElementById('track-title');
    const artistEl = document.getElementById('track-artist');
    const progressContainer = document.getElementById('progress-container');
    const progressEl = document.getElementById('progress-bar');
    const progressBuffered = document.getElementById('progress-buffered');
    const progressHandle = document.getElementById('progress-handle');
    const currTimeEl = document.getElementById('curr-time');
    const durTimeEl = document.getElementById('dur-time');
    const currentGenreEl = document.getElementById('current-genre');
    const playbackSpeed = document.getElementById('playback-speed');
    const canvas = document.getElementById('visualizer');
    const ctx = canvas?.getContext('2d');
    const screenPlayer = document.getElementById('screen-player');
    const screenGenres = document.getElementById('screen-genres');
    const btnGenres = document.getElementById('btn-genres');
    const btnBackPlayer = document.getElementById('btn-back-player');
    const subgenreDrawer = document.getElementById('subgenre-drawer');
    const playlistDrawer = document.getElementById('playlist-drawer');
    const overlay = document.getElementById('overlay');
    const btnPlaylist = document.getElementById('btn-playlist');
    const genreGrid = document.getElementById('genre-grid');
    const trendingChips = document.getElementById('trending-chips');
    const decadeChips = document.getElementById('decade-chips');
    const moodChips = document.getElementById('mood-chips');
    const genreSearch = document.getElementById('genre-search');
    const subgenreList = document.getElementById('subgenre-list');
    const drawerTitle = document.getElementById('drawer-title');
    const drawerIcon = document.getElementById('drawer-icon');

    // === STATE ===
    let audioCtx, analyser, dataArray;
    let isInitialized = false;
    let currentGenre = null;
    let isSeeking = false;
    let playerPlaylist = [];
    let currentTrackIndex = -1;
    let isLoading = false; // Флаг для загрузки плейлиста/жанра
    let isAudioLoading = false; // НОВЫЙ ФЛАГ: для загрузки конкретного аудио
    let audioLoadTimeout = null;

    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    // === GENRE DATABASE ===
    const GENRES = {
        pop: { name: "Pop", icon: "🎤", color: "#FF6B9D", subgenres: { modern: { name: "Modern Pop", search: "pop hits 2024", styles: "Dance Pop, Electropop, Synth Pop" }, classic: { name: "Classic Pop", search: "80s 90s pop hits", styles: "80s Pop, 90s Pop, Europop" }, kpop: { name: "K-Pop", search: "kpop hits", styles: "BTS, BLACKPINK, Korean Pop" }, latin: { name: "Latin Pop", search: "reggaeton latin hits", styles: "Reggaeton, Bachata, Latin Urban" }, indie: { name: "Indie Pop", search: "indie pop music", styles: "Bedroom Pop, Art Pop, Dream Pop" } } },
        hiphop: { name: "Hip-Hop", icon: "🎤", color: "#FFD93D", subgenres: { trap: { name: "Trap", search: "trap music hits", styles: "Modern Trap, Drill, Rage" }, oldschool: { name: "Old School", search: "90s hip hop classics", styles: "Boom Bap, Golden Age, G-Funk" }, melodic: { name: "Melodic Rap", search: "melodic rap", styles: "Trapsoul, Emo Rap, Melodic" }, underground: { name: "Underground", search: "underground hip hop", styles: "Conscious, Alternative, Lyrical" } } },
        electronic: { name: "Electronic", icon: "🎧", color: "#9B59B6", subgenres: { house: { name: "House", search: "house music", styles: "Deep House, Tech House, Future House" }, techno: { name: "Techno", search: "techno music", styles: "Minimal, Industrial, Detroit" }, edm: { name: "EDM", search: "edm bangers", styles: "Big Room, Future Bass, Dubstep" }, dnb: { name: "Drum & Bass", search: "drum and bass", styles: "Liquid, Jump Up, Neurofunk" }, trance: { name: "Trance", search: "trance music", styles: "Progressive, Uplifting, Psytrance" }, chill: { name: "Chill", search: "chillout lofi", styles: "Lo-Fi, Chillwave, Ambient" } } },
        rock: { name: "Rock", icon: "🎸", color: "#E74C3C", subgenres: { classic: { name: "Classic Rock", search: "classic rock hits", styles: "70s Rock, Arena Rock, Blues Rock" }, alternative: { name: "Alternative", search: "alternative rock", styles: "Indie Rock, Grunge, Post-Punk" }, metal: { name: "Metal", search: "heavy metal", styles: "Heavy, Thrash, Nu-Metal" }, punk: { name: "Punk", search: "punk rock", styles: "Pop Punk, Hardcore, Emo" } } },
        rnb: { name: "R&B / Soul", icon: "💜", color: "#8E44AD", subgenres: { modern: { name: "Modern R&B", search: "r&b hits 2024", styles: "Alternative R&B, Trapsoul, PBR&B" }, classic: { name: "Classic R&B", search: "90s r&b", styles: "New Jack Swing, Quiet Storm" }, soul: { name: "Soul", search: "soul music", styles: "Neo Soul, Motown, Northern Soul" }, funk: { name: "Funk", search: "funk music", styles: "P-Funk, Boogie, Electro Funk" } } },
        jazz: { name: "Jazz", icon: "🎷", color: "#3498DB", subgenres: { classic: { name: "Classic Jazz", search: "jazz classics", styles: "Bebop, Swing, Cool Jazz" }, modern: { name: "Modern Jazz", search: "modern jazz", styles: "Nu Jazz, Acid Jazz, Jazz Fusion" }, smooth: { name: "Smooth Jazz", search: "smooth jazz", styles: "Contemporary, Chill Jazz" } } },
    };
    const TRENDING = [ 
        { name: "🔥 Viral TikTok", search: "tiktok viral hits 2024" }, 
        { name: "📈 Top Charts", search: "top 50 hits 2024" }, 
        { name: "🆕 New Releases", search: "new music 2024" }, 
        { name: "💎 Best of 2024", search: "best songs 2024" } 
    ];
    const DECADES = [ 
        { name: "2020s", search: "2020s hits" }, 
        { name: "2010s", search: "2010s hits" }, 
        { name: "2000s", search: "2000s hits" }, 
        { name: "90s", search: "90s hits" }, 
        { name: "80s", search: "80s hits" }, 
        { name: "70s", search: "70s hits" } 
    ];
    const MOODS = [ 
        { name: "😌 Chill", search: "chill relaxing music" }, 
        { name: "🎉 Party", search: "party music hits" }, 
        { name: "💪 Workout", search: "workout motivation music" }, 
        { name: "😢 Sad", search: "sad songs" }, 
        { name: "❤️ Romantic", search: "love songs romantic" }, 
        { name: "📚 Focus", search: "study focus music" }, 
        { name: "😴 Sleep", search: "sleep relaxation music" } 
    ];

    // === AUDIO HELPERS ===
    function safePlay() {
        if (!audio.src || isLoading) return Promise.resolve();
        
        return audio.play().catch(err => {
            console.error("Playback error:", err.name, err.message);
            if (err.name === 'NotSupportedError') {
                titleEl.textContent = "Audio format not supported";
                artistEl.textContent = "Trying next track...";
                setTimeout(() => playNextTrack(), 1000);
            } else if (err.name === 'NotAllowedError') {
                console.log("Playback prevented by browser policy");
                titleEl.textContent = "Playback blocked";
                artistEl.textContent = "Tap play button to start";
                haptic.notification('error');
            }
            playIcon.textContent = 'play_arrow';
        });
    }

    function clearAudioTimeouts() {
        if (audioLoadTimeout) {
            clearTimeout(audioLoadTimeout);
            audioLoadTimeout = null;
        }
    }

    // === CORE LOGIC ===
    function playTrack(index) {
        console.log('[playTrack] НАЧАЛО ВЫПОЛНЕНИЯ playTrack'); // НОВЫЙ ЛОГ
        if (isAudioLoading || index < 0 || index >= playerPlaylist.length) {
            if (index >= playerPlaylist.length) {
                playIcon.textContent = 'play_arrow';
                titleEl.textContent = "Playlist finished";
                artistEl.textContent = "Select a new genre";
                currentTrackIndex = -1;
                audio.src = "";
                audio.load();
                isAudioLoading = false; // Сброс флага при завершении плейлиста
            }
            console.log('[playTrack] Возврат из playTrack: isAudioLoading=' + isAudioLoading + ', index=' + index);
            return;
        }

        clearAudioTimeouts();
        isAudioLoading = true; // Устанавливаем флаг, что аудио начинает загружаться
        currentTrackIndex = index;
        const track = playerPlaylist[index];

        titleEl.textContent = track.title || 'Unknown';
        artistEl.textContent = track.artist || 'Unknown';
        
        audio.pause();
        
        // Remove old listeners to prevent memory leaks
        audio.removeEventListener('canplay', handleCanPlay);
        audio.removeEventListener('error', handleError);
        audio.removeEventListener('loadedmetadata', handleLoadedMetadata);

        const audioUrl = track.url || `/audio/${track.identifier}`; 
        console.log('[playTrack] 1. Устанавливаю audio.src:', audioUrl);
        audio.src = audioUrl;

        function handleCanPlay() {
            console.log('[playTrack] 4. Событие "canplay" сработало. Вызываю safePlay.');
            clearAudioTimeouts();
            safePlay().finally(() => {
                isAudioLoading = false; // Сброс флага после попытки воспроизведения
            });
            audio.removeEventListener('canplay', handleCanPlay);
        }

        function handleError(e) {
            console.error("[playTrack] 5. Событие 'error' сработало:", track.title, "URL:", audioUrl, "Error:", e);
            clearAudioTimeouts();
            isAudioLoading = false; // Сброс флага при ошибке
            titleEl.textContent = "Track unavailable";
            artistEl.textContent = "Skipping...";
            setTimeout(() => playNextTrack(), 1500);
            audio.removeEventListener('error', handleError);
        }

        function handleLoadedMetadata() {
            console.log('[playTrack] Событие "loadedmetadata" сработало.');
            clearAudioTimeouts();
            audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
        }

        // Set timeout to prevent hanging on bad sources
        audioLoadTimeout = setTimeout(() => {
            if (isAudioLoading) { // Проверяем НОВЫЙ ФЛАГ
                console.warn("Track load timeout, skipping...");
                isAudioLoading = false; // Сброс флага при таймауте
                playNextTrack();
            }
        }, 10000); 

        audio.addEventListener('canplay', handleCanPlay);
        audio.addEventListener('error', handleError);
        audio.addEventListener('loadedmetadata', handleLoadedMetadata);
        
        try {
            console.log('[playTrack] 2. Вызываю audio.load().');
            audio.load();
            console.log('[playTrack] 3. audio.load() выполнен без ошибок.');
        } catch (e) {
            console.error('[playTrack] Ошибка при вызове audio.load():', e);
        }

        updateMediaSessionMetadata();
    }

    async function selectGenre(name, searchQuery) {
        if (isLoading) {
            console.log("selectGenre: Уже идет загрузка, игнорируем выбор.");
            return;
        }
        isLoading = true;
        currentGenre = name;
        currentGenreEl.textContent = name.toUpperCase();
        titleEl.textContent = "Loading playlist...";
        artistEl.textContent = "Accessing the Grid...";
        closeGenresScreen();
        closeDrawers();
        
        try {
            const response = await fetch(`/api/player/playlist?query=${encodeURIComponent(searchQuery)}`);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            console.log('Playlist API response:', data);
            playerPlaylist = data.playlist || [];
            console.log('First track:', playerPlaylist[0]);
            if (playerPlaylist.length > 0) {
                playTrack(0);
            } else {
                titleEl.textContent = "No tracks found";
                artistEl.textContent = "Try another genre";
            }
        } catch (e) {
            console.error('Failed to fetch playlist:', e);
            titleEl.textContent = "Error loading playlist";
            artistEl.textContent = "Please try again";
        } finally {
            isLoading = false; // Сбрасываем флаг загрузки в любом случае
        }
        haptic.impact('medium');
    }

    const playNextTrack = () => playTrack(currentTrackIndex + 1);
    const playPrevTrack = () => playTrack(currentTrackIndex - 1);

    // === AUDIO CONTEXT & VISUALIZER ===
    function initAudio() {
        if (isInitialized) return;
        try {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            analyser = audioCtx.createAnalyser();
            analyser.fftSize = 128;
            const source = audioCtx.createMediaElementSource(audio);
            source.connect(analyser);
            analyser.connect(audioCtx.destination);
            dataArray = new Uint8Array(analyser.frequencyBinCount);
            isInitialized = true;
            drawSunRays();
        } catch (e) {
            console.error('Audio context initialization failed:', e);
        }
    }

    // Generate sun rays
    function generateSunRays() {
        if (!sunRays) return;
        sunRays.innerHTML = '';
        const rayCount = 16;
        for (let i = 0; i < rayCount; i++) {
            const ray = document.createElement('div');
            ray.className = 'sun-ray';
            ray.style.transform = `rotate(${i * (360 / rayCount)}deg)`;
            ray.dataset.index = i;
            sunRays.appendChild(ray);
        }
    }

    // Animate sun rays based on audio
    function drawSunRays() {
        if (!analyser || !sunRays) return;
        requestAnimationFrame(drawSunRays);
        analyser.getByteFrequencyData(dataArray);
        
        const rays = sunRays.querySelectorAll('.sun-ray');
        rays.forEach((ray, i) => {
            const dataIndex = Math.floor((i / rays.length) * dataArray.length);
            const value = dataArray[dataIndex] || 0;
            const height = 80 + (value / 255) * 60; // 80-140px
            ray.style.height = height + 'px';
            ray.style.opacity = 0.4 + (value / 255) * 0.6;
        });
    }

    // === MEDIA SESSION ===
    function updateMediaSessionMetadata() {
        if ('mediaSession' in navigator && currentTrackIndex >= 0) {
            const track = playerPlaylist[currentTrackIndex];
            navigator.mediaSession.metadata = new MediaMetadata({
                title: track.title || 'Unknown',
                artist: track.artist || 'Unknown',
                album: currentGenre || 'Music',
            });
            
            navigator.mediaSession.setActionHandler('play', () => safePlay());
            navigator.mediaSession.setActionHandler('pause', () => audio.pause());
            navigator.mediaSession.setActionHandler('previoustrack', playPrevTrack);
            navigator.mediaSession.setActionHandler('nexttrack', playNextTrack);
        }
    }

    // === AUDIO EVENT LISTENERS ===
    audio.addEventListener('play', () => { 
        playIcon.textContent = 'pause';
        vinylRecord?.classList.add('playing');
        tonearm?.classList.add('playing');
        sunRays?.classList.add('playing');
        vinylGlow?.classList.add('active');
    });
    
    audio.addEventListener('pause', () => { 
        playIcon.textContent = 'play_arrow';
        vinylRecord?.classList.remove('playing');
        tonearm?.classList.remove('playing');
        sunRays?.classList.remove('playing');
        vinylGlow?.classList.remove('active');
    });
    
    audio.addEventListener('ended', playNextTrack);
    
    audio.addEventListener('timeupdate', () => {
        if (!isSeeking && audio.duration) {
            const progress = (audio.currentTime / audio.duration) * 100;
            progressEl.style.width = progress + '%';
            progressHandle.style.left = progress + '%';
            currTimeEl.textContent = formatTime(audio.currentTime);
        }
    });

    audio.addEventListener('durationchange', () => {
        if (audio.duration && isFinite(audio.duration)) {
            durTimeEl.textContent = formatTime(audio.duration);
        }
    });

    audio.addEventListener('progress', () => {
        if (audio.buffered.length > 0 && audio.duration) {
            const buffered = audio.buffered.end(audio.buffered.length - 1);
            progressBuffered.style.width = ((buffered / audio.duration) * 100) + '%';
        }
    });

    // === UI HELPERS ===
    function formatTime(seconds) {
        if (!isFinite(seconds)) return '0:00';
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    function closeDrawers() {
        subgenreDrawer?.classList.remove('active');
        playlistDrawer?.classList.remove('active');
        overlay?.classList.remove('active');
    }

    function openGenresScreen() {
        screenGenres?.classList.add('active');
        screenPlayer?.classList.remove('active');
    }

    function closeGenresScreen() {
        screenGenres?.classList.remove('active');
        screenPlayer?.classList.add('active');
    }

    // === EVENT LISTENERS ===
    playBtn?.addEventListener('click', () => {
        if (isLoading || !audio.src) return;
        initAudio();
        if (audioCtx?.state === 'suspended') audioCtx.resume();
        audio.paused ? safePlay() : audio.pause();
        haptic.impact('light');
    });

    nextBtn?.addEventListener('click', () => {
        if (!isLoading) {
            playNextTrack();
            haptic.impact('medium');
        }
    });

    prevBtn?.addEventListener('click', () => {
        if (isLoading) return;
        if (audio.currentTime > 3) {
            audio.currentTime = 0;
        } else {
            playPrevTrack();
        }
        haptic.impact('medium');
    });

    rewindBtn?.addEventListener('click', () => {
        if (!isFinite(audio.duration)) return;
        audio.currentTime = Math.max(0, audio.currentTime - 10);
        haptic.impact('light');
    });

    forwardBtn?.addEventListener('click', () => {
        if (!isFinite(audio.duration)) return;
        audio.currentTime = Math.min(audio.duration, audio.currentTime + 10);
        haptic.impact('light');
    });

    playbackSpeed?.addEventListener('click', () => {
        const speeds = [1, 1.25, 1.5, 1.75, 2];
        const currentIndex = speeds.indexOf(audio.playbackRate);
        const nextIndex = (currentIndex + 1) % speeds.length;
        audio.playbackRate = speeds[nextIndex];
        playbackSpeed.textContent = speeds[nextIndex] + 'x';
        haptic.selection();
    });

    // Progress bar seeking
    progressContainer?.addEventListener('click', (e) => {
        if (!audio.duration) return;
        const rect = progressContainer.getBoundingClientRect();
        const percent = (e.clientX - rect.left) / rect.width;
        audio.currentTime = percent * audio.duration;
        haptic.impact('light');
    });

    let isDragging = false;
    progressHandle?.addEventListener('touchstart', () => { isDragging = true; isSeeking = true; });
    progressHandle?.addEventListener('mousedown', () => { isDragging = true; isSeeking = true; });

    document.addEventListener('touchmove', (e) => {
        if (!isDragging || !audio.duration) return;
        const rect = progressContainer.getBoundingClientRect();
        const touch = e.touches[0];
        const percent = Math.max(0, Math.min(1, (touch.clientX - rect.left) / rect.width));
        audio.currentTime = percent * audio.duration;
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging || !audio.duration) return;
        const rect = progressContainer.getBoundingClientRect();
        const percent = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        audio.currentTime = percent * audio.duration;
    });

    document.addEventListener('touchend', () => { isDragging = false; isSeeking = false; });
    document.addEventListener('mouseup', () => { isDragging = false; isSeeking = false; });

    // Navigation
    btnGenres?.addEventListener('click', () => {
        openGenresScreen();
        haptic.impact('medium');
    });

    btnBackPlayer?.addEventListener('click', () => {
        closeGenresScreen();
        haptic.impact('medium');
    });

    btnPlaylist?.addEventListener('click', () => {
        if (!playlistDrawer || !overlay) return;
        playlistDrawer.classList.add('active');
        overlay.classList.add('active');
        renderPlaylist();
        haptic.impact('medium');
    });

    overlay?.addEventListener('click', closeDrawers);

    // === UI INITIALIZATION ===
    function createChips(container, items) {
        if (!container) return;
        container.innerHTML = '';
        items.forEach(item => {
            const chip = document.createElement('button');
            chip.className = 'chip';
            chip.textContent = item.name;
            chip.onclick = () => {
                selectGenre(item.name, item.search);
                haptic.selection();
            };
            container.appendChild(chip);
        });
    }

    function renderGenres() {
        if (!genreGrid) return;
        genreGrid.innerHTML = '';
        Object.entries(GENRES).forEach(([key, genre]) => {
            const card = document.createElement('button');
            card.className = 'genre-card';
            card.style.setProperty('--genre-color', genre.color);
            card.innerHTML = `
                <div class="genre-icon">${genre.icon}</div>
                <div class="genre-name">${genre.name}</div>
            `;
            card.onclick = () => {
                if (!subgenreDrawer || !overlay || !drawerTitle || !drawerIcon || !subgenreList) return;
                drawerTitle.textContent = genre.name;
                drawerIcon.textContent = genre.icon;
                subgenreList.innerHTML = '';
                Object.entries(genre.subgenres).forEach(([subKey, sub]) => {
                    const item = document.createElement('button');
                    item.className = 'subgenre-item';
                    item.innerHTML = `
                        <div>
                            <div class="subgenre-name">${sub.name}</div>
                            <div class="subgenre-styles">${sub.styles}</div>
                        </div>
                        <span class="material-icons">arrow_forward</span>
                    `;
                    item.onclick = () => selectGenre(sub.name, sub.search);
                    subgenreList.appendChild(item);
                });
                subgenreDrawer.classList.add('active');
                overlay.classList.add('active');
                haptic.impact('medium');
            };
            genreGrid.appendChild(card);
        });
    }

    function renderPlaylist() {
        const playlistContent = document.getElementById('playlist-content');
        if (!playlistContent) return;
        playlistContent.innerHTML = '';
        
        if (playerPlaylist.length === 0) {
            playlistContent.innerHTML = '<div style="padding: 2rem; text-align: center; color: #666;">No playlist loaded</div>';
            return;
        }

        playerPlaylist.forEach((track, index) => {
            const item = document.createElement('button');
            item.className = 'playlist-item' + (index === currentTrackIndex ? ' active' : '');
            item.innerHTML = `
                <span class="material-icons">${index === currentTrackIndex ? 'play_circle' : 'music_note'}</span>
                <div class="playlist-track-info">
                    <div class="playlist-track-title">${track.title || 'Unknown'}</div>
                    <div class="playlist-track-artist">${track.artist || 'Unknown'}</div>
                </div>
            `;
            item.onclick = () => {
                playTrack(index);
                closeDrawers();
                haptic.impact('medium');
            };
            playlistContent.appendChild(item);
        });
    }

    // Genre search
    genreSearch?.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase();
        if (!genreGrid) return;
        const cards = genreGrid.querySelectorAll('.genre-card');
        cards.forEach(card => {
            const name = card.querySelector('.genre-name')?.textContent.toLowerCase() || '';
            card.style.display = name.includes(query) ? 'flex' : 'none';
        });
    });

    // Initialize UI
    generateSunRays();
    createChips(trendingChips, TRENDING);
    createChips(decadeChips, DECADES);
    createChips(moodChips, MOODS);
    renderGenres();

    // Show genres screen initially if no playlist
    if (playerPlaylist.length === 0) {
        openGenresScreen();
    }

    console.log('Music Player initialized', { 
        hapticSupported: haptic.isSupported,
        telegramVersion: tg.version 
    });
});