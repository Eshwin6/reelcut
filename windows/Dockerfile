FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg fonts-noto-color-emoji && rm -rf /var/lib/apt/lists/*
# changes on every setup/update run so the latest code is pulled instead of a cached copy
ARG CACHEBUST=1
RUN git clone --depth 1 https://github.com/Eshwin6/reelcut /srv
WORKDIR /srv
RUN pip install --no-cache-dir -r requirements.txt
ENV HF_HOME=/opt/hf-cache
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" && chmod -R 777 /opt/hf-cache
ENV DATA_DIR=/data
VOLUME /data
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
