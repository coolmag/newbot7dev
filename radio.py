    async def _radio_loop(self, s: RadioSession):
        try:
            while not s.stop_event.is_set():
                s.skip_event.clear()

                # 1. Пополнение плейлиста
                if len(s.playlist) < 2:
                    await self._update_dashboard(s, status="📡 Поиск новых треков...")
                    await self._fetch_playlist(s)

                if not s.playlist:
                    await asyncio.sleep(5)
                    continue

                # 2. Берем следующий трек
                track = s.playlist.popleft()
                s.current = track
                s.played_ids.add(track.identifier)
                
                await self._update_dashboard(s, status=f"⬇️ Загрузка: {track.title}...")

                # 3. СКАЧИВАНИЕ (с тайм-аутом)
                try:
                    # Даем на скачивание 40 секунд из наших 90, чтобы оставить время на проигрывание
                    result = await asyncio.wait_for(
                        self._downloader.download_with_retry(track.identifier),
                        timeout=40.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[{s.chat_id}] Download timeout for {track.identifier}")
                    continue

                if not result or not result.success:
                    logger.warning(f"[{s.chat_id}] Download failed: {result.error}")
                    continue

                s.audio_file_path = Path(result.file_path)

                # 4. ОТПРАВКА В ЧАТ
                try:
                    with open(s.audio_file_path, 'rb') as f:
                        await self._bot.send_audio(
                            chat_id=s.chat_id,
                            audio=f,
                            caption=f"🎧 *{track.title}*\n👤 {track.artist}",
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=get_track_keyboard(track.identifier)
                        )
                    await self._update_dashboard(s, status="▶️ Сейчас в эфире")
                except Exception as e:
                    logger.error(f"[{s.chat_id}] Send audio error: {e}")

                # 5. ГЛАВНОЕ: ОЖИДАНИЕ 90 СЕКУНД (Цикл переключения)
                try:
                    # Бот спит 90 секунд ИЛИ пока не нажмут кнопку "Skip" (skip_event)
                    await asyncio.wait_for(s.skip_event.wait(), timeout=90.0)
                    logger.info(f"[{s.chat_id}] Track skipped by user")
                except asyncio.TimeoutError:
                    # 90 секунд прошло, идем на следующий круг
                    logger.info(f"[{s.chat_id}] 90s interval reached, next track...")

                # Удаляем старый файл, чтобы не забивать диск Railway
                if s.audio_file_path and s.audio_file_path.exists():
                    try: s.audio_file_path.unlink()
                    except: pass

        except asyncio.CancelledError:
            logger.info(f"[{s.chat_id}] Radio loop cancelled")
        except Exception as e:
            logger.error(f"[{s.chat_id}] Critical radio loop error: {e}", exc_info=True)
        finally:
            await self.stop(s.chat_id)
