# EC2 Kurulumu — shaumne/uv-back-end (Sizin Bilgilerinizle)

**Repo:** https://github.com/shaumne/uv-back-end (backend doğrudan repo kökünde)  
**EC2:** 16.170.120.34 (eu-north-1)  
**DNS:** ec2-16-170-120-34.eu-north-1.compute.amazonaws.com  
**Pem:** `uv.pem` (proje klasöründe veya d:\uv\uv.pem)

---

## Adım 1 — Bilgisayarınızdan SSH ile bağlanın

PowerShell veya Git Bash’i açın. `uv.pem` dosyasının olduğu klasöre gidin (örn. `d:\uv`):

```powershell
cd d:\uv
```

Windows’ta .pem izni (Git Bash’te):

```bash
icacls uv.pem /inheritance:r
icacls uv.pem /grant:r "%USERNAME%:R"
```

Bağlanın:

```bash
ssh -i uv.pem ubuntu@16.170.120.34
```

İlk seferde `Are you sure you want to continue connecting?` → `yes` yazın.  
Başarılı olunca `ubuntu@ip-172-31-28-24:~$` benzeri bir prompt görürsünüz.

---

## Adım 2 — Sunucuda tek seferde kurulum scripti

SSH ile bağlıyken aşağıdaki **tüm bloğu** kopyalayıp terminale yapıştırın (Enter). Tek seferde güncelleme, git, clone, venv, requirements ve systemd servisini kurar.

```bash
set -e
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv python3-dev git libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1

cd ~
if [ -d uv-back-end ]; then cd uv-back-end && git pull; else git clone https://github.com/shaumne/uv-back-end.git && cd uv-back-end; fi

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

sudo tee /etc/systemd/system/uv-dosimeter-api.service > /dev/null << 'EOF'
[Unit]
Description=UV Dosimeter FastAPI (uv-back-end)
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/uv-back-end
Environment="PATH=/home/ubuntu/uv-back-end/venv/bin"
ExecStart=/home/ubuntu/uv-back-end/venv/bin/python -m gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable uv-dosimeter-api
sudo systemctl start uv-dosimeter-api
sudo systemctl status uv-dosimeter-api
```

Çıktıda **active (running)** görmelisiniz. Hata varsa:

```bash
sudo journalctl -u uv-dosimeter-api -n 50 --no-pager
```

---

## Adım 3 — Test

Tarayıcıda açın:

- **http://16.170.120.34:8000/health**  
  veya  
- **http://ec2-16-170-120-34.eu-north-1.compute.amazonaws.com:8000/health**

Beklenen: `{"status":"ok","version":"1.0.0"}`

Flutter’da base URL olarak kullanın:

- `http://16.170.120.34:8000`  
  veya  
- `http://ec2-16-170-120-34.eu-north-1.compute.amazonaws.com:8000`

---

## Güvenlik grubu kontrolü

EC2’de **8000** portu açık değilse API erişilmez. AWS Console → **EC2** → **Security Groups** → instance’ınızın grubunda **Inbound rules**:

| Type   | Port | Source    |
|--------|------|-----------|
| SSH    | 22   | My IP     |
| Custom TCP | 8000 | 0.0.0.0/0 |
| HTTP   | 80   | 0.0.0.0/0 (isteğe bağlı) |

Kaydedin.

---

## Sonraki güncellemeler (kod değişince)

SSH ile bağlanıp:

```bash
cd ~/uv-back-end
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart uv-dosimeter-api
```

---

## Hata: status=203/EXEC (Main process exited)

Bu hata **ExecStart** satırındaki çalıştırılabilirin bulunamadığı anlamına gelir. Servisi **python -m gunicorn** ile çalışacak şekilde güncelleyin.

**Sunucuda (SSH ile bağlıyken) şunu çalıştırın:**

```bash
sudo tee /etc/systemd/system/uv-dosimeter-api.service > /dev/null << 'EOF'
[Unit]
Description=UV Dosimeter FastAPI (uv-back-end)
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/uv-back-end
Environment="PATH=/home/ubuntu/uv-back-end/venv/bin"
ExecStart=/home/ubuntu/uv-back-end/venv/bin/python -m gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl restart uv-dosimeter-api
sudo systemctl status uv-dosimeter-api
```

`active (running)` görünmeli. Hâlâ 203 alırsanız venv yolunu kontrol edin:

```bash
ls -la /home/ubuntu/uv-back-end/venv/bin/python
/home/ubuntu/uv-back-end/venv/bin/python -m gunicorn --version
```

---

## Hata: libGL.so.1: cannot open shared object file (OpenCV)

OpenCV sunucuda GUI/OpenGL kütüphanesi arıyor. Aşağıdakileri **sırayla** deneyin.

### 1) Ubuntu 22.04 — libGL ve bağımlılıklar

```bash
sudo apt update
sudo apt install -y libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1
sudo systemctl restart uv-dosimeter-api
sudo systemctl status uv-dosimeter-api
```

### 2) Hâlâ aynı hata varsa — opencv-python-headless kullanın

Sunucuda GUI yok; `opencv-python-headless` kullanmak daha uygundur. Repo’da `requirements.txt` içinde `opencv-python-headless` olduğundan emin olun. Eğer `opencv-python` (GUI’li) yüklüyse kaldırıp headless kurun:

```bash
cd ~/uv-back-end
source venv/bin/activate
pip uninstall -y opencv-python opencv-python-headless 2>/dev/null
pip install opencv-python-headless
sudo systemctl restart uv-dosimeter-api
sudo systemctl status uv-dosimeter-api
```

---

## Hata: ModuleNotFoundError: No module named 'pydantic_settings'

Eksik Python paketi. Venv içinde requirements’ı tekrar kurun:

```bash
cd ~/uv-back-end
source venv/bin/activate
pip install pydantic-settings
pip install -r requirements.txt
sudo systemctl restart uv-dosimeter-api
sudo systemctl status uv-dosimeter-api
```

GitHub repo’daki `requirements.txt` içinde `pydantic-settings` satırı olmalı; yoksa ekleyip `pip install -r requirements.txt` çalıştırın.

---

## Özet

1. `ssh -i uv.pem ubuntu@16.170.120.34` ile bağlanın.  
2. Yukarıdaki **Adım 2**’deki scripti sunucuda tek blok olarak çalıştırın.  
3. Tarayıcıda `http://16.170.120.34:8000/health` ile test edin.

Bu dosya sizin IP, DNS ve repo’nuz (shaumne/uv-back-end) ile uyumludur.
