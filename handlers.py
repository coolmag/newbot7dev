    async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        try: await query.answer()
        except: pass
        
        data = query.data
        chat_id = query.message.chat_id
        chat_type = query.message.chat.type

        # 1. Главное меню
        if data == "main_menu":
            await query.edit_message_text(
                "💿 *Каталог:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_menu_keyboard()
            )
        
        # 2. Папки (cat|HASH)
        elif data.startswith("cat|"):
            path_hash = data.removeprefix("cat|")
            path_str = resolve_path(path_hash) # <--- ВОТ ТУТ ВАЖНО
            
            if not path_str:
                # Если хэш протух (после перезагрузки бота), возвращаем в меню
                await query.edit_message_text("⚠️ Меню обновлено.", reply_markup=get_main_menu_keyboard())
                return

            folder_name = path_str.split('|')[-1]
            await query.edit_message_text(
                f"📂 *{folder_name}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_subcategory_keyboard(path_str)
            )

        # 3. Play (play|HASH)
        elif data.startswith("play|"):
            path_hash = data.removeprefix("play|")
            path_str = resolve_path(path_hash)
            
            if not path_str:
                await query.edit_message_text("⚠️ Ошибка. Выберите заново.", reply_markup=get_main_menu_keyboard())
                return

            # Ищем запрос в каталоге
            # (Функция get_query_from_catalog должна быть внутри handlers.py или импортирована)
            def get_query_recursive(path_parts, current_level):
                if not path_parts: return current_level
                return get_query_recursive(path_parts[1:], current_level.get(path_parts[0], {}))

            parts = path_str.split('|')
            search_query = get_query_recursive(parts, settings.MUSIC_CATALOG)
            
            if isinstance(search_query, dict):
                # Это папка, а не трек! Ошибка логики. Открываем как папку.
                await query.edit_message_text(f"📂 {parts[-1]}", reply_markup=get_subcategory_keyboard(path_str))
                return

            await query.message.delete()
            await radio.start(chat_id, str(search_query), chat_type)