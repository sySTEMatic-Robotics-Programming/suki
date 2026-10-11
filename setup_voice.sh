#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$HERE/backend"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

step() { printf '\n\033[1;35m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '    \033[33mwarn\033[0m  %s\n' "$*"; WARNED=1; }
info() { printf '          %s\n' "$*"; }
die()  { printf '\n\033[1;31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }
WARNED=0

[ "$(uname -s)" = "Linux" ] || die "this targets Raspberry Pi OS / Debian, not $(uname -s)"
[ -f "$BACKEND/config.py" ] || die "no backend/config.py next to this script"

step "Reading backend/config.py"
eval "$(cd "$BACKEND" && python3 - <<'PY'
import os
import shlex
import config as c

def emit(k, v):
    print("%s=%s" % (k, shlex.quote(str(v))))

emit("CFG_BIN", c.WHISPER_BIN)
emit("CFG_MODEL", c.WHISPER_MODEL)
emit("CFG_MODEL_DIR", c.WHISPER_MODEL_DIR)
emit("CFG_MODEL_NAME",
     os.path.basename(c.WHISPER_MODEL).removeprefix("ggml-").removesuffix(".bin"))
emit("CFG_MIC", c.MIC_DEVICE)
emit("CFG_RATE", c.MIC_RATE)
emit("CFG_CHANNELS", c.MIC_CHANNELS)
emit("CFG_THREADS", c.WHISPER_THREADS)
emit("CFG_NICE", c.WHISPER_NICE)
emit("CFG_RECDIR", os.path.join(os.path.dirname(os.path.abspath(c.__file__)),
                                c.RECORD_DIR))
PY
)" || die "could not read backend/config.py — is python3 installed?"

MODEL="${MODEL:-$CFG_MODEL_NAME}"
WHISPER_DIR="${WHISPER_DIR:-$(dirname "$(dirname "$(dirname "$CFG_BIN")")")}"
BIN="$CFG_BIN"
MODEL_FILE="$CFG_MODEL_DIR/ggml-$MODEL.bin"
JOBS="$(nproc 2>/dev/null || echo 4)"

ok "whisper binary  $BIN"
ok "model           $MODEL_FILE"
ok "microphone      $CFG_MIC at ${CFG_RATE} Hz, ${CFG_CHANNELS} ch"
[ "$MODEL" = "$CFG_MODEL_NAME" ] || warn "MODEL=$MODEL overrides the configured $CFG_MODEL_NAME"

step "System packages"
PKGS="alsa-utils git build-essential cmake"
MISSING=""
for p in $PKGS; do
  dpkg -s "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"
done
if [ -n "$MISSING" ]; then
  if [ "$CHECK_ONLY" = 1 ]; then
    warn "missing:$MISSING"
  else
    echo "   installing:$MISSING"
    sudo apt-get update -qq
    sudo apt-get install -y $MISSING || die "apt could not install:$MISSING"
    ok "installed"
  fi
else
  ok "alsa-utils, git, build-essential, cmake all present"
fi

if python3 -c "import numpy" 2>/dev/null; then
  ok "python3 numpy present (audio.py needs it for the level meter and the VAD)"
else
  warn "python3 has no numpy — the microphone cannot start without it"
  info "pip3 install numpy    (or: sudo apt-get install -y python3-numpy)"
fi

step "whisper.cpp"
if [ -x "$BIN" ]; then
  :
elif [ -d "$WHISPER_DIR/.git" ]; then
  ok "already cloned at $WHISPER_DIR"
elif [ "$CHECK_ONLY" = 1 ]; then
  warn "not cloned at $WHISPER_DIR"
else
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$WHISPER_DIR" \
    || die "clone failed — check the network"
  ok "cloned"
fi

if [ -x "$BIN" ]; then
  ok "already built"
elif [ "$CHECK_ONLY" = 1 ]; then
  warn "$BIN is not built"
elif [ -d "$WHISPER_DIR" ]; then
  echo "   building with $JOBS jobs, ~3 minutes on a Pi 4..."
  cmake -B "$WHISPER_DIR/build" -S "$WHISPER_DIR" -DCMAKE_BUILD_TYPE=Release >/dev/null \
    || die "cmake configure failed"
  cmake --build "$WHISPER_DIR/build" -j "$JOBS" >/dev/null \
    || die "build failed — re-run the cmake --build line with -j1 to see the compiler error"
  ok "built"
fi

if [ ! -x "$BIN" ]; then
  ALT="$WHISPER_DIR/build/bin/main"
  if [ -x "$ALT" ]; then
    warn "this checkout built '$ALT', but config.py opens '$BIN'"
    info "that is the old whisper.cpp layout. Either:"
    info "  ln -s '$ALT' '$BIN'"
    info "  or:  export WHISPER_BIN='$ALT'   (add it to ~/.bashrc)"
    info "  or:  git -C '$WHISPER_DIR' pull && rebuild"
  else
    warn "no whisper binary at $BIN"
  fi
fi

step "Model: $MODEL"
if [ -f "$MODEL_FILE" ]; then
  ok "already downloaded ($(du -h "$MODEL_FILE" | cut -f1))"
elif [ "$CHECK_ONLY" = 1 ]; then
  warn "$MODEL_FILE is missing"
elif [ -d "$WHISPER_DIR/models" ]; then
  sh "$WHISPER_DIR/models/download-ggml-model.sh" "$MODEL" \
    || die "could not fetch '$MODEL' — run $WHISPER_DIR/models/download-ggml-model.sh with no arguments for the valid names"
  [ -f "$MODEL_FILE" ] || die "download reported success but $MODEL_FILE is missing"
  ok "downloaded ($(du -h "$MODEL_FILE" | cut -f1))"
fi

if [ -d "$CFG_MODEL_DIR" ]; then
  FOUND="$(find "$CFG_MODEL_DIR" -maxdepth 1 -name 'ggml-*.bin' -printf '%f ' 2>/dev/null || true)"
  [ -n "$FOUND" ] && info "the Audio tab's picker will offer: $FOUND"
fi

step "Proof: transcribing a known sample"
SAMPLE="$WHISPER_DIR/samples/jfk.wav"
if [ ! -x "$BIN" ] || [ ! -f "$MODEL_FILE" ]; then
  warn "skipped — the binary or the model is not in place yet"
elif [ ! -f "$SAMPLE" ]; then
  warn "no samples/jfk.wav in this checkout, skipping"
else
  NICE=""
  [ "$CFG_NICE" != "0" ] && command -v nice >/dev/null && NICE="nice -n $CFG_NICE"
  T0=$(date +%s)
  OUT="$($NICE "$BIN" -m "$MODEL_FILE" -f "$SAMPLE" -t "$CFG_THREADS" -l en -nt -np \
         2>/dev/null | tr -d '\n' | sed 's/^ *//;s/ *$//' || true)"
  T1=$(date +%s)
  info "heard: \"$OUT\""
  info "took $((T1 - T0))s with $CFG_THREADS thread(s) — the same settings stt.py uses"
  case "$(echo "$OUT" | tr '[:upper:]' '[:lower:]')" in
    *country*) ok "the whole speech-to-text chain works" ;;
    "")        die "transcribed nothing — the model or the build is broken" ;;
    *)         warn "transcribed something unexpected; the chain runs but check the model" ;;
  esac
  if [ "$((T1 - T0))" -gt 25 ]; then
    warn "that is slow enough to hit stt.py's timeout on real speech"
    info "use a smaller model:  MODEL=tiny-q5_1 ./setup_voice.sh"
  fi
