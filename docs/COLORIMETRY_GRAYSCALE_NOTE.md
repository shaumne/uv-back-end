# Doz Okumasında Siyah-Beyaz (Grayscale) Kullanımı — Teknik Görüş

## Mevcut pipeline (özet)

1. Beyaz dengesi (LAB Grey-World)
2. Sticker bölgesi izolasyonu (kontur / maske)
3. **K-Means (k=3)** → en fazla piksel sayısına sahip küme = **dominant renk** → HEX
4. **HEX → LAB L\*** → kalibrasyon eğrisi ile **L\* → UV%**

Yani doz zaten **tek bir skalere (L\* = parlaklık)** indirgeniyor. Renk (a\*, b\*) sadece “sticker mı?” kontrolü (mor ton) ve “achromatic artefact” atlamak için kullanılıyor.

---

## Grayscale fikri

**Öneri:** Sticker tespit edildikten sonra görüntüyü siyah-beyaza çevirip doz okumasını oradan yapmak.

### Artıları

- **Renk kaynaklı gürültü azalır:** Ortam ışığının rengi (güneş/saat, gölge, LED) RGB’yi kaydırır; grayscale’da sadece parlaklık kalır. Kalibrasyon zaten L\* üzerinden olduğu için mantıken uyumlu.
- **K-Means’e bağımlılık azalır:** Dominant renk tek bir küme merkezi; birkaç parlak/gölge pikseli sonucu oynatabilir. ROI’nin **ortanca/ortalama parlaklığı** daha kararlı olabilir.
- **Beyaz dengesi etkisi:** LAB white balance sonrası L\* kanalı zaten “nötrleştirilmiş” parlaklık; grayscale ile tüm ROI’den tek bir L değeri (örn. ortanca) almak, renk kanallarının ağırlık farkından kaynaklanan sapmayı azaltabilir.

### Dikkat edilmesi gerekenler

- **Sticker tespiti renkli kalsın:** “Sticker var mı?” ve “mor/uygun ton mu?” kontrolü mevcut renkli pipeline ile yapılmaya devam etmeli; grayscale sadece **doz okuma adımı** için düşünülmeli.
- **Aynı kalibrasyon eğrisi:** L\* → UV% eğrisi değişmez; sadece L\* değerini **dominant HEX’ten** değil, **ROI’nin ortanca (veya ortalama) L\*** değerinden üretiriz.
- **Uygulama yeri:** Bu mantık **backend’de** uygulanmalı: sticker izole edildikten sonra ROI’yi LAB’ye çevirip yalnızca L kanalından ortanca/ortalama alıp mevcut `_hex_to_uv_percent` benzeri L\* → UV% eşlemesiyle sonucu ver. Mobil tarafta görüntüyü grayscale’a çevirip göndermek hem API’yi (tek kanal görüntü) hem de “dominant HEX” raporlamayı bozar; önerilmez.

---

## Öneri (uygulama öncesi)

- **Şu an:** Mevcut pipeline (dominant HEX → L\* → UV%) çalışıyor ve circle detect’ten memnunsanız, **grayscale’ı zorunlu yapmayın**.
- **İsteğe bağlı deneme:** Backend’de sticker tespitinden sonra **opsiyonel** bir yol ekleyın:
  - ROI → LAB → sadece L kanalı → **ortanca(L)** (veya ortalama) → aynı L\* → UV% eğrisi.
  - Bunu bir **feature flag** veya **query parametresi** (`?dose_from_median_l=true`) ile açıp gerçek çekimlerle A/B karşılaştırması yapın.
- **Sonuç:** Eğer ortanca L\* okuması, farklı ışık ve mesafelerde daha kararlı çıkarsa, varsayılan doz okumayı buna geçirebilirsiniz; yoksa mevcut dominant-HEX yöntemi kalsın.

Özet: **Evet, “sticker tespitinden sonra siyah-beyaz/parlaklık üzerinden doz okumak” teknik olarak mantıklı ve denemeye değer; uygulama backend’de, mevcut L\* eğrisi korunarak ve isteğe bağlı (A/B) yapılmalı.**
