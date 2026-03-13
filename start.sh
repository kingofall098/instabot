apt-get update
apt-get install -y xvfb

playwright install chromium

xvfb-run python insta.py
