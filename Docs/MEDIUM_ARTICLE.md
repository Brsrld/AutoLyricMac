# Bir YouTube Linkinden Instagram Reels'e: Apple Silicon'da Uçtan Uca Lyric Video Fabrikası Kurmak

*Bir şarkı linki yapıştırıyorsunuz. 3-4 dakika sonra elinizde sözleri kelimesi kelimesine senkronize, sahneleri şarkının anlamına göre kurgulanmış, müziğin ritmiyle nefes alan 1080×1920'lik bir video var — ve tek tıkla Instagram'da. Bu yazı, AutoLyricMac'i inşa ederken öğrendiklerimizin hikâyesi.*

---

## Fikir: "Lyric video üretmek neden bir öğleden sonra sürüyor?"

Instagram Reels ve YouTube Shorts'ta lyric videolar küçük bir endüstri. Ama üretim süreci hâlâ el işçiliği: sözleri bul, zamanlamaları elle otur, stok görsel ara, After Effects'te kurgula... Bir video, bir öğleden sonra.

Hedefimiz netti: **URL → bitmiş video** hattını tamamen yerelde, bir M-serisi Mac'te, insan müdahalesi opsiyonel olacak şekilde kurmak. Bulut yok, abonelik yok; sadece gerektiğinde kuruş mertebesinde API çağrıları.

## Mimari: SwiftUI kabuk, Python motor

Uygulama iki parça:

- **SwiftUI uygulaması** — arayüz, geçmiş, Keychain'de anahtar yönetimi ve motorun yaşam döngüsü. Kullanıcı asla terminal görmüyor: uygulama açılınca Python motorunu kendisi başlatıyor, kapanınca öldürüyor.
- **Python motoru** — 127.0.0.1'e kilitli küçük bir HTTP servisi. Her ağır iş bir "job": indir, analiz et, hizala, planla, indir, çiz, render'la, yayınla. Swift tarafı sadece job açıp durum soruyor.

Bu ayrımın en tatlı meyvesi test edilebilirlik oldu: 170+ Python birim testi, motorun her saf fonksiyonunu (söz eşleme, sahne yerleşimi, sıralama, kırpma kararları) ağ ve model olmadan doğruluyor.

## 1. Perde: Ses ve "en iyi 60 saniye"

