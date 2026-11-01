# WorldLab server for Hugging Face Spaces (Docker SDK), Render, or any container host.
FROM python:3.11-slim
RUN useradd -m -u 1000 app
WORKDIR /home/app/worldlab
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app worldlab ./worldlab
USER app
# Accounts and runs live in WORLDLAB_DATA. On Hugging Face, turn on persistent storage and set it to /data
# so accounts survive restarts. WORLDLAB_ALLOWED_ORIGINS lists the sites (GitHub Pages) allowed to call the API. Set MODEL_API_KEY as a secret to let Muse Spark run the farm.
ENV PYTHONUNBUFFERED=1 \
    WORLDLAB_DATA=/tmp/worldlab \
    WORLDLAB_SECURE_COOKIES=1 \
    WORLDLAB_COOKIE_SAMESITE=None \
    WORLDLAB_MAX_RUNS=3 \
    WORLDLAB_TRUST_PROXY=1 \
    WORLDLAB_ALLOWED_ORIGINS=https://moamryehia.github.io
EXPOSE 7860
# PORT is set by hosts such as Render, Railway or Cloud Run; Hugging Face uses 7860.
CMD ["sh", "-c", "exec python -m worldlab serve --host 0.0.0.0 --http-port ${PORT:-7860}"]
