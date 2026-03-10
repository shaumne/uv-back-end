# AWS EC2’de BlancMate API — Adım Adım Kurulum

Backend’i bir EC2 instance üzerinde çalıştırıp internete açmak için aşağıdaki adımları uygulayın.

---

## Ön gereksinimler

- AWS hesabı (ücretsiz tier kullanabilirsiniz)
- Bilgisayarınızda SSH client (Windows: PowerShell veya Git Bash; Mac/Linux: terminal)

---

## 1. EC2 instance oluşturma

### 1.1 AWS Console’a giriş

1. https://console.aws.amazon.com → **EC2** servisine gidin.
2. Sol menüden **Instances** → **Launch instance** tıklayın.

### 1.2 Instance ayarları

| Ayar | Önerilen değer |
|------|----------------|
| **Name** | `uv-dosimeter-api` (isterseniz başka isim) |
| **AMI** | **Ubuntu Server 22.04 LTS** |
| **Instance type** | **t2.micro** (Free tier uygun) veya **t3.small** (daha rahat) |
| **Key pair** | **Create new key pair** → İsim: `uv-api-key` → **.pem** indir → dosyayı güvenli yerde saklayın |
| **Network settings** | **Create security group** seçili kalsın |

### 1.3 Security group (gelen trafik)

**Inbound security group rules** kısmında şunlar olsun:

| Type   | Port | Source    | Açıklama        |
|--------|------|-----------|-----------------|
| SSH    | 22   | My IP     | Sunucuya bağlanmak |
| HTTP   | 80   | 0.0.0.0/0 | Tarayıcı / mobil API |
| Custom | 8000 | 0.0.0.0/0 | İsteğe bağlı; uvicorn doğrudan test |

**Launch instance** ile instance’ı başlatın.

---

## 2. Instance’a bağlanma (SSH)

### 2.1 Public IP / DNS

- **EC2** → **Instances** → instance’ınızı seçin.
- **Public IPv4 address** (veya **Public IPv4 DNS**) değerini kopyalayın, örn: `3.12.34.56` veya `ec2-3-12-34-56.eu-central-1.compute.amazonaws.com`.

### 2.2 SSH ile giriş

**.pem** dosyasının bulunduğu klasörde (Windows’ta Git Bash veya PowerShell):

```bash
# .pem dosyasına sadece sizin okuma izniniz olmalı (Linux/Mac)
chmod 400 uv-api-key.pem

# Bağlan (ubuntu kullanıcısı — Ubuntu AMI varsayılanı)
ssh -i uv-api-key.pem ubuntu@PUBLIC_IP
```

`PUBLIC_IP` yerine kopyaladığınız IP veya DNS’i yazın. İlk seferde “Are you sure?” sorusunda `yes` deyin.

Başarılı olunca `ubuntu@ip-172-31-...` gibi bir prompt görürsünüz.

---

## 3. Sunucuda güncelleme ve gerekli paketler

SSH ile bağlıyken:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv python3-dev git
```

---

## 4. Projeyi sunucuya alma

### Seçenek A: GitHub’dan (tercih edilen)

```bash
cd ~
git clone https://github.com/KULLANICI/REPO_ADI.git
cd REPO_ADI/uv_dosimeter/backend
```

`KULLANICI` ve `REPO_ADI` yerine kendi GitHub kullanıcı adınız ve repo adınızı yazın. Repo private ise token veya SSH key kullanmanız gerekir.

### Seçenek B: Bilgisayarınızdan SCP ile yükleme

Kendi bilgisayarınızda (backend klasörünün bir üst dizininde):

```bash
scp -i uv-api-key.pem -r uv_dosimeter ubuntu@PUBLIC_IP:~
```

Sunucuda:

```bash
cd ~/uv_dosimeter/backend
```

---

## 5. Python sanal ortam ve bağımlılıklar

Sunucuda, **backend** dizininde:

```bash
cd ~/REPO_ADI/uv_dosimeter/backend   # veya ~/uv_dosimeter/backend

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

Kurulum birkaç dakika sürebilir (opencv, numpy, scipy).

---

## 6. Ortam değişkenleri (isteğe bağlı)

Production için CORS ve API key ayarlamak isterseniz:

```bash
nano .env
```

Örnek içerik:

