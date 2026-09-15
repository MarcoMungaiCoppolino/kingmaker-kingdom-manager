# Kingmaker Kingdom Manager — container image.
#
# UNTESTED: the author runs the app on Windows with `python launch.py` and has
# not built this image. It is here as a starting point for whoever wants to
# self-host; read the "Hosting and security" section of the README first.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "Pillow>=10,<12"
COPY . .

# The game and the images live outside the image: mount them as volumes.
ENV KINGMAKER_HOST=0.0.0.0 \
    KINGMAKER_PORT=8080 \
    KINGMAKER_DATA_DIR=/data/saves \
    KINGMAKER_ASSETS_DIR=/data/assets
VOLUME ["/data/saves", "/data/assets"]
EXPOSE 8080

CMD ["python", "launch.py", "--no-browser"]
