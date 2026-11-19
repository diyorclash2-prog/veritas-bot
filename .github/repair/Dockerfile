FROM python:3.13-slim
RUN pip install --no-cache-dir 'python-telegram-bot[job-queue]==22.5' 'httpx==0.28.1' 'PyJWT[crypto]==2.15.1' 'Pillow==13.0.0' 'rlottie-python==1.3.8' 'imageio-ffmpeg==0.8.1'
ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
