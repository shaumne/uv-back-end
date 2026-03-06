# PythonAnywhere’da UV Dosimeter API’yi Yayınlama (Adım Adım)

Test için backend’i ücretsiz PythonAnywhere hesabında çalıştırmak için aşağıdaki adımları uygulayın.

---

## 1. Hesap açma

1. Tarayıcıda **https://www.pythonanywhere.com** adresine gidin.
2. **Pricing & signup** → **Create a Beginner account** (ücretsiz).
3. E-posta ve şifre ile kayıt olun; e-postayı doğrulayın.

---

## 2. Projeyi PythonAnywhere’a taşıma

### Seçenek A: GitHub’dan (tercih edilen)

1. Backend’i GitHub’a pushladıysanız:
   - **Dashboard** → **Consoles** → **$ Bash** ile yeni konsol açın.
2. Ev dizinine gidip repoyu klonlayın (örnek kullanıcı adı: `uvdosimetry`):

   ```bash
   cd ~
   git clone https://github.com/KULLANICI/REPO_ADI.git
   cd REPO_ADI/uv_dosimeter/backend
   ```

   Proje yapınız farklıysa `REPO_ADI` ve `uv_dosimeter/backend` kısmını kendi yolunuza göre değiştirin.

### Seçenek B: Dosya yükleme

1. Bilgisayarınızda `uv_dosimeter/backend` klasörünü zip’leyin (içinde `app/`, `requirements.txt`, `wsgi.py` olsun).
2. **Dashboard** → **Files** → **Upload a file** ile zip’i yükleyin.
3. **$ Bash** konsolunda:

   ```bash
   cd ~
   unzip backend.zip -d backend
   cd backend
   ```

---

## 3. Sanal ortam ve bağımlılıklar

Bash konsolunda (proje dizininde, örn. `~/REPO_ADI/uv_dosimeter/backend` veya `~/backend`):

```bash
# Sanal ortam oluştur
python3.10 -m venv venv

# Aktif et
source venv/bin/activate

# Bağımlılıkları kur (opencv vb. birkaç dakika sürebilir)
pip install --upgrade pip
pip install -r requirements.txt
```

PythonAnywhere’da genelde **Python 3.10** kullanılır. Başka sürüm isterseniz `python3.10` yerine `python3.9` vb. yazabilirsiniz; Web app’te de aynı sürümü seçeceksiniz.

---

## 4. Web uygulaması oluşturma

1. Üst menüden **Web** sekmesine gidin.
2. **Add a new web app** → **Next** → **Manual configuration** → **Python 3.10** (veya kullandığınız sürüm) → **Next**.
3. **Domain:** Varsayılan `kullaniciadi.pythonanywhere.com` kalabilir.

---

## 5. WSGI ayarları

1. **Web** sayfasında **Code** bölümüne inin.
2. **WSGI configuration file** satırındaki linke (örn. `/var/www/kullaniciadi_pythonanywhere_com_wsgi.py`) tıklayın.
3. Açılan dosyadaki her şeyi silin ve aşağıdaki içeriği yapıştırın (yolları kendi kullanıcı adınıza göre düzeltin):

```python
# Kullanıcı adınızı buraya yazın (örn. uvdosimetry)
import sys
username = "KULLANICI_ADINIZ"

# Proje dizini: backend klasörünün tam yolu
project_home = f"/home/{username}/REPO_ADI/uv_dosimeter/backend"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Sanal ortam (Web sekmesinde "Virtualenv" ile de ayarlanabilir)
# activate_this = f"/home/{username}/.virtualenvs/venv/bin/activate_this.py"
# exec(open(activate_this).read(), {"__file__": activate_this})

# WSGI uygulaması
from wsgi import application
```

- `KULLANICI_ADINIZ`: PythonAnywhere giriş adınız.
- `REPO_ADI`: Repo veya zip’i açtığınız klasör adı (örn. `uv_dosimeter` veya `backend`).
- Backend’i doğrudan `~/backend` içine açtıysanız: `project_home = f"/home/{username}/backend"` yapın.

Dosyayı **Save** edin.

---

## 6. Virtualenv’i Web app’e bağlama

1. **Web** sekmesinde **Virtualenv** bölümüne inin.
2. **Enter path to a virtualenv** kutusuna şunu yazın (kullanıcı adınızı ve proje yolunu değiştirin):

   ```
   /home/KULLANICI_ADINIZ/REPO_ADINIZ/uv_dosimeter/backend/venv
   ```

   veya backend doğrudan `~/backend` ise:

   ```
   /home/KULLANICI_ADINIZ/backend/venv
   ```

3. Yeşil tik çıkınca virtualenv bağlanmış demektir.

---

## 7. Ortam değişkenleri (isteğe bağlı)

API key veya CORS için:

1. **Web** sekmesinde **Code** bölümündeki **WSGI configuration file** dosyasını tekrar açın.
2. `from wsgi import application` satırından **önce** şunları ekleyebilirsiniz:

```python
import os
os.environ["DEBUG"] = "false"
os.environ["ALLOWED_ORIGINS"] = "*"   # Test için; production’da domain yazın
# os.environ["API_KEY"] = "gizli_anahtar"  # İsterseniz açın
```

