import httpx


class HttpClientManager:
    def __init__(self):
        # self. делает переменную свойством объекта, она не пропадет
        self.api_client: httpx.AsyncClient = None


# Создаем ОДИН экземпляр менеджера на все приложение
manager = HttpClientManager()


def get_http_client() -> httpx.AsyncClient:
    """Функция возвращает САМ httpx.AsyncClient для удобства"""
    return manager.api_client
