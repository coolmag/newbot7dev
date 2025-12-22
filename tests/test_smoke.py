
import pytest
import httpx

# Используем маркер anyio и явно указываем бэкенд, чтобы избежать запуска тестов на 'trio'
pytestmark = pytest.mark.anyio(backend='asyncio')


async def test_health_check(client: httpx.AsyncClient):
    """
    Проверяет, что базовый эндпоинт /api/health работает и возвращает корректный ответ.
    Фикстура 'client' из conftest.py автоматически обрабатывает запуск приложения с тестовыми настройками.
    """
    response = await client.get("/api/health")
    
    # Проверяем, что запрос прошел успешно
    assert response.status_code == 200
    
    # Проверяем содержимое ответа
    assert response.json() == {"ok": True}
