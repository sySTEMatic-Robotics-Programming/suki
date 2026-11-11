# Suki

**Data**: 11.11.2026\
**Lider proiect**: Ana-Maria Acsinte\
**Membri proiect**: Tomescu Vlad-Costin, Postelnicu Andrei

## Structura repository-ului
```text
├── backend/            # Serverul Python (FastAPI): motoare, cameră, AI, voce
│   ├── models/         # Modelele YOLO (.pt)
│   ├── lab/            # Imaginile din Lab și rezultatele adnotate
│   └── test_*.py       # Teste (pytest)
├── frontend/           # Interfața web (HTML/CSS/JS, fără build)
│   ├── css/
│   └── js/
├── requirements.txt    # Dependențele Python
├── run.sh              # Pornește serverul pe portul 8000
├── setup_voice.sh      # Instalează whisper.cpp + modelul și testează microfonul
└── README.md           # Acest fișier
```

## Descriere proiect
Suki este un robot patruped (câine-robot) controlat de un Raspberry Pi. Robotul se
controlează dintr-o pagină web servită chiar de Pi. Suki vede (detecție de obiecte
cu YOLO, de pe o cameră web USB), aude (recunoaștere vocală offline cu whisper.cpp)
și merge folosind mersuri învățate manual.

Nu folosește cloud și nici LLM. Toată partea de AI rulează local, pe Pi.

**Scopul principal** al lui Suki este să devină un **câine-ghid (service dog)** pentru
persoanele nevăzătoare: să le ajute să meargă singure prin oraș, ca pietoni. Robotul
trebuie să vadă mașinile, semnele de circulație, gropile și culoarea semaforului, să
spună omului ce e în jur și să se oprească atunci când traversarea nu e sigură.
Versiunea actuală este prototipul de laborator. Ce mai trebuie făcut până acolo este
descris în [Planuri de viitor](#planuri-de-viitor).

## Instrucțiuni de instalare/rulare

- Conectați-vă prin SSH la Raspberry Pi:\
    `ssh <utilizator>@<ip-pi>`

- Instalați dependențele:\
    `pip install -r requirements.txt`

- Instalați recunoașterea vocală (whisper.cpp + model, Raspberry Pi OS / Debian):\
    `./setup_voice.sh`

- Porniți serverul, apoi deschideți `http://<ip-pi>:8000` în browser:\
    `./run.sh`

- Rulați testele:\
    `cd backend && python3 -m pytest -q`

### Mod SIM

Orice componentă hardware este opțională. Interfața rulează pe orice laptop:

| Lipsește | Ce se întâmplă |
|---|---|
| PCA9685 / librăriile I2C | Motoarele rulează în modul **SIM**, nu se trimite nimic |
| whisper.cpp sau modelul lui | Tab-ul Audio rulează în SIM, textul scris tot pornește comenzi |
| Camera web | Video-ul arată „NO CAMERA" și reîncearcă la fiecare 10 s |
| `ultralytics` / `torch` | Detecția de obiecte este oprită, restul funcționează |

Setați `SUKI_NO_CAMERA=1` ca să nu se deschidă nicio cameră.

### Librării folosite

| Librărie | Folosită pentru |
|---|---|
| `fastapi`, `uvicorn`, `websockets` | Serverul web și WebSocket-ul |
| `numpy` | Procesare audio și imagine |
| `opencv-python` | Cameră, desenare pe imagine, culoarea semaforului |
| `adafruit-circuitpython-pca9685`, `adafruit-blinka` | Comunicare I2C cu PCA9685 (doar pe robot) |
| `ultralytics`, `torch` | YOLO (opțional) |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp), `alsa-utils` (`arecord`) | Recunoaștere vocală și captură microfon. Nu sunt pachete pip, le instalează `./setup_voice.sh` |

## Documentație software

### Arhitectură
Backend-ul este un server **FastAPI + uvicorn** scris în Python. El controlează
motoarele, citește camera și microfonul și rulează modelele AI. Frontend-ul este
HTML/JS simplu, fără build, servit de același server.

- Telemetria pleacă spre browser pe WebSocket-ul `/ws`, de 10 ori pe secundă.
- Video-ul pleacă spre browser ca MJPEG, pe `/stream.mjpg`.