yt-dlp ile yetkili indirme (uygulama, her indirmede telif onayı istiyor) göründüğü kadar basit değil — YouTube ara ara "Sign in to confirm you're not a bot" duvarı çıkarıyor. Çözümümüz üç kademeli bir geri çekilme zinciri: normal istemci → iOS istemci kimliği → kullanıcının kendi tarayıcı oturumu (yt-dlp'nin resmi `cookies-from-browser` mekanizması).

Sonra librosa devreye giriyor: tempo, vuruşlar, onset'ler, enerji eğrisi, bölüm sınırları ve tekrar matrisi. "En iyi segment" seçicisi nakarat olasılığı + enerji + vuruş hizası puanlıyor; kesim noktaları vuruşa oturuyor, kelime ortasından kesmiyor.

## 2. Perde: Sözler ve saniyenin onda biri

En çok sökülen ve yeniden yazılan katman bu oldu. Nihai boru hattı:

1. **Söz bulma, üç kademe:** LRCLIB (ücretsiz, senkronlu sözler) → kullanıcının `.lrc/.txt` dosyası → hiçbiri yoksa *şarkının kendisinden transkripsiyon*. Evet: söz bulunamayan şarkıda motor vokali ayrıştırıp Whisper'a dinletiyor ve sözleri kendisi çıkarıyor.
2. **Vokal ayrıştırma (Demucs):** Kelime zaman damgalarını bulanıklaştıran şey enstrümanlar. Hizalamadan önce htdemucs ile vokali izole edince test şarkımızda eşleşme %60'tan %100'e çıktı.
3. **whisper-large-v3-turbo (MLX):** Apple Silicon'da 18 saniyelik ses ~4 saniyede işleniyor. `base` model Türkçe vokalde bir şarkıyı Rusça sanmıştı — sözler Türkçe *görünüyorsa* dili zorlayan bir metin sezgisi ekledik.
4. **Monotonik pencere eşleme:** Klasik global hizalama, "bülbül bülbül bülbül" gibi tekrarlı halk şarkılarında çuvallıyor — tüm tekrarlar ilk oluşuma yapışıyor. Bizim eşleyici satır satır, imlecin hep ilerisinde arıyor: her tekrar sıradaki oluşumu "tüketiyor". Sıfır süreli, sırasız satır kalmadı.
5. **Dürüst belirsizlik:** ASR'ın duyamadığı satır gizlice uydurulmuyor; senkronlu LRC varsa onun zamanına düşüyor, yoksa arayüzde turuncu işaretle "belirsiz" görünüyor. Kullanıcı kalem ikonuyla düzeltiyor, düzeltmeler kalıcı.

## 3. Perde: Anlamdan sahneye

Sahneler vuruşa değil **cümleye** kesiliyor — vuruşlar sadece mikro hareketi besliyor. Her satır için deterministik bir sözlük (İngilizce + Türkçe kökler: "hasret", "yağmur", "yol"...) konu/duygu/arama sorgusu çıkarıyor. Anthropic anahtarı varsa Claude Haiku aynı işi satır satır, çok daha isabetli yapıyor: *"Watch it fly by as the pendulum swings"* → "pendulum clock macro, moody light".

Kullanıcı bir de **tema** yazabiliyor: *"pişmanlık, geçen zaman, yalnız karanlık şehir"*. Tema parçalanıp yerel çeviriden geçiyor ve her sahnenin sorgu listesine dönüşümlü giriyor — enstrümantal sahneler bile şarkının dünyasından görsel arıyor.

## 4. Perde: Görseller — stok, havuz ve hiç tekrar etmeme kuralı

Üç resmi kaynak (Pexels, Pixabay, Unsplash) tek protokol arkasında; sonuçlar alaka + dikeylik + çözünürlük payıyla sıralanıyor. Sert kurallar: büyütme yok, esnetme yok, filigran kokusu alan etiket eleniyor, algısal hash (dHash) ile görsel kopyalar ayıklanıyor. Her sahne 1 ana + 2 yedek görsel indiriyor ve demir kural şu: **bir görsel yalnızca bir sahnede görünür.**

Doodle stili için stok tamamen bırakıldı: her sahne fal.ai üzerinde FLUX'a **çizdiriliyor** — kalın lacivert konturlu, masal kitabı dokulu illüstrasyonlar. Renk paleti sahnenin duygusundan geliyor (hüzün → yağmurlu indigo, sevinç → güneşli sarı). En eğlenceli detay "line boil": çizimin sinüzoidal alanla hafifçe eğrilmiş üç kopyası saniyede altı kez dönüyor ve resim, elle çiziliyormuş gibi titriyor — GIF üretmenin maliyeti olmadan animasyon hissi.

## 5. Perde: Ritim — metronom değil, davul

İlk sürümde görsel değişimleri vuruş ızgarasına bağlamıştık; "metronom gibi, ruhsuz" geri bildirimi geldi. Doğrusu şuydu: değişimler **perküsif onset'lerde** (bas/davul vuruşları) tetiklenmeli, kadans şarkının gerçek temposuna kilitlenmeli (60/BPM), sakin pasajlarda tek görsel uzun uzun durmalı ("uzun hava" modu). Bir de kritik incelik: cümle değiştiği anda görsel de değişirse kopukluk hissediliyor — her sahnenin ilk ve son saniyesi "değişim yasak" bölgesi ilan edildi. Sahneler arası geçiş efekti ise tamamen kaldırıldı: yeni sahnenin farklı görsel sayısı ve yerleşimi, geçişin kendisi.

Bu bölümün asıl dersi: **şablon estetiği koddan değil, referanstan çıkar.** Kullanıcı 10 gerçek referans video verdi; kare kare analiz edip her iki stilin kompozisyon kurallarını (fotoğraf oranları, rotasyon limitleri, metin boyutları, geçiş dilleri) ölçülmüş değerlerle yeniden yazdık — ve bu kurallar birim testlerine döküldü: "fotoğraf genişliği %55-90 arası", "rotasyon ≤0.35°" birer assert artık.

## 6. Perde: Yayınlama — resmi yollardan, şifresiz

- **YouTube:** PKCE'li OAuth (loopback yönlendirme), Keychain'de refresh token, parçalı devam ettirilebilir yükleme.
- **Instagram Reels:** Resmi Graph API. Instagram videoyu HTTPS URL'den istiyor; dosya Cloudflare R2'ye 1-2 dakikalığına gidiyor, container FINISHED olunca obje siliniyor. Stdlib ile yazılmış minimal bir SigV4 imzalayıcı — boto3'süz.
- Hiçbir yerde şifre yok. Kullanıcı bir keresinde e-posta+şifresini yapıştırdı; reddedip resmi token akışına yönlendirdik. (Şifrenizi asla bir yapay zekâya vermeyin.)

Sahadan bir bonus hikâye: R2'ye TLS el sıkışması sürekli düşüyordu. Suçlu ne Python ne Cloudflare'dı — makinedeki antivirüs, TLS trafiğine kendi sertifikasıyla araya giriyordu. Çözüm: obje trafiğini sistem güven zincirini kullanan curl'e devretmek.

## Tutumluluk: Aynı şeye iki kez para vermemek

Paralı her API sonucu yerel önbelleğe yazılıyor: Claude'un sahne yönergeleri (şarkı+söz anahtarıyla), çeviriler (satır bazında) ve FLUX görselleri (prompt hash'iyle). Planı beşinci kez yeniden kursanız da fatura değişmiyor. 20 dolarlık kredi, pratikte yüzlerce videoya yetiyor.

## Öğrendiklerimiz

1. **Saf fonksiyon + enjekte edilebilir taşıyıcı = huzur.** Ağ katmanı `opener` parametresiyle sahtelenince OAuth'tan resumable upload'a her şey çevrimdışı test edildi.
2. **ML çıktısına asla körü körüne güvenme.** Dil tespiti yanılır, hizalama kayar, FLUX resme yazı karalar. Her modelin çıktısına bir doğrulayıcı ve bir insan-düzeltme kapısı koyduk.
3. **Estetik geri bildirim döngüsü kısa olmalı.** Her render QA kareleri üretiyor; "şu saniye kötü" diyebilmek, "genel olarak beğenmedim"den yüz kat hızlı iterasyon demek.
4. **Deterministik temel + opsiyonel LLM** mimarisi hem ucuz hem sağlam: anahtar yoksa sistem yine çalışıyor, anahtar varsa parlıyor.

---

*AutoLyricMac; SwiftUI, Python, FFmpeg, librosa, Demucs, MLX Whisper, FLUX ve resmî YouTube/Instagram API'leri üzerine kurulu. Kod: github.com/Brsrld/AutoLyricMac*
