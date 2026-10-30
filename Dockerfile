FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# bake the speech model into the image so jobs don't wait for a download
ENV HF_HOME=/opt/hf-cache
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')" \
    && chmod -R a+rX /opt/hf-cache
COPY . .
# Hugging Face Spaces runs the container as a non-root user; /tmp is writable
ENV DATA_DIR=/tmp/reelcut
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