### Module

| Fișier | Ce face |
|---|---|
| `backend/app.py` | Serverul FastAPI, rutele, WebSocket-ul |
| `backend/controller.py` | Bucla de mișcare la 50 Hz, engage/relax/E-STOP, poziții |
| `backend/driver.py` | Driverul PCA9685, verificarea cipului, protecția la căderi de tensiune |
| `backend/corridor.py` | Intervalul sigur al genunchiului pentru fiecare poziție a coapsei |
| `backend/walk.py` | Punctele de mers (gaits) |
| `backend/sequence.py` | Secvențele de poziții |
| `backend/camera.py` | Captura de pe camera web USB, stream MJPEG |
| `backend/vision.py` | Detecția YOLO + culoarea semaforului |
| `backend/lab.py` | Banc de test offline pentru modele |
| `backend/audio.py` | Captura microfonului, detecția vorbirii, înregistrare |
| `backend/stt.py` | Legătura cu whisper.cpp |
| `backend/voice.py` | Setări, comenzi vocale, potrivire aproximativă (fuzzy) |
| `backend/listener.py` | Ascultă vorbirea și pornește comenzile |
| `backend/config.py` | Toate constantele: canale, limite, viteze, modele |
| `frontend/` | Interfața web (`index.html`, `js/`, `css/`) |

### Controlul motoarelor

- **Buclă de mișcare la 50 Hz.** Un fir de execuție dedicat rulează de 50 de ori
  pe secundă. Cere prioritate real-time de la Linux (`SCHED_FIFO` 10) când are voie.
- **Rampă de viteză.** Servomotoarele nu sar niciodată direct la țintă. La fiecare
  pas se apropie de țintă cu o viteză setată: implicit 900 µs/s, interval
  60–2400 µs/s.
- **O singură scriere I2C pe pas.** Toate cele 16 canale pleacă spre PCA9685 într-un
  singur pachet. La fiecare 0,1 s se citește înapoi un canal, ca să se verifice că
  cipul ține valoarea trimisă.
- **Coridorul piciorului.** Pentru fiecare poziție a coapsei există un interval
  sigur min/max pentru genunchi (`backend/corridor.json`). Mișcările sunt limitate și
  făcute în pași, astfel încât genunchiul rămâne mereu în acest interval. Așa piciorul
  nu se lovește de el însuși sau de corp.
- **Mișcare în impulsuri (Pulsed motion).** Opțional: picioarele se mișcă pe rând, în
  pași de maximum 400 µs. Așa bateria nu alimentează niciodată patru picioare în
  mișcare deodată.
- **Protecție la căderi de tensiune.** PCA9685 este verificat la fiecare 0,2 s. O
  cădere de tensiune resetează cipul la o frecvență PWM greșită. La frecvența greșită
  impulsurile ies cu lățimea greșită și pot împinge toate articulațiile peste limite.
  De aceea Suki ține toate ieșirile la zero, apoi setează din nou frecvența. Dacă
  cipul este găsit resetat de 3 ori în 6 s, Suki renunță și ține toate ieșirile
  oprite până la repornire. Aceasta este o problemă de alimentare: reparați sursa.
- **E-STOP** pune toate ieșirile la zero (servomotoarele devin moi). Apăsați UNLOCK
  ca să puteți controla robotul din nou.

### Viziune: YOLO

