import os

bind = "0.0.0.0:8000"
workers = int(os.getenv("WEB_CONCURRENCY", "3"))
threads = int(os.getenv("GUNICORN_THREADS", "2"))
worker_class = "gthread"
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "100"))
accesslog = "-"
errorlog = "-"
capture_output = True

# Gunicorn internetga publish qilinmaydi; unga faqat Docker networkdagi Nginx ulanadi.
# Shu sababli Nginx yuborgan X-Forwarded-Proto ni barcha ichki proxy IPlaridan qabul qilamiz.
forwarded_allow_ips = "*"
