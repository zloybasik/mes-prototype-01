# mes-prototype-01

**ОС:** CentOS Stream 9
**Технологии:** Docker, Nginx, FastAPI, RabbitMQ


## Структура проекта

src/
└── mes-prototype/
├── docker-compose.yml
├── fastapi/
└── nginx/


## Открытые порты

- **80** — HTTP (Nginx, проксирует запросы к FastAPI)
- **8000** — FastAPI (доступен только внутри Docker-сети)
- **15672** — Web-интерфейс RabbitMQ (RabbitMQ Management UI)
- **5672** — RabbitMQ (для приложений/клиентов)


## Хосты для доступа

- **API и веб-интерфейс:**
  http://localhost/
  http://<IP_сервера>/

- **Swagger-документация FastAPI:**
  http://localhost/docs

- **RabbitMQ Management UI:**
  http://localhost:15672 
  (логин/пароль: guest/guest)