Sonra yine `from wsgi import application` ile bitmeli.

---

## 8. Uygulamayı başlatma

1. **Web** sekmesinde en üstteki yeşil **Reload** butonuna tıklayın.
2. Sayfayı yenileyip **Errors** kısmına bakın; hata varsa log’u okuyup yolu veya WSGI dosyasını düzeltin.

---

## 9. Test etme

- Tarayıcıda: `https://KULLANICI_ADINIZ.pythonanywhere.com/health`
- Beklenen: `{"status":"ok","version":"1.0.0"}`

API base URL (Flutter’da kullanacağınız):

```
https://KULLANICI_ADINIZ.pythonanywhere.com
```

- Analyze: `POST https://KULLANICI_ADINIZ.pythonanywhere.com/api/v1/analyze`
- Detect: `POST https://KULLANICI_ADINIZ.pythonanywhere.com/api/v1/detect`
- Dokümantasyon (DEBUG=true ise): `https://KULLANICI_ADINIZ.pythonanywhere.com/docs`

---

## "Unhandled Exception" veya site açılmıyor — ilk adım: Error log

1. **Web** sekmesine gidin.
2. **Log files** bölümünde **Error log** satırındaki linke tıklayın (örn. `kullaniciadi.pythonanywhere.com.error.log`).
3. **En alttaki satırlara** bakın; orada gerçek hata mesajı (ör. `ImportError`, `ModuleNotFoundError`) ve traceback olur.

Örnek hata:
```text
ImportError: No module named 'a2wsgi'
```
veya
```text
ImportError: No module named 'app'
```

Aşağıdaki tabloda bu hatalara göre ne yapacağınız yazıyor. WSGI dosyasını aşağıdaki **“Güvenilir WSGI örneği”** ile değiştirirseniz birçok sorun çözülür (virtualenv dahili aktive, yol tek yerde).

---

## Sık karşılaşılan hatalar

| Hata (log’ta görünen) | Çözüm |
|------------------------|--------|
| **ImportError: No module named 'app'** | `project_home` yanlış. Bash’te `cd ~` → `find . -name wsgi.py` ile `wsgi.py` yolunu bulun; `project_home` = bu dosyanın bulunduğu klasör (örn. `/home/user/backend`). |
| **ImportError: No module named 'a2wsgi'** | Virtualenv yüklenmemiş. Aşağıdaki **“Güvenilir WSGI örneği”**ni kullanın (içinde venv aktive ediliyor). Veya Web → Virtualenv path: `/home/KULLANICI/backend/venv`. |
| **No module named 'cv2'** / **opencv** | Bağımlılıklar venv içine kurulmamış. Bash: `cd ~/backend` → `source venv/bin/activate` → `pip install -r requirements.txt` → Web’ten **Reload**. |
| **Unhandled Exception** (log’ta başka bir şey yok) | Error log’u açıp **tam traceback**’i okuyun; yukarıdaki maddelerden hangisine uyduğunu bulun. |
| **502 Bad Gateway** | Genelde import/yol hatası. Error log’a bakın; çoğu zaman `project_home` veya virtualenv path düzeltmesi yeterli. |

---

## Güvenilir WSGI örneği (virtualenv dahili)

PythonAnywhere’daki **WSGI configuration file** içeriğini tamamen silip aşağıdakini yapıştırın. **Üç yeri** kendinize göre düzeltin: `KULLANICI_ADINIZ`, `backend` klasörünün gerçek yolu, `venv` yolunun aynı yerde olduğu.

```python
import sys
import os

# Proje dizini (wsgi.py'nin bulunduğu klasör)
project_home = "/home/shaumne/uv-back-end"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Virtualenv site-packages — Web app'in fastapi vb. bulması için zorunlu
venv_path = "/home/shaumne/uv-back-end/venv"
lib_dir = os.path.join(venv_path, "lib")
if os.path.exists(lib_dir):
    for name in os.listdir(lib_dir):
        if name.startswith("python"):
            site_packages = os.path.join(lib_dir, name, "site-packages")
            if os.path.exists(site_packages):
                sys.path.insert(0, site_packages)
                break

from wsgi import application
```

Yolunuz farklıysa sadece `project_home` ve `venv_path` satırlarını kendi dizinlerinize göre değiştirin. Kaydettikten sonra **Web** → **Reload** yapın.

---

## Özet yol haritası

1. pythonanywhere.com → ücretsiz hesap aç.
2. Backend’i GitHub’dan clone et veya zip ile yükle.
3. Bash’te: `cd backend` → `python3.10 -m venv venv` → `source venv/bin/activate` → `pip install -r requirements.txt`.
4. Web → Manual configuration → Python 3.10 → WSGI dosyasını yukarıdaki gibi düzenle (yolları kendi kullanıcı adına göre yaz).
5. Virtualenv path’i Web’te `.../backend/venv` olarak ayarla.
6. Reload → `https://KULLANICI.pythonanywhere.com/health` ile test et.

Bu adımlarla API’niz PythonAnywhere üzerinde test için yayında olur.
