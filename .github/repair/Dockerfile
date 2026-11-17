FROM python:3.13-slim
RUN pip install --no-cache-dir 'python-telegram-bot[job-queue]==22.5' 'httpx==0.28.1' 'PyJWT[crypto]==2.15.1'
ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