fi

step "Capture devices"
if ! command -v arecord >/dev/null; then
  warn "no arecord — alsa-utils is not installed, so the microphone runs in SIM"
elif arecord -l 2>/dev/null | grep -q '^card'; then
  arecord -l | sed -n 's/^card /    card /p'

  SEED_CARD="$(printf '%s' "$CFG_MIC" | sed -n 's/.*CARD=\([^,]*\).*/\1/p')"
  if [ -n "$SEED_CARD" ]; then
    if arecord -L 2>/dev/null | grep -q "^plughw:CARD=$SEED_CARD,"; then
      ok "the configured device names card '$SEED_CARD', which exists"
    else
      warn "config.py seeds MIC_DEVICE=$CFG_MIC but no card is called '$SEED_CARD'"
      info "pick the right one in the Audio tab (it is stored in backend/settings.json),"
      info "or use one of these strings:"
      arecord -L 2>/dev/null | grep '^plughw:CARD=' | head -6 | sed 's/^/            /' || true
    fi
  fi
fi

step "Proof: recording one second"
if ! command -v arecord >/dev/null; then
  warn "skipped — no arecord"
else
  TMPWAV="$(mktemp -t suki-mic-XXXXXX.wav)"
  trap 'rm -f "$TMPWAV"' EXIT
  if arecord -q -D "$CFG_MIC" -f S16_LE -r "$CFG_RATE" -c "$CFG_CHANNELS" \
             -d 1 "$TMPWAV" 2>"$TMPWAV.err"; then
    LVL="$(python3 - "$TMPWAV" <<'PY'
