document.addEventListener('DOMContentLoaded', () => {
    const tg = window.Telegram.WebApp;
    tg.expand();

    // === ELEMENTS ===
    const audio = document.getElementById('audio-player');
    const playBtn = document.getElementById('btn-play-pause');
    const playIcon = document.getElementById('icon-play');
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
    const ctx = canvas.getContext('2d');

    // Screens
    const screenPlayer = document.getElementById('screen-player');
    const screenGenres = document.getElementById('screen-genres');
    const btnGenres = document.getElementById('btn-genres');
    const btnBackPlayer = document.getElementById('btn-back-player');

    // Drawers
    const subgenreDrawer = document.getElementById('subgenre-drawer');
    const playlistDrawer = document.getElementById('playlist-drawer');
    const overlay = document.getElementById('overlay');
    const btnPlaylist = document.getElementById('btn-playlist');

    // Genre elements
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

    const urlParams = new URLSearchParams(window.location.search);
    const chatId = urlParams.get('chat_id');

    // === MEDIA SESSION API ===
    function setupMediaSession() {
        if ('mediaSession' in navigator) {
            navigator.mediaSession.metadata = new MediaMetadata({
                title: titleEl.textContent || 'Solar Radio',
                artist: artistEl.textContent || 'Live Radio',
                album: currentGenre || 'Radio',
                artwork: [{ src: 'favicon.svg', sizes: '512x512', type: 'image/svg+xml' }]
            });

            navigator.mediaSession.setActionHandler('play', () => { audio.play(); playIcon.textContent = 'pause'; });
            navigator.mediaSession.setActionHandler('pause', () => { audio.pause(); playIcon.textContent = 'play_arrow'; });
            navigator.mediaSession.setActionHandler('nexttrack', () => playNextTrack());
            navigator.mediaSession.setActionHandler('previoustrack', () => {
                if (audio.currentTime > 3) {
                    audio.currentTime = 0;
                } else {
                    playPrevTrack();
                }
            });
            navigator.mediaSession.setActionHandler('seekbackward', (d) => { audio.currentTime = Math.max(0, audio.currentTime - (d.seekOffset || 10)); });
            navigator.mediaSession.setActionHandler('seekforward', (d) => { audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + (d.seekOffset || 10)); });
            navigator.mediaSession.setActionHandler('seekto', (d) => { audio.currentTime = d.seekTime; });
        }
    }

    function updateMediaSessionMetadata() {
        if ('mediaSession' in navigator) {
            const track = playerPlaylist[currentTrackIndex];
            if (!track) return;
            navigator.mediaSession.metadata = new MediaMetadata({
                title: track.title || 'Unknown Track',
                artist: track.artist || 'Unknown Artist',
                album: currentGenre || 'Cyber Radio',
                artwork: [{ src: 'favicon.svg', sizes: '512x512', type: 'image/svg+xml' }]
            });
        }
    }

    function updateMediaSessionPosition() {
        if ('mediaSession' in navigator && 'setPositionState' in navigator.mediaSession) {
            if (audio.duration && isFinite(audio.duration)) {
                navigator.mediaSession.setPositionState({
                    duration: audio.duration,
                    playbackRate: audio.playbackRate,
                    position: audio.currentTime
                });
            }
        }
    }

    // === BACKGROUND PLAYBACK ===
    function setupBackgroundPlayback() {
        document.addEventListener('visibilitychange', () => {
            if (document.hidden && !audio.paused && audioCtx?.state === 'suspended') {
                audioCtx.resume();
            }
        });
    }

    // === SEEK FUNCTIONALITY ===
    function setupSeekBar() {
        let isDragging = false;

        function getSeekPosition(e) {
            const rect = progressContainer.getBoundingClientRect();
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            let percent = (clientX - rect.left) / rect.width;
            return Math.max(0, Math.min(1, percent));
        }

        function updateSeekUI(percent) {
            progressEl.style.width = `${percent * 100}%`;
            progressHandle.style.left = `${percent * 100}%`;
            if (audio.duration && isFinite(audio.duration)) {
                currTimeEl.textContent = formatTime(percent * audio.duration);
            }
        }

        function startSeek(e) {
            if (!audio.duration || !isFinite(audio.duration)) return;
            isDragging = true;
            isSeeking = true;
            progressContainer.classList.add('seeking');
            const percent = getSeekPosition(e);
            updateSeekUI(percent);
            tg.HapticFeedback.impactOccurred('light');
        }

        function moveSeek(e) {
            if (!isDragging) return;
            e.preventDefault();
            const percent = getSeekPosition(e);
            updateSeekUI(percent);
        }

        function endSeek(e) {
            if (!isDragging) return;
            isDragging = false;
            isSeeking = false;
            progressContainer.classList.remove('seeking');
            const percent = getSeekPosition(e.changedTouches ? e.changedTouches[0] : e);
            if (audio.duration && isFinite(audio.duration)) {
                audio.currentTime = percent * audio.duration;
                updateMediaSessionPosition();
            }
            tg.HapticFeedback.impactOccurred('medium');
        }

        progressContainer.addEventListener('mousedown', startSeek);
        document.addEventListener('mousemove', moveSeek);
        document.addEventListener('mouseup', endSeek);
        progressContainer.addEventListener('touchstart', startSeek, { passive: false });
        document.addEventListener('touchmove', moveSeek, { passive: false });
        document.addEventListener('touchend', endSeek);
        progressContainer.addEventListener('click', (e) => {
            if (!audio.duration || !isFinite(audio.duration)) return;
            const percent = getSeekPosition(e);
            audio.currentTime = percent * audio.duration;
            updateMediaSessionPosition();
        });
    }

    // === GENRE DATABASE ===
    const GENRES = {
        pop: { name: "Pop", icon: "🎤", color: "#FF6B9D", subgenres: { modern: { name: "Modern Pop", search: "pop hits 2024", styles: "Dance Pop, Electropop, Synth Pop" }, classic: { name: "Classic Pop", search: "80s 90s pop hits", styles: "80s Pop, 90s Pop, Europop" }, kpop: { name: "K-Pop", search: "kpop hits", styles: "BTS, BLACKPINK, Korean Pop" }, latin: { name: "Latin Pop", search: "reggaeton latin hits", styles: "Reggaeton, Bachata, Latin Urban" }, indie: { name: "Indie Pop", search: "indie pop music", styles: "Bedroom Pop, Art Pop, Dream Pop" } } },
        hiphop: { name: "Hip-Hop", icon: "🎤", color: "#FFD93D", subgenres: { trap: { name: "Trap", search: "trap music hits", styles: "Modern Trap, Drill, Rage" }, oldschool: { name: "Old School", search: "90s hip hop classics", styles: "Boom Bap, Golden Age, G-Funk" }, melodic: { name: "Melodic Rap", search: "melodic rap", styles: "Trapsoul, Emo Rap, Melodic" }, underground: { name: "Underground", search: "underground hip hop", styles: "Conscious, Alternative, Lyrical" } } },
        electronic: { name: "Electronic", icon: "🎧", color: "#9B59B6", subgenres: { house: { name: "House", search: "house music", styles: "Deep House, Tech House, Future House" }, techno: { name: "Techno", search: "techno music", styles: "Minimal, Industrial, Detroit" }, edm: { name: "EDM", search: "edm bangers", styles: "Big Room, Future Bass, Dubstep" }, dnb: { name: "Drum & Bass", search: "drum and bass", styles: "Liquid, Jump Up, Neurofunk" }, trance: { name: "Trance", search: "trance music", styles: "Progressive, Uplifting, Psytrance" }, chill: { name: "Chill", search: "chillout lofi", styles: "Lo-Fi, Chillwave, Ambient" } } },
        rock: { name: "Rock", icon: "🎸", color: "#E74C3C", subgenres: { classic: { name: "Classic Rock", search: "classic rock hits", styles: "70s Rock, Arena Rock, Blues Rock" }, alternative: { name: "Alternative", search: "alternative rock", styles: "Indie Rock, Grunge, Post-Punk" }, metal: { name: "Metal", search: "heavy metal", styles: "Heavy, Thrash, Nu-Metal" }, punk: { name: "Punk", search: "punk rock", styles: "Pop Punk, Hardcore, Emo" } } },
        rnb: { name: "R&B / Soul", icon: "💜", color: "#8E44AD", subgenres: { modern: { name: "Modern R&B", search: "r&b hits 2024", styles: "Alternative R&B, Trapsoul, PBR&B" }, classic: { name: "Classic R&B", search: "90s r&b", styles: "New Jack Swing, Quiet Storm" }, soul: { name: "Soul", search: "soul music", styles: "Neo Soul, Motown, Northern Soul" }, funk: { name: "Funk", search: "funk music", styles: "P-Funk, Boogie, Electro Funk" } } },
        jazz: { name: "Jazz", icon: "🎷", color: "#3498DB", subgenres: { classic: { name: "Classic Jazz", search: "jazz classics", styles: "Bebop, Swing, Cool Jazz" }, modern: { name: "Modern Jazz", search: "modern jazz", styles: "Nu Jazz, Acid Jazz, Jazz Fusion" }, smooth: { name: "Smooth Jazz", search: "smooth jazz", styles: "Contemporary, Chill Jazz" } } },
        classical: { name: "Classical", icon: "🎻", color: "#2ECC71", subgenres: { orchestral: { name: "Orchestral", search: "orchestral classical", styles: "Romantic, Baroque, Symphony" }, piano: { name: "Piano", search: "classical piano", styles: "Chopin, Debussy, Modern Piano" }, cinematic: { name: "Cinematic", search: "epic orchestral music", styles: "Film Score, Trailer, Epic" } } },
        reggae: { name: "Reggae", icon: "🌴", color: "#27AE60", subgenres: { roots: { name: "Roots Reggae", search: "roots reggae", styles: "Bob Marley, Dub, Rocksteady" }, dancehall: { name: "Dancehall", search: "dancehall music", styles: "Modern Dancehall, Ragga" }, afrobeats: { name: "Afrobeats", search: "afrobeats hits", styles: "Afropop, Amapiano, Afroswing" } } },
        country: { name: "Country", icon: "🤠", color: "#D35400", subgenres: { modern: { name: "Modern Country", search: "country hits 2024", styles: "Country Pop, Bro Country" }, classic: { name: "Classic Country", search: "classic country", styles: "Outlaw, Honky Tonk, Bluegrass" } } },
        world: { name: "World", icon: "🌍", color: "#1ABC9C", subgenres: { arabic: { name: "Arabic", search: "arabic music", styles: "Arabic Pop, Rai, Khaleeji" }, indian: { name: "Indian", search: "bollywood hits", styles: "Bollywood, Punjabi, Indian Pop" }, asian: { name: "Asian", search: "japanese music jpop", styles: "J-Pop, C-Pop, City Pop" }, latin: { name: "Latin", search: "salsa cumbia", styles: "Salsa, Cumbia, Bossa Nova" } } }
    };
    const TRENDING = [ { name: "🔥 Viral TikTok", search: "tiktok viral hits 2024" }, { name: "📈 Top Charts", search: "top 50 hits 2024" }, { name: "🆕 New Releases", search: "new music 2024" }, { name: "💎 Best of 2024", search: "best songs 2024" } ];
    const DECADES = [ { name: "2020s", search: "2020s hits" }, { name: "2010s", search: "2010s hits" }, { name: "2000s", search: "2000s hits" }, { name: "90s", search: "90s hits" }, { name: "80s", search: "80s hits" }, { name: "70s", search: "70s hits" } ];
    const MOODS = [ { name: "😌 Chill", search: "chill relaxing music" }, { name: "🎉 Party", search: "party music hits" }, { name: "💪 Workout", search: "workout motivation music" }, { name: "😢 Sad", search: "sad songs" }, { name: "❤️ Romantic", search: "love songs romantic" }, { name: "📚 Focus", search: "study focus music" }, { name: "😴 Sleep", search: "sleep relaxation music" } ];

    // === UI & PLAYER LOGIC ===

    function initGenresUI() {
        const createChips = (container, items) => {
            items.forEach(item => {
                const chip = document.createElement('div');
                chip.className = 'chip';
                chip.textContent = item.name;
                chip.onclick = () => selectGenre(item.name, item.search);
                container.appendChild(chip);
            });
        };
        createChips(trendingChips, TRENDING);
        createChips(decadeChips, DECADES);
        createChips(moodChips, MOODS);

        Object.entries(GENRES).forEach(([key, genre]) => {
            const card = document.createElement('div');
            card.className = 'genre-card';
            card.style.setProperty('--card-color', genre.color);
            card.innerHTML = `<span class="genre-icon">${genre.icon}</span><span class="genre-name">${genre.name}</span><span class="genre-count">${Object.keys(genre.subgenres).length} styles</span>`;
            card.onclick = () => openSubgenres(key, genre);
            genreGrid.appendChild(card);
        });
    }

    function openSubgenres(key, genre) {
        drawerIcon.textContent = genre.icon;
        drawerTitle.textContent = genre.name;
        subgenreList.innerHTML = '';

        Object.entries(genre.subgenres).forEach(([subKey, sub]) => {
            const item = document.createElement('div');
            item.className = 'subgenre-item';
            item.innerHTML = `<span class="material-icons-round">play_circle</span><div class="subgenre-info"><div class="subgenre-name">${sub.name}</div><div class="subgenre-styles">${sub.styles}</div></div><span class="material-icons-round" style="opacity:0.3">chevron_right</span>`;
            item.onclick = () => {
                selectGenre(sub.name, sub.search);
                closeDrawers();
            };
            subgenreList.appendChild(item);
        });
        openDrawer(subgenreDrawer);
    }

    async function selectGenre(name, searchQuery) {
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

            playerPlaylist = data.playlist || [];
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
        }
        tg.HapticFeedback.impactOccurred('medium');
    }

    function playTrack(index) {
        if (index < 0 || index >= playerPlaylist.length) {
            playIcon.textContent = 'play_arrow';
            titleEl.textContent = "Playlist finished";
            artistEl.textContent = "Select a new genre";
            currentTrackIndex = -1;
            return;
        }

        currentTrackIndex = index;
        const track = playerPlaylist[index];

        titleEl.textContent = track.title || 'Unknown';
        artistEl.textContent = track.artist || 'Unknown';
        
        audio.crossOrigin = "anonymous";
        audio.src = `/audio/${track.identifier}`;
        
        initAudio();
        if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
        
        audio.play().catch(e => console.error("Play failed:", e));
        playIcon.textContent = 'pause';

        updateMediaSessionMetadata();
    }

    function playNextTrack() {
        playTrack(currentTrackIndex + 1);
    }

    function playPrevTrack() {
        playTrack(currentTrackIndex - 1);
    }

    // === SCREEN & DRAWER NAVIGATION ===
    const openGenresScreen = () => { screenPlayer.classList.add('slide-left'); screenGenres.classList.add('active'); tg.HapticFeedback.impactOccurred('light'); };
    const closeGenresScreen = () => { screenPlayer.classList.remove('slide-left'); screenGenres.classList.remove('active'); };
    const openDrawer = (drawer) => { drawer.classList.add('active'); overlay.classList.add('active'); };
    const closeDrawers = () => { subgenreDrawer.classList.remove('active'); playlistDrawer.classList.remove('active'); overlay.classList.remove('active'); };
    window.togglePlaylist = () => playlistDrawer.classList.contains('active') ? closeDrawers() : openDrawer(playlistDrawer);
    btnGenres.onclick = openGenresScreen;
    btnBackPlayer.onclick = closeGenresScreen;
    btnPlaylist.onclick = window.togglePlaylist;
    overlay.onclick = closeDrawers;

    genreSearch.oninput = (e) => {
        const query = e.target.value.toLowerCase();
        document.querySelectorAll('.genre-card').forEach(card => {
            card.querySelector('.genre-name').textContent.toLowerCase().includes(query)
                ? card.style.display = 'flex'
                : card.style.display = 'none';
        });
    };

    // === VISUALIZER ===
    function setupCanvas() { /* ... canvas setup logic ... */ }
    function initAudio() { /* ... audio context init logic ... */ }
    function animate() { /* ... animation logic ... */ }
    // (Assuming these functions are filled in from the previous version)

    // === PLAYER CONTROLS & EVENTS ===
    playBtn.onclick = () => {
        initAudio();
        if (audioCtx?.state === 'suspended') audioCtx.resume();
        audio.paused ? audio.play() : audio.pause();
        tg.HapticFeedback.impactOccurred('light');
    };

    nextBtn.onclick = () => { playNextTrack(); tg.HapticFeedback.impactOccurred('medium'); };
    prevBtn.onclick = () => {
        if (audio.currentTime > 3) {
            audio.currentTime = 0;
        } else {
            playPrevTrack();
        }
        tg.HapticFeedback.impactOccurred('medium');
    };

    rewindBtn.onclick = () => { audio.currentTime = Math.max(0, audio.currentTime - 10); updateMediaSessionPosition(); };
    forwardBtn.onclick = () => { if (audio.duration) audio.currentTime = Math.min(audio.duration, audio.currentTime + 10); updateMediaSessionPosition(); };
    playbackSpeed.onchange = () => { audio.playbackRate = parseFloat(playbackSpeed.value); updateMediaSessionPosition(); };

    audio.onplay = () => { playIcon.textContent = 'pause'; if (audioCtx?.state === 'suspended') audioCtx.resume(); updateMediaSessionMetadata(); };
    audio.onpause = () => playIcon.textContent = 'play_arrow';
    audio.onended = () => playNextTrack();
    audio.onloadedmetadata = () => updateMediaSessionPosition();

    audio.ontimeupdate = () => {
        if (isSeeking) return;
        if (audio.duration && isFinite(audio.duration)) {
            const percent = (audio.currentTime / audio.duration) * 100;
            progressEl.style.width = `${percent}%`;
            progressHandle.style.left = `${percent}%`;
            currTimeEl.textContent = formatTime(audio.currentTime);
            durTimeEl.textContent = formatTime(audio.duration);
        }
    };

    audio.onprogress = () => {
        if (audio.buffered.length > 0 && audio.duration) {
            const bufferedEnd = audio.buffered.end(audio.buffered.length - 1);
            progressBuffered.style.width = `${(bufferedEnd / audio.duration) * 100}%`;
        }
    };

    function formatTime(s) {
        if (!s || !isFinite(s)) return '0:00';
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return `${m}:${sec < 10 ? '0' + sec : sec}`;
    }

    // === INITIALIZATION ===
    initGenresUI();
    setupSeekBar();
    setupMediaSession();
    setupBackgroundPlayback();
    // Removed sync() and setInterval(sync, 2000)
});