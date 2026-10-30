# Paste this into your Hugging Face Space as "Dockerfile".
# It pulls the ReelCut code from GitHub, so the Space only needs this file and README.md.
# To update the app later: Space Settings -> "Factory rebuild".
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
ARG REPO=https://github.com/Eshwin6/reelcut
RUN git clone --depth 1 "$REPO" /srv
WORKDIR /srv
RUN pip install --no-cache-dir -r requirements.txt
ENV HF_HOME=/opt/hf-cache
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" \
    && chmod -R a+rX /opt/hf-cache
ENV DATA_DIR=/tmp/reelcut
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