```env
DEBUG=false
ALLOWED_ORIGINS=https://your-flutter-app.com,*
API_KEY=güçlü_bir_gizli_anahtar
```

Kaydet: `Ctrl+O`, Enter, `Ctrl+X`.

---

## 7. Uygulamayı çalıştırma (test)

Önce tek seferlik manuel test:

```bash
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Tarayıcıda: `http://PUBLIC_IP:8000/health` → `{"status":"ok",...}` görmelisiniz.  
Bitirmek için: `Ctrl+C`.

---

## 8. Sürekli çalışması için systemd servisi

Sunucuda SSH ile:

```bash
sudo nano /etc/systemd/system/uv-dosimeter-api.service
```

Aşağıdaki içeriği yapıştırın. **Yolları** kendi proje dizininize göre düzeltin (örn. `uv_dosimeter` veya repo adı):

```ini
[Unit]
Description=BlancMate FastAPI
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/uv_dosimeter/backend
Environment="PATH=/home/ubuntu/uv_dosimeter/backend/venv/bin"
ExecStart=/home/ubuntu/uv_dosimeter/backend/venv/bin/gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- `WorkingDirectory` ve `Environment` / `ExecStart` içindeki **/home/ubuntu/uv_dosimeter/backend** kısmını kendi yolunuza göre değiştirin (örn. `/home/ubuntu/REPO_ADI/uv_dosimeter/backend`).

Kaydedin (`Ctrl+O`, Enter, `Ctrl+X`), sonra:

```bash
sudo systemctl daemon-reload
sudo systemctl enable uv-dosimeter-api
sudo systemctl start uv-dosimeter-api
sudo systemctl status uv-dosimeter-api
```

`active (running)` görünmeli. Log için:

```bash
sudo journalctl -u uv-dosimeter-api -f
```

(`Ctrl+C` ile çıkarsınız.)

---

## 9. (İsteğe bağlı) Nginx ile 80 portunda yayın

API’yi 80 portunda (http://PUBLIC_IP/) vermek ve ileride HTTPS eklemek için:

```bash
sudo apt install -y nginx
sudo nano /etc/nginx/sites-available/uv-api
```

İçerik:

```nginx
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 10M;
    }
}
```

Aktifleştirip yeniden başlatın:

```bash
sudo ln -sf /etc/nginx/sites-available/uv-api /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

Artık **http://PUBLIC_IP/health** ve **http://PUBLIC_IP/api/v1/...** çalışır.

---

## 10. API adresini Flutter’da kullanma

- Nginx kullandıysanız: `http://PUBLIC_IP` veya `http://EC2_DNS`
- Nginx yoksa: `http://PUBLIC_IP:8000`

Flutter tarafında base URL’i bu adrese göre ayarlayın (env veya config).

---

## Özet komut listesi (tek sayfa)

```bash
# 1) SSH
ssh -i uv-api-key.pem ubuntu@PUBLIC_IP

# 2) Güncelleme + Python/git
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv python3-dev git

# 3) Proje (GitHub örneği)
cd ~ && git clone https://github.com/KULLANICI/REPO.git && cd REPO/uv_dosimeter/backend

# 4) Venv + requirements
python3 -m venv venv && source venv/bin/activate
pip install --upgrade pip && pip install -r requirements.txt

# 5) Test
uvicorn app.main:app --host 0.0.0.0 --port 8000
# Tarayıcı: http://PUBLIC_IP:8000/health

# 6) Systemd servisi (yolları kendi dizininize göre düzenleyin)
sudo nano /etc/systemd/system/uv-dosimeter-api.service
# ... içeriği yapıştır, WorkingDirectory/ExecStart yollarını düzelt ...
sudo systemctl daemon-reload && sudo systemctl enable uv-dosimeter-api && sudo systemctl start uv-dosimeter-api
```

---

## Güvenlik notları

- **.pem** dosyasını kimseyle paylaşmayın; GitHub’a koymayın.
- Production’da **API_KEY** kullanın ve Flutter’da header’da gönderin.
- İleride HTTPS için **Let’s Encrypt** (certbot) + Nginx kullanabilirsiniz.
- Mümkünse **ALLOWED_ORIGINS**’i kendi domain’inize kısıtlayın.

Bu adımlarla API’niz EC2 üzerinde sürekli çalışır ve internete açık olur.