Suki folosește modele [Ultralytics](https://docs.ultralytics.com) **YOLO26 nano**.
Fișierele sunt în `backend/models/`:

| Model | Ce detectează | Antrenare |
|---|---|---|
| `yolo26n.pt` | 80 de clase COCO uzuale (person, car, dog, cat, traffic light…) | Greutăți COCO standard |
| `trafficeu.pt` | 55 de indicatoare rutiere europene (limite de viteză, stop, cedează trecerea, trecere de pietoni…) | Antrenat pornind de la `yolo26n.pt`, 100 de epoci, 640 px, setul „Traffic Signs Detection Europe v14" (~4.500 de imagini) |
| `trafficch.pt` | 4 tipuri de indicatoare din Hong Kong (direcție, obligare, direcție stradă, avertizare) | Antrenat pornind de la `yolo26n.pt`, 50 de epoci, 640 px |

Camera live folosește `yolo26n.pt`. Pentru alt model, schimbați `YOLO_MODEL` în
`backend/config.py`.

#### Cum funcționează detecția live

1. Firul camerei citește cadre la 640×480, 20 fps.
2. Un fir separat de detecție încarcă YOLO la prima folosire, cu `torch` limitat la
   2 fire. Apoi face o rulare de încălzire (warm-up).
3. Detectorul ia cel mai nou cadru și rulează YOLO la **256 px**, cu **încredere
   0,4**. Apoi așteaptă 0,1 s și ia următorul cel mai nou cadru. Camera nu așteaptă
   niciodată după YOLO: desenează ultimele cutii pe care le are.
4. Cutiile se desenează pe video. Aceste clase sunt desenate cu portocaliu, ca
   alertă: person, bicycle, car, motorcycle, bus, truck, cat, dog.
5. Video-ul ajunge în browser ca MJPEG (`/stream.mjpg`). Detecțiile pleacă pe
   WebSocket.

#### Culoarea semaforului

YOLO găsește doar *unde* este semaforul. Culoarea se află cu OpenCV simplu:

1. Se ia cea mai mare cutie `traffic light` și se decupează.
2. Decupajul se convertește în HSV și se numără pixelii roșii, galbeni și verzi.
3. Dacă roșul sau verdele acoperă cel puțin 2% din decupaj, semaforul are acea
   culoare.
4. Dacă YOLO este oprit, se verifică tot cadrul.

Lab-ul folosește o variantă mai puternică. Când numărarea pixelilor este prea slabă,
caută cea mai luminoasă pată din decupaj. Apoi verifică nuanța ei și înălțimea ei în
carcasă (roșul este sus, verdele jos).

#### Lab

Tab-ul Vision are un Lab pentru testarea modelelor pe imagini statice:

- Încărcați până la 60 de imagini (maximum 12 MB fiecare, redimensionate la 1280 px
  pe latura lungă).
- Rulați pe ele orice fișier `.pt` din `backend/models/`. Alegeți încrederea și
  dimensiunea imaginii (160–1280 px).
- Rezultatele adnotate se salvează ca `backend/lab/<id>__<model>.out.jpg`.
- Cel mult 2 modele stau în memorie în același timp.

Un fișier `.pt` nou pus în `backend/models/` apare automat în Lab.

### Voce: whisper.cpp

Recunoașterea vocală folosește [whisper.cpp](https://github.com/ggerganov/whisper.cpp),
complet offline. `./setup_voice.sh` îl compilează și descarcă modelul.

- **Model:** implicit `ggml-base-q5_1.bin`. Alte modele `.bin` din folderul de
  modele whisper se pot alege din tab-ul Audio.
- **Limbi:** English, Română, 中文 sau detecție automată.
- **Setări de viteză:** decodare greedy, fără fallback, 2 fire, `nice 10`, ca bucla de
  mișcare să păstreze prioritatea.

Cum funcționează o comandă vocală:

1. `arecord` preia sunetul de la microfon la 16 kHz.
2. Un prag de energie ascultă după sunet puternic. Vorbirea începe când nivelul
   depășește pragul și se termină după 0,7 s de liniște. Clipurile mai scurte de
   0,4 s sunt ignorate, iar cele lungi sunt tăiate la 8 s.
3. whisper.cpp transcrie clipul. Toate frazele comenzilor sunt trimise ca prompt, ca
   whisper să prefere cuvintele pe care Suki le cunoaște.
4. Textul este trecut în litere mici și i se scot diacriticele. Apoi este comparat
   aproximativ (fuzzy) cu fiecare frază a fiecărei comenzi, în toate limbile.
5. O comandă pornește dacă scorul ei este cel puțin 0,80 și îl depășește pe al doilea
   cu 0,15. Altfel rezultatul este „no match" sau „ambiguous". Aceeași comandă nu
   poate porni din nou timp de 1,5 s.

Comenzi incluse (se editează din tab-ul Audio, salvate în `backend/commands.json`):

| Comandă | Exemple de fraze |
|---|---|
| Sit down | „sit down", „șezi", „坐下" |
| Stand up | „stand up", „ridică-te", „站起来" |
| Hold position | „hold position", „ține poziția", „保持姿势" |
| Relax | „relax", „relaxează-te", „放松" |
| Emergency stop | „emergency stop", „oprire de urgență", „急停" |
| Start / stop recording | „start recording", „oprește înregistrarea" |

O comandă poate porni o poziție, o secvență, engage, relax, E-STOP sau înregistrarea.

### Mișcare

- **Poziții (Actions):** poziții salvate pentru toate cele 8 servomotoare ale
  picioarelor, de ex. `SIT DOWN`, `P1`…`P5`. Poziția curentă se înregistrează din
  interfață. Salvate în `backend/actions.json`.
- **Secvențe:** un șir de poziții cu timp de menținere, număr de repetări și inversare
  opțională, de ex. „sit up" = `SIT DOWN → P1 → P2 → P3 → P4`. Salvate în
  `backend/sequences.json`.
- **Puncte de mers:** un mers (gait) este o listă de puncte pentru fiecare picior.
  Fiecare punct are o poziție a coapsei (µs), o poziție a genunchiului `k` (0 =
  capătul de jos al coridorului sigur, 1 = capătul de sus) și un timp de oprire.
  Mersuri incluse: `forward`, `backward`, `step`, `step back`. Salvate în
  `backend/walk_points.json`.

### Interfața web

Se deschide la `http://<ip-pi>:8000`.

| Tab | Ce face |
|---|---|
| Drive | Joystick pentru mers, butoane pentru poziții, cardurile live ale picioarelor, cameră pe tot ecranul |
| Calibration | Tabelul servomotoarelor, limite/coridor picioare, puncte de mers, test de mers, mișcare în impulsuri, poziții, secvențe |
| Simulator | Model 2D al picioarelor, cu poziția live și arcele mersului. Nu trimite nimic la robot |
| Vision | Camera live cu detecții, pornire/oprire cameră, Lab-ul |
| Audio | Nivelul microfonului, setări de ascultare, model whisper, înregistrare, comenzi vocale |
| Auto | Gol deocamdată |

## Documentație hardware

### Sisteme mecanice
**Software CAD**: Fusion

Suki are 4 picioare, fiecare cu 3 articulații: șold, coapsă și genunchi.

| Dimensiune | Valoare |
|---|---|
| Segment superior picior | 107 mm |
| Segment inferior picior | 138 mm |
| Lungime corp | 230 mm |
| Lățime corp | 78 mm |
| Înălțime în picioare | 150 mm |

### Sisteme electrice
**Software CAD:** Fusion

Lista de piese:

| Componentă | Detalii |
|---|---|
| Calculator | Raspberry Pi (timpii din cod sunt măsurați pe un Pi 4) |
| Driver servomotoare | Placă PCA9685, 16 canale PWM, magistrala I2C 1, adresa `0x40`, 50 Hz |
| Motoare | 12 servomotoare PWM standard (500–2500 µs): 4 picioare × (șold, coapsă, genunchi) |
| Cameră | Cameră web USB, 640×480 la 20 fps, prin OpenCV/V4L2 |
| Microfon | Microfonul camerei web (`plughw:CARD=Webcam,DEV=0`), 16 kHz |

Conectarea servomotoarelor la canalele PCA9685 (din `backend/config.py`):

| Picior | Coapsă | Genunchi | Șold |
|---|---|---|---|
| Spate-Stânga (BL) | ch 0 | ch 1 | ch 2 |
| Spate-Dreapta (BR) | ch 4 | ch 5 | ch 6 |
| Față-Stânga (FL) | ch 8 | ch 9 | ch 10 |
| Față-Dreapta (FR) | ch 12 | ch 13 | ch 14 |

- Cele 4 servomotoare de șold sunt **oprite implicit**. Suki se mișcă cu 8
  servomotoare (coapse și genunchi). Șoldurile se pornesc din Calibration → tabelul
  Hardware.
- Impulsurile servomotoarelor sunt între 500 și 2500 µs, cu neutrul la 1500 µs.
  Fiecare servomotor are propriile setări min, max și inversare, salvate în
  `backend/servo_config.json`.

## Planuri de viitor

### Obiectiv: câine-ghid pentru persoane nevăzătoare

Ținta finală este ca Suki să însoțească o persoană nevăzătoare pe stradă, ca un
câine-ghid. Concret, robotul trebuie să poată:

- să meargă pe trotuar, în fața omului, și să-l ghideze printr-un mâner (ham);
- să ocolească obstacole: stâlpi, oameni, biciclete, mașini parcate pe trotuar;
- să se oprească la bordură, la scări și în fața gropilor;
- să găsească trecerea de pietoni și semaforul de pietoni;
- să spună când semaforul e verde și să traverseze doar când este sigur;
- să urmeze un traseu ales vocal („du-mă la farmacie");
- să **refuze o comandă periculoasă** (de ex. „înainte" când vine o mașină). Câinii-ghid
  reali fac la fel; se numește *intelligent disobedience*.

### Îmbunătățiri necesare

#### Mecanică și alimentare

| Acum | Ce trebuie |
|---|---|
| Înălțime 150 mm, corp 230 mm | Robot mai mare (înălțime ~50–60 cm), ca să poată fi ținut de mâner și să urce o bordură de 15 cm |
| Servomotoare PWM de hobby, șoldurile oprite | Motoare mai puternice (servomotoare de putere sau motoare BLDC cu reductor), toate cele 12 articulații active |
| Mersuri învățate manual | Mers dinamic cu echilibru (IMU + control în buclă închisă), pentru teren denivelat, pantă, zăpadă |
| Probleme cu căderile de tensiune | Baterie dedicată pentru motoare, separată de calculator, autonomie de minimum 1–2 ore |
| Fără protecție | Carcasă rezistentă la ploaie și praf (minimum IP54) |
| — | Mâner cu senzor de forță și vibrații (feedback haptic), ca omul să simtă direcția și oprirea |

#### Senzori

| Senzor | Pentru ce |
|---|---|
| Cameră stereo / de adâncime | Distanța până la obstacole, bordură, groapă. Calculează adâncimea în hardware, fără să încarce procesorul principal |
| Cameră cu unghi larg, montată mai sus | Semaforul și semnele sunt deasupra; o cameră la 15 cm de sol nu le vede bine |
| IMU (accelerometru + giroscop) | Echilibru, detecția căderii, pantă |
| Senzori ultrasonici / ToF | Obstacole foarte apropiate, sticlă, lucruri pe care camera le ratează |
| GPS (ideal RTK) + busolă | Navigare pe traseu |
| Microfon cu mai multe capsule | Comenzi vocale în zgomotul străzii |
| Difuzor / cască cu conducție osoasă | Mesaje vocale fără să acopere sunetele străzii |

#### Software

- **Tab-ul Auto**: aici intră modul autonom (acum este gol).
- **Navigare**: hărți offline OpenStreetMap, traseu pe trotuare, localizare GPS + odometrie.
- **Segmentare**: trotuar, carosabil, trecere de pietoni, bordură, scări, nu doar cutii.
- **Urmărire în timp** (tracking, de ex. ByteTrack): aceeași mașină este urmărită de la un
  cadru la altul, ca să se știe dacă se apropie și cu ce viteză.
- **Semafor cu model dedicat**: culoarea se citește acum cu praguri HSV, care greșesc la
  soare puternic, noaptea sau cu reflexii. Trebuie un clasificator antrenat, cu clasele
  `roșu`, `verde`, `galben`, `stins`, `necunoscut`, separat pentru semaforul de pietoni
  (omulețul) și cel pentru mașini. Decizia „verde" se ia doar după mai multe cadre la
  rând care sunt de acord.
- **Rezoluție mai mare**: detecția rulează acum la 256 px. Un semafor la 15 m are doar
  câțiva pixeli la această rezoluție. Este nevoie de 640 px sau mai mult.
- **Mesaje vocale (TTS) offline**: „mașină din stânga", „trecere de pietoni în față",
  „verde, putem traversa".
- **Siguranță**: watchdog, oprire automată când un senzor nu mai răspunde, jurnal
  complet al deciziilor. Regula de bază: **când nu este sigur, Suki se oprește**.

### Recunoaștere cu acuratețe mare

Ce trebuie să recunoască Suki și țintele propuse:

| Clasă | Exemple | Țintă propusă |
|---|---|---|
| Semafor de pietoni + culoare | roșu, verde, verde intermitent, stins | Detecție ≥ 99% până la 20 m; „verde" fals practic zero (sub 1 la 10.000 decizii) |
| Vehicule | mașină, autobuz, camion, motocicletă, bicicletă, trotinetă | Detecție ≥ 98% până la 30 m, latență sub 150 ms |
| Pietoni și animale | persoană, cărucior, câine | Detecție ≥ 97% |
| Semne de circulație | trecere de pietoni, stop, cedează trecerea, accesul interzis | mAP50 ≥ 0,90 |
| Pericole la sol | gropi, capace lipsă, bordură, scări, denivelări, bălți | Detecție ≥ 95% până la 5 m |
| Elemente de navigare | trecere de pietoni (zebră), trotuar, carosabil | Segmentare, IoU ≥ 0,85 |

Erorile nu sunt egale. „Roșu" citit greșit ca „verde" poate fi mortal; „verde" citit ca
„roșu" înseamnă doar o așteptare în plus. Modelele și pragurile se aleg ca să favorizeze
oprirea.

De ce latența contează: o mașină cu 50 km/h parcurge ~14 m pe secundă. La 200 ms
întârziere, mașina a mers deja aproape 3 m până când Suki a reacționat.

### Seturi de date necesare

**Seturi publice** (pentru pre-antrenare):

| Set de date | Ce conține |
|---|---|
| [COCO](https://cocodataset.org) | Persoane, vehicule, semafoare (deja folosit de `yolo26n.pt`) |
| [Mapillary Traffic Sign Dataset](https://www.mapillary.com/dataset/trafficsign) | Peste 300 de tipuri de semne, din toată lumea, inclusiv Europa |
| [GTSDB / GTSRB](https://benchmark.ini.rub.de) | Semne de circulație germane (similare cu cele din România) |
| [DriveU Traffic Light Dataset (DTLD)](https://www.uni-ulm.de/in/iui-drive-u/projekte/driveu-traffic-light-dataset/) | Semafoare din orașe germane, cu starea fiecăruia |
| Pedestrian Traffic Lights (PTL / LYTNet) | Semafoare de pietoni fotografiate din perspectiva pietonului, făcut pentru nevăzători |
| [Mapillary Vistas](https://www.mapillary.com/dataset/vistas) / [Cityscapes](https://www.cityscapes-dataset.com) | Segmentare stradă: trotuar, bordură, trecere de pietoni |
| [RDD2022](https://github.com/sekilab/RoadDamageDetector) | Gropi și fisuri în asfalt, din mai multe țări |
| [BDD100K](https://www.vis.xyz/bdd100k/) | Condiții grele: noapte, ploaie, ceață |

**Set de date propriu** (obligatoriu): seturile publice sunt filmate din mașină, la
înălțimea unui șofer. Suki vede strada de jos, de pe trotuar, iar semafoarele, semnele și
trecerile de pietoni din România arată puțin diferit. Este nevoie de:

- imagini filmate chiar cu camera robotului, la înălțimea ei, pe trotuare din România;
- toate condițiile: zi, noapte, ploaie, zăpadă, soare din față, contre-jour;
- semafoare de pietoni românești, inclusiv cele cu numărătoare inversă;
- gropi, capace, bordure și scări de pe trotuare, nu doar de pe carosabil;
- orientativ **≥ 1.500 de imagini și ≥ 10.000 de obiecte adnotate pentru fiecare clasă**
  (recomandarea Ultralytics), plus ~10% imagini fără niciun obiect;
- adnotare cu [CVAT](https://www.cvat.ai) sau [Label Studio](https://labelstud.io),
  verificată de două persoane pentru clasele critice (semafor, vehicule).

Testarea finală se face pe un set separat, filmat pe străzi pe care modelul nu le-a văzut
niciodată.

### Performanță de calcul necesară

**Ce metrică contează**

- **TOPS INT8** (tera-operații pe secundă, pe 8 biți): metrica principală. Modelele
  YOLO se pot rula cuantizate pe 8 biți aproape fără pierdere de acuratețe.
- **TFLOPS FP16/FP32**: relevant doar dacă modelele rulează fără cuantizare.
- Cifra din fișa tehnică este un maxim teoretic. Un model real folosește de obicei doar
  20–40% din el.
- Ce contează cu adevărat: **cadre pe secundă și latența măsurate pe modelul nostru,
  la rezoluția noastră**, plus **TOPS/W**, pentru că robotul merge pe baterie.

**Cât calcul trebuie**

| Sarcină | Model exemplu | Cost per cadru | Cadre/s țintă |
|---|---|---|---|
| Detecție vehicule, pietoni, semne (640 px) | YOLO26s | ~20 GFLOPs | 15–20 |
| Segmentare trotuar, trecere, gropi (640 px) | YOLO26s-seg | ~30–40 GFLOPs | 10 |
| Clasificare culoare semafor (pe decupaj) | CNN mic | < 1 GFLOP | 15–20 |
| Adâncime | Calculată de camera stereo | 0 pe procesorul principal | 30 |

Total: ~0,7–1 TOPS folosiți efectiv. Cu utilizare reală de 20–40% și o rezervă pentru
modele mai mari, este nevoie de **minimum ~13 TOPS INT8, recomandat 26 TOPS sau mai mult**.

**Hardware-ul actual față de ce trebuie**

| Metrică | Acum (Raspberry Pi 4, doar CPU) | Necesar pentru stradă |
|---|---|---|
| Putere de calcul AI | sub 0,05 TFLOPS FP32 (maxim teoretic, 4 nuclee Cortex-A72), fără accelerator | ≥ 13 TOPS INT8, recomandat ≥ 26 TOPS |
| Rezoluție detecție | 256 px | ≥ 640 px |
| Model | YOLO26 nano (~6 GFLOPs la 640 px, ~1 GFLOP la 256 px) | Model „small” sau mai mare (~20–40 GFLOPs), mai multe modele în paralel |
| Cadre/s detecție | câteva, cu pauză de 0,1 s între rulări | ≥ 15 pentru detecție, ≥ 10 pentru segmentare |
| Latență cameră → decizie | sute de ms | sub 150 ms |
| Memorie RAM | partajată cu restul sistemului | ≥ 8 GB |
| Consum pentru partea de AI | — | sub ~15 W, ca bateria să țină 1–2 ore |

Cu procesorul Pi 4, un YOLO nano la 640 px merge doar cu câteva cadre pe secundă. De
aceea detecția rulează acum la 256 px și cu pauze. Pentru uz pe stradă, puterea de calcul
trebuie să crească de câteva sute de ori.

**Eficiența energetică: de ce un accelerator AI**

Suki merge pe baterii și, ca un câine-ghid, trebuie să țină o plimbare întreagă prin
oraș. Autonomia contează la fel de mult ca puterea de calcul. Un accelerator AI dedicat
(NPU) ajută direct la asta:

- Un NPU face aceleași operații ca procesorul cu mult mai puțină energie. Procesorul
  general obține de obicei sub 0,01 TOPS/W la rețele neuronale. Un NPU ajunge la ordinul
  câtorva TOPS/W, deci de sute de ori mai eficient pe fiecare cadru procesat.
- Procesorul Pi 4 rulând YOLO în continuu stă aproape de sarcină maximă: consumă mai mult,
  se încălzește și ajunge să-și scadă singur frecvența (throttling). Cu un accelerator,
  procesorul rămâne liber pentru bucla de mișcare la 50 Hz, voce și navigare.
- Energia economisită la calcul rămâne pentru motoare, care consumă oricum cel mai mult.
  Asta înseamnă mai mulți kilometri pe o încărcare.
- Ținta este ca toată partea de AI să consume **sub ~15 W**, la **≥ 2 TOPS/W**.

---
**© sySTEMatic Robotics**
