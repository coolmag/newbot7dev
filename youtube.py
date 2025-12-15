    async def search(
        self,
        query: str,
        limit: int = 30,
        **kwargs,
    ) -> List[TrackInfo]:
        """
        Поиск с агрессивной фильтрацией нарезок и топов.
        """
        # Минус-слова для YouTube
        clean_query = f'{query} -live -radio -stream -24/7 -"10 hours" -"top 10" -"top 5" -"best of"'
        search_query = f"ytsearch{limit * 2}:{clean_query}"
        opts = self._get_opts(is_search=True)

        try:
            info = await self._extract_info(search_query, opts, download=False)
            entries = info.get("entries", []) or []

            out: List[TrackInfo] = []
            
            # РАСШИРЕННЫЙ СПИСОК МУСОРА
            BANNED = [
                # Технические
                '10 hours', '1 hour', 'mix 20', 'full album', 'playlist', 
                'compilation', 'live', 'stream', '24/7',
                # Нарезки и топы (ЭТО ВАЖНО)
                'top 10', 'top 5', 'top 20', 'top 50', 'top 100', 
                'best of', 'greatest hits', 'collection', 'mashup',
                'minimix', 'megamix', 'medley', 'intro', 'outro', 'teaser',
                'preview', 'trailer'
            ]

            for e in entries:
                if not e or not e.get("id"): continue
                if e.get("is_live"): continue

                title = e.get("title", "").lower()
                
                # Фильтр по названию
                if any(b in title for b in BANNED):
                    # Если юзер сам попросил "mix", то разрешаем миксы, но не топы
                    if "mix" in query.lower() and "top" not in title:
                        pass 
                    else:
                        continue

                duration = int(e.get("duration") or 0)
                # Фильтр длительности:
                # < 2 мин — часто обрезки или интро
                # > 10 мин — часто миксы
                if duration == 0: continue
                if duration > 600: continue # Строго < 10 мин
                if duration < 120: continue # Строго > 2 мин (чтобы не качать огрызки)

                out.append(
                    TrackInfo(
                        title=e.get("title", "Unknown"),
                        artist=e.get("channel") or e.get("uploader") or "Unknown",
                        duration=duration,
                        source=Source.YOUTUBE.value,
                        identifier=e["id"],
                    )
                )
                if len(out) >= limit: break
            return out

        except Exception as e:
            logger.error(f"Search error: {e}")
            return []