import sys, wave, array
try:
    with wave.open(sys.argv[1]) as w:
        n, ch = w.getnframes(), w.getnchannels()
        a = array.array("h"); a.frombytes(w.readframes(n))
    if not len(a):
        print("empty"); raise SystemExit
    left = a[0::ch] if ch > 1 else a
    peak = max(max(left), -min(left))
    rms = (sum(float(v) * v for v in left) / len(left)) ** 0.5
    print("%.0f %.0f" % (rms, peak))
except Exception as e:
    print("unreadable %s" % e)
PY
)"
    RMS="$(printf '%s\n' "$LVL" | cut -d' ' -f1)"
    PEAK="$(printf '%s\n' "$LVL" | cut -d' ' -f2)"
    RMS="${RMS:-0}"; PEAK="${PEAK:-0}"
    case "$RMS" in
      empty|unreadable*) warn "recorded a file this build of python cannot read: $LVL" ;;
      *)
        info "one second at $CFG_MIC: RMS $RMS, peak $PEAK (16-bit, so 32767 is clipping)"
        if [ "${RMS%.*}" -lt 5 ]; then
          warn "that is digital silence — the device opens but delivers nothing"
          info "check it is not muted:  amixer -c \"$SEED_CARD\" scontrols"
          info "and unmute the capture:  alsamixer -c \"$SEED_CARD\"  (F4 for capture)"
        elif [ "${RMS%.*}" -lt 30 ]; then
          ok "capture works (quiet room — say something and re-run to see it rise)"
        else
          ok "capture works and the room is not silent"
        fi
        ;;
    esac
  else
    warn "could not open $CFG_MIC"
    sed 's/^/          /' "$TMPWAV.err" 2>/dev/null | head -4 || true
    if grep -qi "busy" "$TMPWAV.err" 2>/dev/null; then
      info "the device is held by something else. On Bookworm that is usually PipeWire:"
      info "  systemctl --user stop pipewire.socket pipewire.service wireplumber.service"
      info "  (or pick a plughw: device the sound server is not holding)"
    else
      info "try one of these strings in the Audio tab instead:"
      arecord -L 2>/dev/null | grep '^plughw:CARD=' | head -6 | sed 's/^/            /' || true
    fi
  fi
  rm -f "$TMPWAV.err"
fi

if command -v pgrep >/dev/null; then
  HOLDER=""
  pgrep -x pipewire   >/dev/null 2>&1 && HOLDER="PipeWire"
  pgrep -x pulseaudio >/dev/null 2>&1 && HOLDER="${HOLDER:+$HOLDER and }PulseAudio"
  if [ -n "$HOLDER" ]; then
    info "$HOLDER is running. Suki opens the card directly with arecord, so if capture"
    info "ever starts failing with 'Device or resource busy', that is what has it."
  fi
fi

step "Recording directory"
if mkdir -p "$CFG_RECDIR" 2>/dev/null && [ -w "$CFG_RECDIR" ]; then
  ok "$CFG_RECDIR is writable"
else
  warn "$CFG_RECDIR is not writable — the Audio tab's recorder will fail"
  info "sudo chown -R \"\$USER\" \"$CFG_RECDIR\""
fi

step "Summary"
[ -x "$BIN" ]          && ok "whisper binary"       || warn "whisper binary missing"
[ -f "$MODEL_FILE" ]   && ok "model on disk"        || warn "model missing"
command -v arecord >/dev/null && ok "arecord" || warn "arecord missing (SIM mode)"

if [ "$MODEL" != "$CFG_MODEL_NAME" ]; then
  echo
  warn "you installed '$MODEL' but config.py loads '$CFG_MODEL_NAME'"
  info "pick $MODEL in the Audio tab (it is stored in settings.json), or make it the default:"
  info "  echo \"export WHISPER_MODEL=$MODEL_FILE\" >> ~/.bashrc && source ~/.bashrc"
fi

echo
if [ "$WARNED" = 1 ]; then
  printf '    \033[33mSome checks warned above.\033[0m Everything unwarned is working.\n'
  echo "    Suki still starts: without a microphone the Audio tab runs in SIM and the"
  echo "    type box exercises the whole matcher, which is how commands are written."
else
  printf '    \033[32mThe whole audio chain is in place.\033[0m\n'
fi
echo "    Start it:  ./run.sh"
HOSTIP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo "    Then open  http://${HOSTIP:-$(hostname 2>/dev/null || echo localhost)}:8000"
echo "    Re-check any time without changing anything:  ./setup_voice.sh --check"
