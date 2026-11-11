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

---
**© sySTEMatic Robotics**
