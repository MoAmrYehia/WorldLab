# WorldLab web app for Hugging Face Spaces (Docker SDK) or any container host.
FROM python:3.11-slim
RUN useradd -m -u 1000 app
WORKDIR /home/app/worldlab
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app worldlab ./worldlab
USER app
ENV PYTHONUNBUFFERED=1
EXPOSE 7860
# Set MODEL_API_KEY as a Space secret to run Muse Spark; without it the scripted scientist runs.
CMD ["python", "-m", "worldlab", "serve", "--host", "0.0.0.0", "--http-port", "7860", "--runs-dir", "/tmp/runs"]
