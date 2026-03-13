apt-get update
apt-get install -y xvfb xauth

pip install -r requirements.txt
playwright install --with-deps chromium

xvfb-run python insta.pyapt-get update
apt-get install -y xvfb

playwright install chromium

xvfb-run python insta.py
