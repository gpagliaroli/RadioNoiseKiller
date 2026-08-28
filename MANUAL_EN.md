# RadioNoiseKiller — User Manual

**Version 2.3**

---

## Introduction

**RadioNoiseKiller** is a Windows and Linux application that processes the audio of an AM/SSB radio in real time before it reaches your speakers or headphones. It sits between the radio's audio output (or SDR receiver) and final playback, acting as a chain of digital filters designed specifically for the kind of noise found on shortwave and AM bands.

### What is it for?

In amateur radio and shortwave listening, audio is usually degraded by:

- **Band noise** (static, white background noise)
- **Atmospheric impulses** (QRN, electrical discharges, crackle)
- **Tone interference** (heterodynes, AM carriers from other stations, mains harmonics)
- **Excessive bandwidth** (frequencies outside the voice range that add unnecessary noise)

The application applies a series of chained processes — the **pipeline** — where each stage attacks one specific kind of degradation. The result is cleaner audio with better voice intelligibility, without introducing audible artificial artifacts.

### How is it used in practice?

1. Connect the radio's audio output to a PC input (line in, or a virtual cable for software SDR).
2. Select that input as the **input device** in the application.
3. Select your speakers or headphones as the **output device**.
4. Set the mode (AM or SSB) and press **START**.
5. Adjust the modules to match the signal type and propagation conditions.

### What the application does NOT do

- It does not demodulate the RF signal — it receives already-demodulated audio.
- It does not correct the level of propagation fading — that is what the **Voice leveler** (Ch. 7) is for: it evens out the level between rises and dips.
- It does not improve signals with a very low signal level (S-meter) — it needs some signal to work with.

### In-app help

**Every slider has a help text**: hover for a second over the control's name, bar or value and a
tooltip appears explaining what it does, which way to move it and what it costs in return. It is the
short version of what the following chapters explain — handy for adjusting without letting go of the
radio, leaving the manual for when you want the reasoning.

You can also **right-click any slider** to restore its factory value.

---

## Glossary of terms

Terms used throughout this manual, in alphabetical order. Experienced operators can skip this chapter and come back when they run into an unfamiliar term.

| Term | Meaning |
|------|---------|
| **AGC** | Automatic Gain Control. Continuously adjusts the volume to keep a stable output level: it amplifies weak signals and attenuates strong ones. |
| **AM / SSB** | The two supported reception modes. **AM** (amplitude modulation): broadcasting and commercial shortwave, wide bandwidth. **SSB** (single sideband): the usual voice mode in HF amateur radio, more efficient but with the voice compressed in frequency. |
| **ANF** | Automatic Notch Filter. Detects and removes continuous tones (heterodynes, carriers, mains hum) without affecting the voice. |
| **Attack / Release** | Reaction times of a dynamics processor. **Attack:** how fast it reacts when the signal rises. **Release:** how fast it recovers when the signal falls. |
| **Bin (spectral)** | Each of the frequency "cells" the FFT divides the spectrum into. The noise canceller decides bin by bin how much to attenuate. |
| **Bypass** | Passing the audio through unprocessed. Useful for comparing the sound with and without the application. |
| **Carrier** | An unmodulated radio signal (a pure RF tone). In demodulated audio it appears as a continuous whistle or as silence with background noise, depending on the mode. |
| **dB / dBFS** | **Decibel:** logarithmic level unit; +6 dB ≈ double the amplitude, −20 dB = one tenth. **dBFS** (*full scale*): decibels referenced to the digital maximum; 0 dBFS is the absolute ceiling before distortion, working levels are negative (e.g. −20 dBFS). |
| **DSP** | Digital Signal Processing. All the work the application does on the audio: filters, noise cancellation, equalization. |
| **Fading / QSB** | Slow rises and falls of the signal level due to changes in ionospheric propagation, typical of shortwave. QSB is its Q code in amateur radio. |
| **FFT / Spectrum** | The FFT (*Fast Fourier Transform*) decomposes audio into its component frequencies. The **spectrum** is that representation: how much energy exists at each frequency. |
| **Bandpass filter** | A filter that only passes frequencies between a lower and an upper limit (e.g. 200–3000 Hz for SSB), removing everything else. |
| **Gate** | An audio gate: open, it lets sound through; closed, it attenuates it. It is the mechanism behind the Noise gate (Ch. 8). |
| **Harmonics** | Multiples of a sound's fundamental frequency. The human voice concentrates its energy in the fundamental (80–400 Hz) and its harmonics — that structure is what distinguishes voice from noise. |
| **Heterodyne** | A continuous tone (whistle) produced by a carrier close to the tuned frequency. The ANF removes them automatically. |
| **Hold** | The time the gate stays open after the signal drops, to avoid cutting word endings or brief pauses. |
| **Hz / kHz** | Hertz: frequency unit (cycles per second). 1 kHz = 1000 Hz. SSB voice occupies roughly 200–3000 Hz. |
| **MCRA** | **Adaptive** noise estimation mode (*Minima Controlled Recursive Averaging*). Estimates the noise floor continuously and automatically, with no need to "learn" a profile manually. The alternative to the Static profile. |
| **Noise floor** | The constant background noise level of the band. Everything below it is inaudible; the useful signal must rise above it. |
| **Noise profile** | A "photograph" of the band noise the canceller uses as a reference. In static mode it is learned manually (3–5 s without signal); in Adaptive (MCRA) mode it is estimated automatically. |
| **Pipeline** | The processing chain: the ordered sequence of stages the audio passes through from input to output. |
| **Pitch (f0)** | The fundamental frequency of the voice — the "tone" a person speaks at (80–400 Hz). The application detects it to protect the voice harmonics. |
| **Preset** | A saved set of all DSP and gain settings, to load complete configurations at once (Presets tab). |
| **Q (selectivity)** | The quality factor of a filter: how narrow it is. Low Q = affects a wide band of frequencies; high Q = a narrow, selective peak. |
| **QRN** | Q code for atmospheric noise: electrical discharges, storms, impulsive crackle. Handled by the Impulse Suppressor. |
| **RMS** | Root Mean Square: a measure of a signal's average level, more representative of perceived loudness than the peak value. |
| **SDR** | Software Defined Radio. Receivers whose demodulation happens on the PC (SDR#, HDSDR, etc.); their audio can be processed with this application using a virtual audio cable. |
| **SNR** | Signal-to-Noise Ratio: how many times the signal exceeds the noise. High SNR = clean signal; low SNR = signal buried in noise. |
| **Squelch** | The receiver's silencer: cuts the audio output when no transmission is present. In this application the equivalent is the **Noise gate** (Ch. 8), which attenuates instead of cutting and decides on input level. |
| **Threshold** | A detector's trigger value: above it, the detector acts; below it, it doesn't. Several modules have a configurable threshold (noise gate, ANF, impulse suppressor). |
| **VAD** | Voice Activity Detector. Decides in real time whether what is heard is human voice or just noise; it feeds the canceller. |
| **Wiener (filter)** | A mathematical noise reduction technique that attenuates each spectrum bin in proportion to how much noise it contains. It is the heart of the Stationary Noise Canceller. |

---

## Pipeline diagram

Audio flows through the following processes in order. Each stage can be enabled or disabled independently:

![Processing pipeline diagram](Images/pipeline_diagram_en.png)

---

## Chapter 1 — Audio Devices

**Location:** Main tab → "Audio Devices" group

### Description

Selects where the audio comes from (input) and where it goes (output). On Windows the application only shows **WASAPI** and **WDM-KS** devices, the lowest-latency Windows drivers.

### Controls

| Control | Description |
|---------|-------------|
| **Input** | Audio source. It can be a physical input (line in, microphone), a virtual audio device (VB-Cable, etc.) or "Stereo Mix" to capture what another application plays. |
| **Output** | Destination of the processed audio. Typically your speakers or headphones. |
| **⟳ (rescan)** | Rescans the audio devices without closing the application — for when hardware (USB interface, headphones) is plugged or unplugged while the program is open. The current selection is kept if the device is still present. Only available while processing is stopped. |
| **Channel** | Channel taken from the input when it is stereo: **Left** (default), **Right** or **L+R mix**. Applies live, without restarting processing. Has no effect with mono inputs. |

### Tips

- If you use a software SDR (HDSDR, SDR#, etc.), configure that program to output to a **virtual audio cable** and select that cable as the input here.
- If the list is empty or incomplete, or new hardware was plugged in while the program was open, use the **⟳** button to rescan the devices (with processing stopped). If a device is still missing, restart the application.
- Changing devices requires stopping and re-starting processing — that is why the Input/Output selectors are disabled while processing is active (the Channel selector stays enabled: it applies live).
- If you hear nothing from a stereo USB interface, try **Channel: Right** — radio audio is often wired to that channel.
- The input and output must belong to the **same Windows API** (both WASAPI, or both WDM-KS): a full-duplex stream cannot mix APIs. If you pick an incompatible combination (for example a WASAPI input plus an output that only exists under WDM-KS, such as "Stereo Mix"), the application **disables the START button**, outlines both selectors with a warning border and explains the reason in the status bar. Pick both devices from the same API to be able to start.
- On **dual-receiver** radios (main RX on the left channel, sub-RX on the right), the Channel selector picks which one to process. The processed output always plays in both ears.

---

## Chapter 2 — General Control

**Location:** Main tab → "Control" group

### Description

The main operating controls: reception mode, AGC and processing activation.

### Controls

| Control | Description |
|---------|-------------|
| **Bandpass** | Width of the input filter, chosen by what you are listening to. There are eight ready-made widths —four for SSB phone and four for AM— plus **Custom**, which is whatever limits you set by hand in *Advanced Audio*. It replaces the old **Mode (AM/SSB)** selector: with the app's presets, picking the mode and then the width was saying the same thing twice — what you pick is the **width**. |
| **AGC** | Automatic Gain Control. **off** = no AGC. **slow / medium / fast** = response speed (attack/release fixed per preset). For SSB, *slow* or *medium* is recommended; for AM with stable signals, *off* or *slow*. |
| **Level continuously (music)** | Checkbox belonging to the **Voice leveler** (Ch. 7), placed here because you change it depending on what you are listening to: ticked for music or continuous audio, unticked for voice. Requires the canceller and the leveler enabled. |
| **Noise ceiling** | Limits how much the AGC can amplify, so it does not lift the band noise. See below. |
| **▶ START / ■ STOP** | Starts or stops real-time processing. When started, audio flows through the whole pipeline. |

### AGC — noise ceiling

**Location:** Main tab → "Control" group, below the AGC selector

The AGC brings the signal to its target level **without telling speech from noise**. On a strong station that is exactly what you want; on a weak signal, what it measures is mostly band noise, and it amplifies it by up to **+36 dB**. The result is the annoying hiss that shows up when the station stops transmitting: measured, the AGC hits its ceiling and the noise ends up 24 dB higher than it needs to be.

With this option, the AGC's gain is capped so the **background noise never exceeds the level you choose**. The AGC keeps adapting normally — it is not frozen — and the **Voice leveller** finishes lifting the speech, since it does tell speech from noise because it runs after the canceller.

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Noise not above** | −70 to −25 dBFS | −45 dBFS | Maximum level the background noise is allowed. Lower = quieter background. |

**"Cap applied" indicator:** shows the **noise floor measured on your input** and whether the cap is actually acting. That is what makes the control understandable, since the cap equals `ceiling − floor`:

- *"floor −38 dBFS · no effect"* — the cap exists but the AGC never reaches it. **This is normal on a strong signal**: the AGC does not want to amplify, so there is nothing to limit. The ceiling will come into play once the signal weakens.
- *"floor −38 dBFS · limiting to +7 dB"* — the cap is biting: the AGC would amplify further and we are not letting it. That is the expected working mode on a weak signal.

Use the floor it shows to pick your threshold: **set it above that value**. Below it, the cap allows 0 dB of gain and the control stops making sense.

> **This is a per-station setting, which is why it ships disabled.** The ceiling is an **absolute** level in dBFS, but the noise floor is not a universal number: it depends on your QTH, your antenna, the band, even the time of day. A value that leaves the background perfect at one station falls below the real floor at another and **limits more than it helps** — weak speech gets choked instead of improved. That is why the factory presets ship with it **off** and carry no recommended value: it is one of the few things in this application you have to calibrate **at your own station, by listening**, and revisit if you change band or antenna. If you do not hear the hiss described above, leave it off with a clear conscience.

> **Why the cap does not open abruptly (changed post-v2.2):** during a fade everything drops — signal and noise — so the measured floor collapses and the cap would swing wide open, letting the AGC amplify a lot. When the signal comes back suddenly, that accumulated gain lands as a **level jump**. To avoid it, the cap **tightens instantly** if the noise rises, but **loosens slowly** (0.5 dB per second). Measured on a 20 dB fade returning in 0.3 s, the jump on return goes from +8.9 to +4.0 dB — better even than switching the ceiling off. The only cost is that if the noise genuinely drops (a QRM source switches off) the cap takes a few seconds to let you exploit the quieter band; meanwhile it just amplifies slightly less.

> **Why a cap and not "freeze the AGC when there is no speech":** that alternative looks more direct but it deadlocks. The voice detector works on the signal already amplified by the AGC; if the gain is frozen at a low value, the detector stops firing, the freeze is never released and the returning voice comes back far too low (measured: 21 dB). A cap, by contrast, leaves the AGC adapting at all times, so it cannot get trapped.

### Interface language

The language selector (🌐 Español / English) sits in the **right corner of the status bar** (bottom edge of the window), visible from any tab. The change is saved instantly but **requires restarting the application** to take effect.

### Interface size

If text looks small on your monitor, the **🔍 100 % / 125 % / 150 %** combo — next to the language selector, in the status bar — enlarges **the whole interface at once**: type, sliders, VU meters, spectrum and buttons, keeping the exact same layout. It does not touch audio or processing. Like the language, it is saved instantly and **requires restarting the application**.

It ships at **100 %**, the size it has always been — anyone who does not need it sees no change.

> **About the options offered:** the window has a fixed width, so a larger scale takes up more screen (150 % is about 1155 px wide). The combo only offers the scales that **fit your monitor**: on a small screen 150 % simply does not appear. If you move to a smaller monitor and the saved scale no longer fits, the application falls back to 100 % on its own and says so in the status bar.

> **System alternative:** Windows (*Settings → Display → Scale*) and GNOME have their own scaling, which the application honours. The difference is that the system setting affects **every** program; this control is for RadioNoiseKiller only.

### About — and how to support the project

The **ℹ** button, also in the status bar, opens the *About* box: version, build identifier (handy if you report something), author and the link to the GitHub repository.

The same box has a **☕ Buy me a coffee** button, which opens the project's donation page in your browser:

**https://cafecito.app/gpagliaroli**

RadioNoiseKiller is free and open source (MIT licence), and it will stay that way — donating is **entirely optional** and unlocks nothing. If it has earned its place on your air, that is the way to support the work.

> **Note for donors outside Argentina:** Cafecito is an Argentine platform, but it does accept international cards. The donation goes through regardless of where you are.

### AGC presets

The **AGC** combo on the Main tab offers three speeds with fixed attack/release, all with target −20 dBFS and max gain +36 dB:

| Preset | Attack | Release | Typical use |
|--------|--------|---------|-------------|
| **fast**   | 5 ms   | 500 ms  | Protects against sharp peaks; may "pump" with SSB voice. |
| **medium** | 25 ms  | 2000 ms | Balanced — a good general starting point. |
| **slow**   | 100 ms | 5000 ms | Stable with deep QSB; the most natural for voice. |

With **off** the AGC is out of the pipeline. For SSB, *slow* or *medium* is recommended; for AM with stable signals, *off* or *slow*.

---

## Chapter 3 — Active Modules

**Location:** **Modules** tab

> **New in v1.7:** the "Active Modules" moved from the Main tab to their **own tab ("Modules",
> second in the row)**, to keep the Main tab less cluttered. The controls and their behavior are
> identical; only the location changed.

### Description

Each checkbox enables or disables one pipeline module independently and in real time. Audio keeps flowing — the module is simply bypassed while disabled.

### Available modules

| Module | When to enable it |
|--------|-------------------|
| **Impulse suppressor** | Always on bands with QRN (storms, industrial noise). Disable on clean signals to save CPU. |
| **Bandpass filter (pre)** | Almost always on. Limits the spectrum before the canceller. |
| **ANF — Removes heterodynes and tones** | Enable when you hear steady tones (whistle, hum). Disable with digital/data signals (PSK, FT8) since it would treat them as interference. |
| **Stationary noise canceller** | The main module. Enable once the noise profile has been learned. |
| &nbsp;&nbsp;&nbsp;↳ **Perceptual spectral floor** | Canceller sub-module. Replaces the fixed floor with a frequency-dependent curve: raises the floor in the vocal zone (~500 Hz, preserves voice warmth) and lowers it at high frequency (suppresses hiss harder). Curve adjustable in Advanced Canceller. |
| &nbsp;&nbsp;&nbsp;↳ **Spectral post-filter** | Canceller sub-module. Removes the "musical noise" (intermittent birdies) the Wiener filter leaves behind. Enable when you notice that artifact. Aggressiveness adjustable in Advanced Canceller. |
| &nbsp;&nbsp;&nbsp;↳ **Voice pitch enhancement** | Canceller sub-module. For very weak voice signals (AM or SSB): detects the voice's fundamental pitch and protects its harmonics from being suppressed — improves intelligibility. Enable if the voice sounds "ghostly" with the canceller at maximum. Sensitivity adjustable in Advanced Canceller. |
| &nbsp;&nbsp;&nbsp;↳ **Voice leveler** | Canceller sub-module. A voice AGC applied *after* noise reduction: keeps the clean voice at a constant level even as band conditions (and the amount of cancellation) vary. Only adapts while voice is detected — noise between transmissions is not re-amplified. |
| **Bandpass filter (post)** | Almost always on together with pre. Cleans up spectral-processing artifacts. Runs after the canceller (this list reflects the pipeline order). Its limits can be made independent from the input (see Ch. 5). |
| **Voice EQ (presence + body)** | Two parametric bands: presence (clarity, 1–2 kHz) and body (warmth, 150–800 Hz). Enable to shape the voice on weakened or heavily filtered signals. |
| **Harmonic exciter** | For dull voice signals lacking brightness. Adds presence. Compare with and without to decide. |
| **Restore bass** | Brings back the voice's fundamental when the radio's filter cut it, deriving it from the harmonics that did get through. For voices that sound thin or "telephone-like" despite a good level — above all on SSB with a narrow filter. |
| **Noise gate** | Top-level module (it does not depend on the canceller). Lowers the background between transmissions when the input level does not reach the threshold, with a progressive close instead of an abrupt cut. Runs at the end of the chain. Calibrated by watching the level indicator in Advanced Canceller (see Ch. 8). |

> **Tip — enable one at a time:** when building a configuration (or on a new signal), enable and disable the modules **one at a time**, listening to the effect each one produces. Since all changes apply live, you hear the difference instantly: that lets you tune each module better — or simply drop it if it brings nothing on that signal. Enabling everything at once makes it impossible to tell what is helping and what is not.

---

## Chapter 4 — Impulse Suppressor

**Location:** Advanced Impulse tab → "Impulse suppressor" group

### Description

Detects and attenuates short high-energy transients: atmospheric discharges (QRN), power lines, electric motors and any impulsive interference. It operates **before** the AGC and the noise canceller, with two cascaded detection levels.

- **Level 1 (10 ms frame):** detects energy bursts lasting several milliseconds, typical of large atmospheric discharges.
- **Level 2 (0.67 ms micro-frame):** detects very short impulses — crackle, static, nearby devices switching on.

Each stage has **its own indicator**, above its slider: **Frame activity** and **Micro activity**, in triggers per second (⚡ N /s). They are separate because they count things of different scale —the micro stage triggers once per 0.67 ms mini-frame and the frame stage once per block— so added together the number is dominated by the micro one: with the default values the frame stage contributed less than 10 %, and moving its threshold barely moved the needle. With two indicators you can see which of the two is working, which is what you need to adjust them separately.

> **What the thresholds mean (changed in v2.2).** Both numbers are a **contrast against the immediate neighbours**, not against the noise floor: "15×" means *fifteen times louder than the audio right next to it*. It is the same principle the ANF uses, but in time instead of frequency. The reason is that speech is **sustained** — its neighbours are just as loud, so the ratio comes out around 1 and the detector does not fire. An impulse, by contrast, is an isolated blip surrounded by nothing, and it stands out. Up to v2.1 the comparison was against the noise floor, which meant that with a signal 20 dB above the floor **every syllable crossed the threshold**: the module was not suppressing impulses, it was compressing the voice. If you had the suppressor switched off for that reason, you can turn it back on.

### Controls

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Frame threshold (10 ms)** | 2× – 30× | 15× | Sensitivity of the long-frame detector. Low = more aggressive (catches more impulses but may affect the voice). High = only blanks very strong pulses. **Lower it** if discharges remain audible; **raise it** if the voice sounds clipped. **Below 6× it also does something else** — see the note below. |
| **Micro threshold (0.67 ms)** | 3× – 30× | 8× | Sensitivity for very short crackle. Works like the previous control but on a microsecond scale. |

### Recommended values by situation

| Situation | Frame threshold | Micro threshold |
|-----------|-----------------|-----------------|
| Clean band, no QRN | 30× | 20× |
| Moderate QRN | 15× | 8× |
| Nearby thunderstorm | 8× | 5× |
| Abrupt fading surges | **4×** | unchanged |

> **The frame threshold has a second job: it puts a ceiling on level bursts.** Besides erasing
> impulses, this stage compares each block of audio against the level of the **last half second**
> and, if it exceeds it by more than the threshold says, it clips it back. Below 6× that starts to
> act on the **abrupt surges of fading**: measured on real recordings, at 4× the abruptness of the
> level jumps drops by 0.6 dB at a cost of 0.01 dB of voice.
>
> **This is the right control for that, and the micro threshold is not.** Lowering the micro
> threshold chasing the same effect gives *less* (0.56 dB against 0.62) and costs far more: with the
> micro at 4× the distortion on clean voice —with not a single impulse present— reaches **−8.7 dB**,
> worse than the defect fixed in v2.2 that was heard as a dulled voice. Leave the micro where it is
> and move only the frame threshold.
>
> The control's range was 5×–100× up to v2.3. It was changed to **2×–30×** because above 20× this
> stage barely triggers at all —so most of the travel did nothing— and the useful zone against
> fading was *below* the minimum, impossible to reach. The step is 0.25× so it can be trimmed
> down there.


---

## Chapter 5 — Bandpass Filter

**Location:** Advanced Audio tab → "Bandpass filter" group

### Description

A Butterworth IIR filter that limits the audio bandwidth to the frequencies useful for voice. It is applied at **two points** in the pipeline:

- **Pre (before the canceller):** limits the spectrum the canceller "learns" as noise. Prevents the canceller from trying to suppress energy outside the vocal range.
- **Post (after the canceller):** removes spectral artifacts that the canceller's STFT processing can introduce outside the useful band.

Both are enabled/disabled independently from **Active Modules**.

### Controls

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Input – low Hz** | 50–1000 Hz | 200 Hz | Lower cutoff. Raising it removes rumble, mains hum and motor noise; lowering it leaves more body in the voice. |
| **Input – high Hz** | 1000–10000 Hz | 3000 Hz | Upper cutoff. Lowering it removes hiss and QRM from the adjacent channel; raising it leaves more brightness and consonants. Up to 10 kHz for local AM stations with good audio. |
| **Filter order** | 2 / 4 / 6 / 8 | 4 | Filter slope. Higher order = sharper cutoff = better out-of-band rejection, but more phase latency. For normal use, order 4 is adequate. |

> **These sliders and the Bandpass combo are the same setting seen two ways.** Picking a width in the
> combo moves the sliders; moving a slider sets the combo to **Custom**. They never show different
> things, so the combo always says what is really being heard.
>
> **Widths available in the combo:**
>
> | Width | Low cutoff | High cutoff |
> |---|---|---|
> | SSB very narrow | 400 Hz | 2100 Hz |
> | SSB narrow | 300 Hz | 2400 Hz |
> | SSB normal | 200 Hz | 2700 Hz |
> | SSB wide | 200 Hz | 3000 Hz |
> | AM 3 kHz | 200 Hz | 3000 Hz |
> | AM 4 kHz | 150 Hz | 4000 Hz |
> | AM 6 kHz | 100 Hz | 6000 Hz |
> | AM 8 kHz | 100 Hz | 8000 Hz |
>
> *SSB wide* and *AM 3 kHz* are the same hertz under two names: the label is there so you can pick by
> what you are hearing, not so you have to translate in your head. And beware of the wide settings:
> they are useless if the receiver does not deliver signal up there — you can see how far it reaches
> by looking at the **Input** curve on the Spectrum tab (see that chapter).

### Output independent from input

By default, the output filter uses **the same limits** as the input one. The **"Output independent from input"** checkbox enables two dedicated sliders (*Output – low/high Hz*) to decouple them. The output has no combo: it is a fine adjustment on top of the width you already chose, and it is almost always defined in relation to the input (wider).

Why? Two identical cascaded filters double the attenuation at the band edge: the top of the voice arrives **doubly dulled**. With an independent output you can use:

- **Narrow input** (e.g. SSB up to 2700 Hz): less hiss enters the noise canceller.
- **Wider output** (3500–4000 Hz): the voice keeps its natural upper edge and the brightness regenerated by the Harmonic Exciter passes through fully. The output filter still cleans artifacts above its own cutoff.

Rule of thumb: output **equal to or wider** than the input. Narrower than the input re-clips useful signal with no benefit.

### Tips

- For **local AM stations with good music** or quality audio: raise the high Hz up to 7000–10000 Hz.
- For **SSB DX** with heavy noise: lower the low Hz to 300–400 Hz and the high to 2500 Hz to reduce band noise.
- Changing the filter order requires restarting processing (the control is disabled while active).

### Splatter from an adjacent station

**Splatter** is the intermodulation product of an overdriven transmitter spilling onto neighbouring
frequencies. It reaches your audio as the other operator's syllables, with their own speech envelope.

**The noise canceller will not remove it, and that is not a flaw:** the canceller is built on the
premise that noise is stationary, and estimates the floor by tracking minima. Something that rises and
falls with somebody else's syllables never enters that minimum. Raising the Strength does not attack
splatter — it only eats your own voice. The ANF is no help either: it is for tones, and splatter is
broadband.

**What does work is the bandpass, narrowed on the side it comes in from:**

1. Work out which side the neighbour is on. If they are *above* you in frequency, lower the **high
   Hz**; if *below*, raise the **low Hz**. Narrowing both sides just in case throws away signal.
2. Raise the **filter order** to 6 or 8. That steepens the skirt and is what pays best: more rejection
   of the neighbour without giving up your own bandwidth.
3. If you use **Output independent**, narrow the INPUT (less junk reaches the canceller) and leave the
   output wider.

> **Do not overdo the narrowing.** Consonant discrimination (/s/, /f/, /t/) lives between 2 and 4 kHz.
> Below **2.4 kHz** you start losing intelligibility, and the cure becomes worse than the disease: you
> understand less even though it sounds cleaner. Better to tolerate some splatter and keep the
> bandwidth.

**Why you cannot filter it all away:** in SSB, demodulation translates the neighbour's spectrum by the
frequency difference between you. Their sibilance, which sits at 4–7 kHz in their transmitter, can land
at 800 Hz or 2 kHz inside *your* passband. That part is **co-channel**, mixed with your voice at the
same frequencies, and no filter removes it. The bandpass trims what fell outside; what got in, got in.

> **The real fix is at the radio, not here:** a narrower IF filter, the *IF shift* moved away from the
> neighbour, or lower RF gain if the splatter is pumping your receiver's AGC.

---

## Chapter 6 — ANF: Spectral Notch Filter

**Location:** Advanced Impulse tab → "ANF — Removes heterodynes and interfering tones" group

### Description

The **ANF** (Adaptive Notch Filter) automatically detects steady or nearly steady tones in the spectrum — heterodynes, AM carriers from adjacent stations, mains hum (50/60 Hz and its harmonics) — and attenuates them without affecting the surrounding voice audio.

The algorithm compares each FFT bin's magnitude with the median of its neighbors. If a bin exceeds N times the surrounding level, it is considered a tone and a notch is applied. It has no state between frames, which makes it very reactive but also keeps it from "chasing" voices.

The **Activity** indicator shows how many tones are being notched at this moment.

> **Important:** Do not use the ANF with digital signals (FT8, PSK31, WSPR, etc.). Those signals have a spectral structure the ANF interprets as tones to remove.

### Controls

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Sensitivity** | 1.5× – 10× | 3.0× | Minimum bin/surroundings ratio to consider a tone. **Lower it** (1.5–2.5×) to catch weak tones that barely stand out. **Raise it** (5–10×) to be more selective and only remove very strong interference. |
| **Depth** | 0% – 100% | 50% | How much the detected tone is attenuated. 100% = silences the bin completely. 50% = 6 dB reduction. Up to v2.1 high values muffled the voice, but **the cause was the ANF mistaking voice harmonics for tones**; with persistence-based detection that no longer happens (measured: 0 % false positives and 0.0 dB of loss on voice with no heterodynes). The default stays at 50 %, but **you can now raise it to 90–100 % without dulling the voice** — if you were holding back for that reason, re-tune it by ear. |

---

## Chapter 7 — Stationary Noise Canceller

**Location:** Main tab → "Stationary Noise Cancellation" group and Advanced Canceller tab → "Stationary noise canceller" group

### Description

This is the application's core module. It implements a spectral **Log-MMSE Wiener filter** with a DD (Decision-Directed) estimator that reduces stationary background noise — band static, white noise, propagation noise — while preserving the voice.

The Log-MMSE estimator (Ephraim & Malah, 1985) computes the optimal gain bin by bin, minimizing distortion on a logarithmic scale, which matches auditory perception. This produces less residual "metallic" quality in the voice compared to the classic Wiener filter, especially on weak signals.

### Noise estimation modes

The canceller offers two modes, selectable from the **Mode:** selector in the *Noise canceller* group on the Main tab (not to be confused with the **Bandpass** combo, which picks the filter width):

**Static profile** (manual mode)
The algorithm learns a "photo" of the background noise over a few seconds and uses it as a fixed reference. Ideal when the band noise is very stable.

1. **Find a noise-only gap** — a moment with no signal, when the station is not transmitting.
2. Press **⏺ Learn noise** and wait 3–5 seconds.
3. Press **⏹ Stop** — the profile is stored and applied.
4. If conditions change a lot, repeat the process.
5. **Clear profile** resets the reference.

> **Important — learn noise only:** it's best to **tune slightly off frequency** to a spot on the dial **with no stations** (just the band's background noise), learn there, and only then return to the station. If some **voice or a carrier** slips in during learning, that energy gets "baked" into the noise profile, and the canceller then subtracts it as if it were noise — you'll hear artifacts and holes over the real voice. The profile should be a snapshot of **pure noise**, not of the signal.

During learning the application takes two automatic measures to capture a faithful profile:

- **The AGC is frozen.** Without this, the AGC would progressively amplify the band noise up to its target level and the profile would capture a sweep of levels instead of a stable one.
- **Monitoring is attenuated −12 dB.** Listening to raw noise at full volume for 3–5 seconds is unpleasant; the attenuation only affects what you hear — the algorithm analyzes the signal at full level.

Both measures are released automatically when you press ⏹ Stop (or cancel learning).

**Named noise profiles** (save and reuse)

Learning the profile every time you open the application is tedious. With the **"💾 Save profile..."** and **"📁 Profiles..."** buttons (under Learn/Clear, static mode only) you can save the current profile under a name and load it again when needed:

1. Learn a profile as usual (or load a saved one and re-adjust).
2. **💾 Save profile...** → type a descriptive name ("40m home", "20m field", "laptop noise").
3. In another session, **📁 Profiles...** → pick the profile from the list to load it instantly, without learning it again.

Profiles are stored as `.json` files in the **`PerfilesRuido/`** folder next to the executable (they can be backed up or copied between machines). Loading a profile automatically switches the canceller to static mode.

**Auto-reload:** the last profile saved or loaded is remembered across sessions — when you open the application it is applied automatically (the status bar confirms it), so you start operating with a reference without re-learning anything. If the profile was learned with a different block size, it adapts automatically by interpolation.

**Adaptive (MCRA)** (automatic mode)
The algorithm estimates the noise floor continuously in real time, with no manual learning. It calibrates in ~200 ms when processing starts and adapts automatically when propagation conditions change, QRM appears or the band noise varies.

- Requires no user intervention — it just works.
- The Learn/Clear buttons are hidden (they don't apply in this mode).
- The status indicator changes from "calibrating..." to "estimating in real time" once ready.
- **Recommended** for long listening sessions where band conditions vary.

**Protection against learning the voice**

MCRA's minima tracking has a known weakness: with **sustained speech** — a long transmission
without pauses — the minima window ends up absorbing the voice itself, the estimated floor rises to
its level and the canceller starts subtracting the very voice it should preserve. It shows up as
clearly audible voice in the *Preview*, and as slightly dulled voice in the output, no matter where
Intensity is set.

To prevent it, frames containing speech **do not feed** the estimator. The detection uses the
signal's **periodicity** (autocorrelation), not its level: a rise in band noise — however large —
is not periodic and therefore freezes nothing, so the estimator keeps chasing the noise as always.
A 300 ms hold covers the unvoiced parts of speech (fricatives are not periodic). It is automatic
and has no controls.

**Floor memory across carrier squelch**

When the radio's squelch cuts the carrier (total silence between transmissions), the MCRA automatically detects that the frame energy has dropped far below the estimated noise floor and **freezes** the estimator's entire state: it updates neither the spectral smoothing, nor the minima tracking, nor the noise estimate `λ_d`. When the signal returns, the algorithm resumes from exactly the memorized profile — with no re-calibration period and no audible noise at the start of the transmission.

This behavior is automatic and requires no adjustment. It triggers when the signal drops more than 13 dB below the estimated floor, which distinguishes a real squelch (carrier cut) from a normal pause between words where band noise remains present.

> **Note — "HF fading compensation" was removed in this version.** It was meant to freeze the estimator during QSB, but measurement showed its detector fired on **syllables**, not on fades: speech energy swings about 17 dB between syllable and gap, the same order as the fade it was looking for. Even with a perfect detector the module recovered only 2.4 dB, and only when the noise faded together with the signal.
>
> **Against QSB the tool is the Voice leveler** (Ch. 7), specifically its *Response speed*: lowering it from 1500 to 200 ms halves the level swing the processing adds. See the tip in Ch. 7.

### Real-time indicators (Advanced Canceller)

| Indicator | Description |
|-----------|-------------|
| **Reduction (dB)** | How much noise is being reduced right now. Green = strong reduction (>10 dB). Yellow = moderate reduction. |
| **Voice (%)** | Probability that the current frame contains voice (the smoothed signal used internally by the Wiener filter). |
| **Preview: listen to removed noise** (Main tab, next to *Extra reduction*) | Inverts the output so you hear **everything the canceller is subtracting** — it reflects the **full reduction: Intensity + Post-filter** (plus the perceptual floor). While it is active the **noise gate, voice leveller, presence/body EQ and exciter are skipped**: they are colouring stages that trigger precisely when there is speech, so they would falsify the diagnosis (a barely audible voice remnant would come out levelled, boosted at 1.5 kHz and with new harmonics). The output bandpass — which defines the band you are listening to — and the limiter are kept. Useful for checking that no voice is being removed: if you hear voice in the preview, something is too aggressive. |

### Advanced controls (Advanced Canceller tab)

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Intensity** | 0% – 100% | 70% | How much reduction is applied on top of the computed gains. **0%** = no reduction (audio passes unchanged). **100%** = full reduction. The scale is non-linear: mid values (50–70%) already produce a noticeable reduction, while voice bins are minimally affected at any position. Start at 70% and raise it according to the noise level. |
| **Spectral floor** | 0.05 – 0.30 | 0.15 | Minimum gain applied to any bin, even the noisiest. 0.10 means no bin is ever silenced by more than 90% of its energy. **Never go below 0.05** — very low values with a high Anti-warble produce severe warbling. |
| **Anti-warble (β)** | 90% – 99% (0.1% steps) | 96% | Doses two mechanisms against background musical noise: the canceller *release* and, above all, the **smoothing of the per-bin voice/noise classification** (prevents a bin flickering around the threshold from making its gain jump — the main cause of persistent background "warble"). **Useful range 96–98%, very condition-dependent.** Raise it if you hear warble or background birdies; lower it (90–95%) if the voice gets a noise "tail" or sounds sluggish. The extreme (99%) gives maximum anti-warble but leaves the longest tail after each transmission. |
| **Attack speed** | 50% – 92% | 80% | How fast the canceller "opens" voice bins when a signal is detected. Fast (50–70%): crisper consonants. Soft (>85%): fewer transition artifacts. |
| **Floor reactivity** *(Adaptive only)* | 250 – 800 ms | 800 ms | Window over which the MCRA estimator tracks the noise minimum. **Reactive (250–350 ms):** the floor follows fast cyclic rises and falls of the noise without lagging (less "swaying" of the sound). **Stable (800 ms):** better for steady noise. Lower it when the band noise rises and falls suddenly in short cycles. With very reactive values, keep **Voice pitch enhancement** on (protects the harmonics from a short window mistaking them for noise). |
| **Fall brake** *(Adaptive only)* | 2 – 30 dB/s | 30 (no brake) | Limits how fast the estimated floor may go **down**; going up is always free. When band noise rises suddenly the output jumps because the floor arrived late — if the floor did not sink during the quiet stretches, it has less to catch up. **It costs voice**, and how much depends on the S/N (see the tip below). |
| **Freeze floor on voice** *(Adaptive only)* | 30% – 100% | 30% | How periodic the audio must be for the estimator to **stop updating** the floor while there is voice. The estimator learns the noise on the frames where it detects no voice; if the transmission is continuous it runs out of material and the floor arrives late to the changes. Raising it lets more frames feed it (100% = never freezes), at the cost of some voice leaking into the floor. 30% is the behaviour of earlier versions. |
| **HF floor boost** | 0% – 150% | 0% | Raises the estimated noise floor above ~2.5 kHz, where noise energy is low and the estimator reacts late. Suppresses the HF hiss that leaks through with fading better. The curve is **logarithmic**: each octave above 2.5 kHz adds more boost, so it acts progressively harder the higher the frequency. **Cost:** it can dull the voice's brightness a bit — compensate with the **Harmonic exciter** or the **Presence EQ** (they regenerate brightness after the canceller, without bringing the noise back). |

> **The ones marked *(Adaptive only)* appear greyed out in Static profile mode**, and that is not an
> oversight: all three act on the floor that Adaptive mode estimates continuously. In static mode the
> floor comes from the profile you learned and is fixed, so there is nothing to react, to brake on
> the way down, or to freeze. The **HF floor boost** does work in both modes: it multiplies the
> floor whatever its source.

> **Careful with the HF floor boost: it only helps if your receiver delivers noise up there.** The ramp
> starts at ~2.5 kHz and grows towards the high frequencies. If the radio's audio is cut off before
> that —you can check it by looking at how far the **Input** curve reaches on the Spectrum tab— the
> ramp lands in a region where there is no noise left to suppress but there are still consonants, and
> all it does is eat them. Measured on such a receiver, the boost at 100% cost **1.0 to 1.6 dB of
> voice** (3.6 dB between 2.5 and 3.5 kHz, precisely the consonant band) in exchange for 0.2 dB of
> background. That is why the factory presets ship it at 0%.

> **Tip — "Freeze floor on voice" is for continuous transmissions.** The adaptive estimator can only
> measure the noise during the stretches where it detects no voice. On a normal QSO, with pauses
> between words, it has material to spare. But with **continuous voice** —a broadcast station, an
> operator who never stops, music— the freeze engages almost all the time and the floor stops
> following the changes in band noise: it sounds as if the cancellation arrived late to every rise.
> Raising the control loosens that freeze.
>
> The price is real: with the control at 100%, sustained voice raises the estimated floor by some
> 10 dB, and then the canceller subtracts too much. That is why the end of the travel is for trying,
> not for leaving set. The factory presets use a **different value in each one** (between 30% and
> 100%), which is the short way of saying that this is chosen per condition and there is no single
> good value.

> **Tip — the Fall brake is chosen by S/N, not by taste.** It is the kind of control that is free on
> one band and ruins the voice on another, so it is worth understanding what it charges. When band
> noise rises suddenly the output jumps because the estimated floor arrived late; the brake keeps
> that floor from sinking during the quiet stretches, so it has less to catch up. The catch is that a
> higher estimated floor also subtracts more from the voice.
>
> **That cost depends almost entirely on the S/N**, measured with a real 8 dB noise rise:
>
> | S/N (indicator on the Spectrum tab) | Voice the brake costs |
> |---|---|
> | +12 dB or more | practically nothing (0.03 dB) |
> | +6 dB | negligible (0.2 dB) |
> | 0 dB | ~1.2 dB |
> | −6 dB | **~2.5 dB** |
>
> **In practice:** with a comfortable signal — local AM, a strong station — you can run it at
> **10 dB/s** at no cost, and the background is noticeably steadier. With a weak signal buried in
> noise — shortwave with high QRN — leave it at **30 (no brake)**: there the voice has no margin to
> pay from, and what you gain in the background you lose in clarity. That is why it ships with no
> brake.
>
> It is a **per-condition** setting, not a preference: since it travels in the preset, each profile
> carries the value that suits the band it was built for.

> **Tip — calibrating Intensity with the Preview:** enable **"Preview: listen to removed noise"** and raise the **Intensity** while listening to what is being removed: as long as the preview contains only noise, you can keep raising it; at the point where voice starts leaking into the removed audio, back off one step and leave it there. That is the maximum cancellation that does not touch the voice. Disable the preview when done.
>
> **Important:** the preview reflects the **total reduction (Intensity + Post-filter)**. To calibrate **Intensity alone**, first set the **Post-filter to 0** — that way what you hear in the preview is only what the Intensity removes. Once the Intensity is set, raise the Post-filter (and, if you like, re-check with the preview that the post-filter isn't taking voice either).

> **Recipe — shortwave noise that rises and falls in short cycles:** a typical problem is band noise fluctuating several dB cyclically and fast, while the signal stays at a steady level. Without tuning, the estimator lags: on the rise it lets noise through, on the fall it eats the voice — a "swaying" of the sound. The combination that fixes it, all in **Adaptive mode**:
> 1. **Floor reactivity** at **250–350 ms** — so the floor follows the noise's rise and fall.
> 2. **HF floor boost** at **50–100%** — for the treble hiss the estimator can't follow on its own.
> 3. **Voice pitch enhancement** on — protects the voice harmonics from the reactive window.
> 4. Against **QSB**, the knob is the Voice leveler's *Response speed* (Ch. 7), not the canceller.
> 5. If the voice brightness got dull from the HF floor boost, compensate with the **Harmonic exciter** (drive 2–3×) or **Presence EQ** (+4–6 dB at 2 kHz).
>
> Watching the **Spectrum** tab, the goal is for the floor line (yellow) to follow the noise's rise and fall instead of lagging behind.

### Floor vs. Anti-warble

These two parameters interact. The practical rule:

| Situation | Floor | Anti-warble |
|-----------|-------|-------------|
| Radio with good S/N | 0.10 | 97% |
| Radio with variable noise | 0.15 | 97–98% |
| Very weak signal, heavy noise | 0.15–0.20 | 98% |

**Low floor + low anti-warble** inevitably produces warbling. Raise the floor first, then adjust the anti-warble.

### Perceptual spectral floor

**Enable:** Active Modules → "Perceptual spectral floor (auditory masking curve)" checkbox  
**Adjust:** Advanced Canceller tab → "Perceptual spectral floor" group

The standard **Spectral floor** control applies the same minimum gain at all frequencies. But the ear does not perceive residual noise equally across bands: in the vocal-fundamentals zone (~300–800 Hz) a slightly higher floor sounds more natural and warm, while above 3 kHz residual noise (hiss) is the most annoying and is worth suppressing harder.

This module replaces the fixed floor with a three-zone curve:

- **Vocal boost:** the floor rises around the configured center frequency (default 500 Hz). Preserves voice warmth.
- **Neutral zone** (1–3 kHz): unchanged — formants pass with the base floor.
- **Treble rolloff:** above the configured start frequency, the floor drops progressively. Suppresses high-frequency hiss harder.

**Real-time indicators:**

| Indicator | Description |
|-----------|-------------|
| **Vocal floor** | The floor value at the maximum-boost frequency, in % and in dB relative to the base floor. E.g. "25% (+8.0 dB)" means the floor at the vocal center is 0.25 while the base is 0.10. |
| **Active** | Percentage of spectrum bins the floor is currently holding up. **If it reads 0%, the module is having no effect** — the Wiener filter is already producing gains above the floor and moving the sliders will change nothing audible. With band noise present, 20–50% is normal. |

**Controls:**

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Vocal boost amount** | 0% – 250% | 75% | How much the floor rises in the vocal zone relative to the base floor. 75% = soft, 150% = normal, 250% = strong. Raise it if the voice sounds "cold" or hollow with the canceller active. |
| **Boost center** | 200 – 1200 Hz | 500 Hz | Frequency of maximum boost. 400–600 Hz for male voices, 600–900 Hz for female voices. |
| **Rolloff start** | 1000 – 6000 Hz | 3000 Hz | Frequency where the floor starts dropping. **On SSB (narrow band ~2.7 kHz), lower it to 1500 Hz** — with the 3000 default the rolloff starts above the band and never engages. |
| **Rolloff depth** | 0% – 95% | 55% | How much the floor drops at the treble end → more high-hiss suppression. 55% ≈ −7 dB. More depth = less residual hiss, at the cost of slightly dulling the voice's highs. |

> **Tip — barely noticeable on SSB:** the Depth's effect concentrates above the "Rolloff start". If you're on SSB and don't notice it, **don't raise the Depth — lower the "Rolloff start"** to ~1500 Hz so the rolloff falls inside your band. On AM (wider band) the effect shows directly. In v1.7 the ramp is steeper (reaching full depth near the band edge) and the maximum went from 70% to 95%.

> **Tip:** use the **Active** indicator as a guide. If it reads 0% consistently, the base floor (the "Spectral floor" control) is already below the gains the Wiener computes and the perceptual curve never engages — in that case the relevant adjustment is the canceller's Intensity, not this curve.

### Spectral post-filter

**Location:** Main tab → **"Post-filter"** slider, right below Intensity (it is the second most impactful control after it). Raising the slider above 0 **turns the post-filter on by itself**; at 0 it is off — nothing else to touch. (The equivalent checkbox is still in Active Modules for advanced users, synced with the slider.)

Even a well-configured Wiener filter can leave a very particular artifact called **musical noise**: instead of the original uniform background noise, short intermittent birdies appear, varying randomly from bin to bin. It is the residue of bins the VAD marked as noise but that were not fully suppressed by the spectral floor.

The post-filter uses that same voice-probability information to **push the floor of those bins down**: where there is residual noise (`p_speech ≈ 0`) the floor drops about **4.5 dB per slider point**; on voice bins (`p_speech ≈ 1`) nothing changes.

That deepening is **independent of Intensity**: it is applied after it, so raising the Post-filter lowers the background without having to raise Intensity. That is what makes the "low Intensity + high Post-filter" recipe below work.

What matters is that this deepening is a **fixed** amount, not a multiplier on the gain. Radio noise naturally fluctuates some 6 dB from instant to instant; the previous design multiplied that fluctuation by the slider value (with the slider at 6, those 6 dB became nearly 40), which is why what remained in the background was not an even hiss but isolated peaks — the warble itself. Subtracting a fixed amount leaves the background **lower and steadier**, and it also leaves alone the voice bins with intermediate probability, which used to take the same punishment.

**Real-time indicator:**

| Indicator | Description |
|-----------|-------------|
| **Extra reduction** (below the slider) | How many additional dB the post-filter is removing on noise bins, beyond what the base canceller already does. Green above −5 dB, yellow between −0.5 and −5 dB, gray when there is no active noise or the module is disabled. Lets you verify at a glance that the Post-filter slider is having real effect. |

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Post-filter** | 0.0 – 10.0 | 1.0 | How far the floor of the noise bins is pushed down: **~4.5 dB per point**. **0** = off. **1** = −4.5 dB. **2** = −9 dB. **6** = −27 dB. **10** = −45 dB, with an internal ceiling of −60 dB total gain. Start at 1.0 and raise it, watching the Extra reduction indicator, until the background is even. |

> **Note:** the post-filter **does not touch the voice bins**, so raising it does not dull or clip the voice — unlike the previous design, where the high range also punished intermediate voice/noise bins. What high values do change is the character of the background: above ~6 the silence between words gets very "dead", which some operators find unnatural and others find restful on long watches. It is a matter of taste, not damage to the signal.

> **Tip — low Intensity + high Post-filter:** a very effective combination is to **lower the canceller's Intensity** (50–60%) and compensate with a **high Post-filter** (5–8). With both sliders together on the Main tab (Intensity + Post-filter), this is the most direct recipe for the user who doesn't want to go into the Advanced tabs. The low Intensity lets the voice through almost untouched — without the dullness that appears when raising it — while the post-filter handles the remaining noise, acting only on the bins the detector marks as noise. On many signals this yields better cancellation **with a more natural voice** than raising the Intensity alone. It is worth trying both approaches on each signal and keeping whichever sounds best.

### Voice pitch enhancement

**Enable:** Active Modules → "Voice pitch enhancement (autocorrelation detection)" checkbox  
**Adjust:** Advanced Canceller tab → "Harmonic protection" slider

On very weak voice signals buried in noise, the Wiener canceller can suppress the voice harmonics along with the noise because the VAD cannot tell them apart. The result is a voice that sounds "ghostly", with shifting tone or lost naturalness.

This module detects the voice's **fundamental pitch** (f0) in real time via autocorrelation over a 42 ms window, searches for f0 in the 80–400 Hz range, and raises the voice probability (`p_speech`) on all bins corresponding to harmonics of that f0. The canceller then treats them as voice and lets them through.

- Detection uses a **confidence threshold**: if the signal is not periodic enough (no clear voice), nothing is modified.
- **3-frame hold:** on brief detection gaps, the last valid f0 is kept to avoid fluttering.
- **Works on both AM and SSB.** On AM, demodulation preserves the voice's harmonic structure exactly, so detection is just as reliable; the confidence threshold protects in very noisy conditions. On SSB, an off-tune BFO shifts the harmonics and can degrade detection — adjust the clarifier if the indicator never detects.

**Real-time indicator:**

| Indicator | Description |
|-----------|-------------|
| **Detected pitch** | The voice's f0 in Hz, in real time. Green = detection active (the harmonic mask is protecting the voice). "no detection" (gray) = no periodic signal — the module is in passthrough. With clear voice it should read a stable value between 80–400 Hz; if it flutters erratically or never detects, the signal is too noisy or (on SSB) the radio's clarifier is off-tune. |

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Harmonic protection** | 0% – 100% | 70% | How much `p_speech` is raised on harmonic bins. **70%** is the balance point: protects the voice without degrading noise suppression. **>85%**: harmonic bins are almost never suppressed — useful for very weak signals. **<40%**: minimal effect. |

> **It depends on the block size, and that is worth knowing.** To protect a harmonic
> without touching what sits next to it, the application needs enough resolution to
> tell them apart: harmonics are spaced by the voice pitch (80–400 Hz), and the width
> of each analysis bin is set by the **block size** (Advanced Audio). With small
> blocks (240–480) and a low-pitched voice, two neighbouring harmonics land in
> adjacent bins and the protection stops being selective: it behaves as a flat floor
> across the whole band, costs noise suppression and does not deliver what it
> promises. If you want to use this module, use **block 960 or 1920**. Up to v2.2 the
> effect was much worse, and it also changed on its own when you changed the block
> size, with nothing to indicate it.

> **When to enable it:** when the voice sounds "ghostly" or "robotic" with the canceller in MCRA mode or at high intensity, on weak AM or SSB signals — it improves intelligibility in both modes. Under normal conditions, leave it off.

### Voice leveler

**Enable:** Active Modules → "Voice leveler (compensates band conditions)" checkbox  
**Adjust:** Advanced Audio tab → "Voice leveler" group

In a real listening session the level of the clean voice varies constantly: propagation changes, stations change, and the amount of noise cancellation itself removes more or less energy depending on conditions. The leveler is an **AGC dedicated to the voice** that works *after* the canceller — that is, on the already-clean audio — and brings it to a constant level.

The difference from the general AGC (Ch. 2) is the **voice-detection gate**: by default the leveler only adapts its gain while the canceller's voice detector confirms voice is present. With noise or silence the gain stays **frozen** at its last value — residual noise between transmissions is not re-amplified, which is the typical flaw of chaining two ordinary AGCs. This gate can be disabled (**"Level continuously"** checkbox, see below) for **music or continuous audio**.

**Requires the Stationary noise canceller enabled with a profile** (learned or MCRA-calibrated) — the voice detector lives inside the canceller. The target (−20 dBFS) and attack (80 ms) are fixed; the **response speed (release) is adjustable** so it can follow faster or slower fading.

**Real-time indicators:** the gain the leveler is applying is shown in two places with the same data — on the Main tab (next to the peak limiter indicator) and as **"Activity"** inside the group itself in Advanced Audio, so you can watch it while adjusting the Max gain. Green while compensating, gray "0 dB" when the voice is already at level, "—" when the module is not running.

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Max gain** | 0 – 20 dB | +12 dB | Amplification cap for weak voice. Raise it for DX signals far below the target level; lower it if a strong station arriving after a weak one starts off too loud. At 0 dB the module only attenuates (never amplifies). |
| **Response speed** | 200 – 3000 ms | 1500 ms | How fast the leveler follows level changes (the AGC *release*). **Fast (200–600 ms):** follows fast cyclic fading without leaving volume "dips" when the signal drops. **This is the main control against QSB:** measured on a 20 dB fade, lowering it from 1500 to 200 ms halves the level swing the processing adds. The price is more abrupt gain steps; if you hear them, lower *Maximum gain* rather than slowing the speed back down. **Smooth (2000–3000 ms):** more stable leveling, less risk of pumping the background noise. |
| **Level continuously (music)** | checkbox | off | *(The checkbox lives on the **Main** tab → "Control" group, below the AGC selector — you change it depending on what you are listening to, so it stays in sight.)* Disables the voice-detection gate: the leveler adapts **at all times**, without waiting for voice. **Enable for music or continuous audio** — where the voice detector does not recognize voice structure and, with the gate, the leveler would stay frozen. For voice on noisy bands leave it **off** (avoids re-amplifying noise in the gaps). |

> **When to enable it:** long sessions with stations at very different levels or pronounced QSB, especially with the noise gate active (level jumps between transmissions are more noticeable when there is no background noise to mask them).

> **Music with fading (cyclic QSB):** enable the Leveler, tick **"Level continuously"**, raise Max gain to ~15 dB and lower the **Response speed to 400–600 ms**. This way the leveler tracks the signal's cyclic rise and fall instead of staying frozen waiting for a voice that never comes. If it starts to "breathe" the background noise, raise the speed one step. Related note: against QSB you want to **raise** the Spectral floor (Ch. 5), not lower it. Measured on a 20 dB fade: moving the floor from 0.10 to 0.20 brings the level swing down from 28.9 to 24.7 dB. The reason is that the swing is added by the canceller itself — as the signal drops the SNR falls and the Wiener gain with it, so the output falls further than the input — and the floor limits how far that gain can fall. The cost is about 2 dB less noise suppression. *(Corrected after measuring it: up to v2.2 this note said the opposite.)*

---

## Chapter 8 — Noise Gate

**Location:** Modules tab → "Noise gate"  
**Advanced settings:** Advanced Canceller tab → "Noise gate" group

### Description

Lowers the background between transmissions. While the **input level** stays below the threshold, the output is attenuated; as soon as it rises above it, the audio passes untouched.

> **It replaces the Voice squelch** of earlier versions. That one decided using the canceller's voice detector, and that criterion had two fundamental problems. One: **it could not be calibrated**. The threshold was a percentage of a probability that appears on no screen of the radio, so it could only be adjusted by trial and error. Two: **the detector is not reliable with weak signals** — it is computed on the estimated signal-to-noise ratio, which in turn depends on the noise estimator; measured on real recordings it read **higher on noise rises than on real voice onsets**. The gate decides using a figure you can actually see: the input level in dBFS.

Three design decisions, all three measured:

**It decides on the input and acts on the output.** Muting the input looks like the natural choice, but it leaves the noise estimator measuring the very silence the gate manufactures: measured on a real recording, a gate placed on the input sinks the estimated floor by **9.5 dB**, while the same gate applied to the output leaves it identical. And it would close precisely during the pauses, which are the only moments when Adaptive mode can measure the band noise.

**The threshold is absolute, in dBFS.** That is what lets you calibrate it by watching the indicator instead of blindly. In exchange it is **not portable**: the level the radio comes in at depends on the station, the antenna and the receiver's volume, so it is a per-station setting — the same case as the AGC's *Noise ceiling*. It travels in the preset and ships disabled.

**It attenuates instead of silencing.** With the gate closed the background drops by whatever *Depth* says, not necessarily to zero. On HF, 15–25 dB usually sounds far more natural than digital silence, which feels like the radio just died. The maximum of the control does silence completely.

The close is **progressive**: when the signal drops, the gate holds full volume during the first half of the *Hold* (pauses between words are untouched) and fades during the second half. If the signal returns at any point, it reopens instantly and without clicks.

**It does not require the canceller.** It is a top-level module: it works with the canceller off, and it is even useful on its own, to lower the background of a noisy band between transmissions. The squelch it replaces did depend on the canceller, because it used its voice detector.

**With music** the gate is no longer the nuisance the squelch was: it does not look for voice structure, only at the level. Even so, if the music has quiet passages that fall below the threshold, it will attenuate them — in that case lower the threshold or leave *Depth* at a small value.

### Real-time indicators (Noise gate group, Advanced Canceller)

| Indicator | Description |
|-----------|-------------|
| **Input level** | Level of the incoming signal, in dBFS, measured **before the AGC** and with the same smoothing used to compare it against the threshold. Next to it, the chosen threshold ("opens at"). This is the calibration tool: with these two numbers the adjustment stops being blind. |
| **Gate** | Current state: **OPEN** (green, audio passes untouched) or **CLOSED** (grey, the background is attenuated). It stays OPEN throughout the Hold. |

### Controls

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Threshold** | −80 to −20 dBFS | −50 dBFS | Input level at which the gate opens. Pick it between the level the indicator reads in the gaps and the level it reads with signal. If it cuts weak voice, lower it; if it opens on noise alone, raise it. **It is a setting for your station** — worth reviewing when you change band, antenna or time of day. |
| **Depth** | 0 to 60 dB | 20 dB | How much the background drops while the gate is closed. At 0 dB the gate attenuates nothing (it is inert); 15–25 dB is the natural range on HF; the maximum silences completely. |
| **Hold** | 50 to 2000 ms | 300 ms | How long the gate stays open after the signal drops, so it does not cut between words. Full volume during the first half, fade during the second. Short for fast conversation; 500–1000 ms for operators with long pauses. |

### Calibration

1. Enable the gate in the Modules tab and open **Advanced Canceller** to see the **Input level** indicator.
2. With the radio on a gap (no transmission), note the level it reads.
3. With a transmission under way, note the level it reads.
4. Set the **Threshold** between those two values, closer to the gap reading than to the signal one.
5. Listen: if it cuts word onsets or weak voice, lower it a step; if the gate opens on noise alone, raise it.
6. Adjust **Depth** to taste (15–25 dB is a good starting point) and **Hold** if it clips word endings.

> **If the two levels are nearly the same**, the gate has no margin to work in: the signal does not rise above the band noise. What is needed there is the canceller, not the gate.

> **Migrating from the Voice squelch:** presets saved with earlier versions load without a problem — the squelch keys are ignored and the gate takes its factory values, that is, **disabled**. If you used the squelch, enable the gate and calibrate it with the procedure above; there is no automatic conversion because the two thresholds measure different things.

---

## Chapter 9 — Voice EQ (Presence + Body)

**Location:** Advanced Audio tab → "Voice EQ" group  
**Enable:** Active Modules → "Voice EQ (presence + body)" checkbox

### Description

Two independent peaking EQ filters working on the two zones that define the character of a voice:

- **Body (150–800 Hz):** the zone of the voice fundamentals. Boosting it adds warmth, weight and "body" — useful when the voice sounds thin or telephone-like, which is common after bandpass filtering and noise reduction.
- **Presence (1000–2000 Hz):** the zone where the ear best discriminates consonants. Boosting it adds clarity and intelligibility — useful when the voice sounds "dull" or propagation attenuates the highs.

Both bands can be used at once: body +4 dB and presence +4 dB produce a fuller, clearer voice than either alone. Each band at 0 dB gain is exact passthrough (no processing cost).

### Controls

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Body frequency** | 150 – 800 Hz | 350 Hz | Center of the body peak. 250–400 Hz for male voices, 400–600 Hz for female voices. The width is fixed (Q 0.9 — roughly one octave). |
| **Body (gain)** | -3 dB to +10 dB | 0 dB | How much the voice body is boosted. +3 to +5 dB is the useful zone; beyond +6 dB it can sound "tubby". Negative values are also allowed to tame excessive lows. |
| **Presence frequency** | 1000 – 3000 Hz | 2000 Hz | Center of the boost peak. 2000 Hz emphasizes consonants (s, t, f). 1000–1500 Hz reinforces the midrange. **2500–3000 Hz only makes sense on AM**, where the bandpass reaches 4–5 kHz: on SSB the band ends around 2.7–3 kHz and the output filter eats the boost. |
| **Presence (gain)** | -3 dB to +10 dB | 0 dB | How much the center frequency is amplified. Start with +3 to +6 dB and adjust to taste. |
| **Q (selectivity)** | 0.2 – 2.0 | 0.7 | Width of the presence peak. Low Q (0.2–0.4) = wide peak, affects a broad band. High Q (1.5–2.0) = narrow, very selective peak. For radio voice, Q between 0.5 and 1.0 is typical. |

> **Tip:** if the voice loses body when the noise canceller is enabled, first try the **Perceptual spectral floor** (Ch. 7), which prevents the loss at the source. The body EQ compensates after the fact — the two approaches complement each other.

---

## Chapter 10 — Harmonic Exciter

**Location:** Advanced Audio tab → "Harmonic exciter" group

### Description

Generates artificial harmonics in the 1–4 kHz zone to restore the sense of "brightness" and "presence" lost to bandpass filtering and noise reduction.

The process takes the intelligibility band (1–3.5 kHz), saturates it with the *tanh* function, **subtracts everything that was already in the original signal** and mixes back only what is left: new harmonics, landing inside the voice band (an internal 7 kHz ceiling keeps them out of the fizz region).

That subtraction is what separates an exciter from an equalizer, and it is worth understanding because up to version 1.9.1 it was not done properly: what got mixed back contained a copy of the band itself, so the module was really a +1.8 dB treble boost — with the harmonics 58 dB down, i.e. inaudible — and that boost rose and fell with the signal level. Much of the metallic character came from there. Now the band's level is untouched (measured: ±0.05 dB) and what is added are genuine harmonics.

The effect is that of an analog exciter: the voice sounds more "airy", with more attack on consonants, without increasing the physical audio level.

**It is not a substitute for the presence EQ** — they are complementary. The EQ amplifies what exists; the exciter generates new energy correlated with the voice present.

With the **canceller enabled and a profile learned**, the exciter only acts while there is speech: between words it closes by itself. It runs at the end of the chain, so without that gate it brightened the residual noise just as much as the voice (+2 dB of hiss between words). Without the canceller there is no voice detection available and it works all the time, as before.

### Controls

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Drive** | 1.0× – 10.0× | 2.0× | How much saturation is applied before extracting the harmonics. **Soft (1–3×):** few harmonics, low order, subtle effect. **Aggressive (6–10×):** more harmonics and of higher order, stronger effect but it can sound hard. The effect **does not depend on signal level**: the stage normalizes itself, so it sounds the same on strong or weak signals. Start at 2.0×. |
| **Mix** | 0% – 100% | 30% | How much of the generated harmonics is added back to the original audio. **20–40%** is the useful zone — noticeable without sounding artificial. Above 60% the effect becomes very pronounced. |
| **Character** | 0% – 100% | 0% (odd) | Which harmonics are generated. **Odd (0%)**: *tanh* saturation is symmetric and produces only 3rd, 5th, 7th — bright but somewhat hollow, the classic "metallic" timbre. **Even (100%)**: 2nd and 4th, warmer and fuller. **Mixed (30–60%)** is usually the best compromise. It is a **timbre** crossfade, not a level one: moving the control does not change the volume. |

> **The price of even harmonics:** any even nonlinearity generates, besides the 2nd harmonic, **difference products** between the voice's partials, which land in the low end and are heard as mud. The even branch is high-passed above 2 kHz precisely to contain them (measured: −39 dB below the signal with that filter, versus −21 dB if filtered at 600 Hz), but the effect exists. If raising Character gains warmth but loses definition in the low end, lower it.

> **Note if you come from v1.9.1:** the module's behaviour changed, so values stored in old presets no longer sound the same — what used to be audible was the treble boost, not the harmonics. Re-tune Drive and Mix by ear. If you miss the flat brightness it used to add, that is EQ: raise it with the **presence EQ**, which is the right tool for that.

### Symptoms and adjustment

| Symptom | Adjustment |
|---------|-----------|
| The voice sounds "metallic" or "screechy" | Lower Drive (to 1.5–2.0×). *tanh* is symmetric: it generates only odd harmonics (3rd, 5th, 7th), which is the characteristic hollow timbre; the higher the Drive, the more it shows |
| The effect is not noticeable | Raise Mix (to 40–50%) or Drive. Note: if you come from v1.9.1, the module now adds harmonics instead of lifting the treble — the change is perceived differently |
| It adds brightness to the background noise | Enable the canceller and learn a profile: with that, the exciter closes by itself between words |
| Bright but "cold" or hollow | Raise **Character** towards mixed (30–60%): it adds 2nd harmonic, which is what gives warmth |

---

## Restore bass

**Location:** Active modules → **"Restore bass"**; level in Advanced Audio → "Harmonic exciter" group

### Why an equalizer is not enough

The radio's filter — an SSB rig typically starts at 300 Hz — leaves a male voice's fundamental far below the rest:

| Fundamental (f0) | What remains after a 300 Hz high-pass |
|------------------|----------------------------------------|
| 200 Hz | −14 dB |
| 150 Hz | −24 dB |
| 120 Hz | −32 dB |
| 100 Hz | −38 dB |

With that loss **there is no energy left to lift**: no matter how far you raise the Body EQ, there is nothing there. The only way to get it back is to **regenerate it**.

The Body EQ remains the right tool when the low end **is** there and only needs reinforcing. This module is for when it is gone.

### How it works

It does not synthesize a separate tone: it **derives the fundamental from the harmonics that did get through the filter**, which is how analog bass restorers do it. The 250–1000 Hz band — where a male voice's 3rd and 4th harmonics live — is squared, and each pair of adjacent harmonics produces their difference, which is exactly the fundamental (4·f0 − 3·f0 = f0). A low-pass keeps just that.

That difference matters a lot to the ear:

- **It sounds like the voice, not on top of it.** The low end comes from the vocal material itself, so it carries its phase, its intonation and its vibrato. Measured on a voice whose f0 swings between 110 and 140 Hz — like a real phrase — what is recovered correlates **+0.78** with the original fundamental. An earlier version of this module, which synthesized an independent tone at the detected f0, scored **+0.01**: a tone pasted on top, beating against the harmonics. It sounded artificial.
- **It is not late.** This is sample-by-sample processing, with no pitch detection and no envelope: **0 ms** latency. Synthesizing required detecting f0 (computed every 3 frames), smoothing it and opening an envelope — the low end came in several tens of milliseconds after the voice.
- **It goes quiet by itself.** With no speech there are no harmonics to derive anything from. On noise alone the module adds **−19 dB** relative to the noise, i.e. nothing; the synthesizing version added **+3 dB**, because the pitch detector fires on anything periodic.

That is why the module needs no voice detection, no confidence threshold, and does not depend on the canceller.

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Restore bass** | 0% – 100% | 35% | Level of the recovered fundamental. **100%** leaves it roughly where it was before the filter, verified across four voices (deep male, male with high F1, higher male and female): the excess stays within ±1.7 dB on all of them. **35%** is the starting point; raise it gradually, because excess bass shows up quickly. |

> **About the percentage:** it is calibrated against the level the fundamental had **before** the radio's filter, not against an arbitrary value. That the same percentage sounds similar across different voices is also verified: across those four voices the spread is 2.7 dB. Even so, "the natural level" is not always what you want to hear — many people prefer considerably less.

### When to use it

It makes sense on **SSB with a narrow filter**, and generally whenever the voice sounds thin or "telephone-like" despite a good level. On AM with wide audio the fundamental is usually present and the module will have little to do.

> **Watch your own low cut first:** before enabling it, check your bandpass's lower limit. If what is cutting the low end is *your* filter and not the radio, lowering it (to 100–150 Hz) restores **real** bass, which will always sound better than synthesized bass.

---

## Chapter 11 — Levels & Gain

**Location:** Main tab → "Levels & Gain" group

### Description

Controls the input and output levels and protects against audio peaks. The VU meters show the level in dB in real time for input and output.

### Controls

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Input** | -20 dB to +20 dB | 0 dB | Amplifies or attenuates the audio before the pipeline. Raise it if the radio's signal arrives weak (input VU in the -20 to -10 dB range). Lower it if it arrives saturated (VU in red). |
| **Output** | -20 dB to +20 dB | 0 dB | Amplifies or attenuates the pipeline output. Useful for compensating the level drop the noise canceller produces — with the noise suppressed, perceived loudness drops because the noise no longer adds to the total level. Raise 3–6 dB to compensate. |
| **Peak limit** | -12 dB to 0 dB | -1 dB | Maximum level allowed at the output. Prevents distortion from clipping. -1 dB is enough to avoid clipping without compressing the audio. |

> **Output gain and Bypass (level-matched A/B comparison).** The **Output gain** now also acts
> when **Bypass** is active (previously it was only applied while processing was running, and
> bypass came out quieter). In addition, the app **remembers the Output value separately for
> bypass ON and OFF**: set a comfortable volume for the raw signal (bypass ON) and another for the
> processed signal (bypass OFF), and from then on every time you toggle Bypass the control jumps to
> the value you left for that mode. This lets you compare before/after at a matched level without
> readjusting each time. **Both levels are saved and survive an application restart**: you
> calibrate them once and they stay. Loading a preset resets the *processing* level (the preset
> carries it) but keeps the *bypass* one, because a preset describes how you process, not how loud
> you listen to the raw signal.
>
> **Note: this memory covers the *output* gain only.** The *input* gain keeps a single value for
> both modes, and that is deliberate: it sits **before** the processing, so moving it changes what
> the DSP sees (the signal-to-noise ratio reaching the canceller, the AGC's starting point, the
> floor measurement for the noise ceiling). Matching levels with the Input would mean you are no
> longer comparing the same processing. For A/B always use the **Output**.
>
> In bypass the gain is applied without the **Peak limit**, so raising Output too much can clip the
> raw signal.

### Peak limiter indicator

Below the **Peak limit** slider there is a real-time indicator:

- **—** (gray): the limiter is not acting — the output level is below the configured threshold.
- **ACTIVE  -X.X dB** (orange): the limiter is reducing light peaks (less than 3 dB of reduction).
- **ACTIVE  -X.X dB** (red): the limiter is working hard (more than 3 dB of reduction) — consider lowering the output gain or the peak limit.

On the same row, the **"Voice leveler"** indicator shows the gain that module is applying (see Ch. 7) — green while compensating a weak voice, "—" when the module is disabled.

### VU meters

- **Green** (-20 to -6 dB): optimal level.
- **Yellow** (-6 to -3 dB): high level, normal on voice peaks.
- **Red** (above -3 dB): saturation — reduce the input gain.

### WAV recording

At the bottom of the group, the **"⏺ Record"** button saves what you are hearing (the processed output) to a WAV file (mono, 16-bit, 48 kHz) inside the **`Grabaciones/`** folder, next to the executable. Files are named automatically by date and time (`RNK_2026-07-16_21-30-05_procesado.wav`).

- Available only **while processing is active**. When pressed, the button changes to "⏹ Stop recording" and the red **REC mm:ss** counter appears.
- The **"include unprocessed input"** checkbox also records a second file (`..._entrada.wav`) with the signal as it arrives from the radio — ideal for before/after comparison or documenting what the application does. Applies when the next recording starts.
- Stopping processing with a recording in progress closes the file cleanly and automatically; the status bar shows the saved duration.
- Approximate size: ~5.6 MB per minute per file. Writing runs on a separate thread: recording does not affect audio latency or smoothness.
- **Bypass** is recorded too: the recording always captures "what you hear", so toggling Bypass during a recording produces a **before/after in the same file** — ideal for demos of what the application does.

### Bypass

In the same row, the **"⇄ Bypass"** button passes audio straight from input to output, **with no processing at all**. It is how you compare before and after without stopping anything.

- It used to be a checkbox in the *Control* group; it became a button and joined **Record** and **Mute** because all three are listening actions you press and release while operating, not settings you leave in place.
- Unlike Record and Mute, it **does not require processing to be active**: having it ready before you start is useful, and it lets you calibrate each mode's level separately without audio.
- When enabled it turns amber (**"⇄ Raw"**) and the status bar shows it.
- The **Output gain** also acts in bypass, and its value is remembered **separately** for bypass ON and OFF, so you can compare at a matched level without readjusting. Both levels are **saved and survive restarts**: you calibrate once. A preset does not carry the bypass level — it describes how you process, not how loud you listen to the raw signal.
- Note about the canceller in **Adaptive** mode: in bypass the audio does not go through the processor, so the estimator cannot calibrate. The label says so ("it cannot calibrate in Bypass"); it is not a fault.

### Output mute

On the right of the same row, the **"🔇 Mute"** button silences the speaker output **without stopping processing**. Handy for a quick test, to step away for a moment, or to go silent without losing the process state (learned noise profile, AGC, calibration).

- Available only **while processing is active**. When enabled it turns red (**"🔇 Muted"**) and the status bar shows it.
- It is a **monitoring mute**: processing, recording and the meters (VU and spectrum) **keep running** and showing the signal — only the audio you hear is cut. So if you are recording, the recording is **not** silenced: it keeps capturing the processed output.
- It releases only when pressed again, and turns off automatically when you **STOP** processing.

---

## Recommended starting configuration

### SSB on HF bands (14–28 MHz)

| Module | State | Notes |
|--------|-------|-------|
| Impulse suppressor | ✅ On | Frame threshold 15×, micro 8× |
| Bandpass filter pre | ✅ On | SSB: 200–3000 Hz |
| Bandpass filter post | ✅ On | Same as pre |
| ANF | ✅ On | Sensitivity 3.0×, depth 50% (raise only if a heterodyne stays audible) |
| Noise canceller | ✅ On | Learn the profile first (or Adaptive mode) |
| ↳ Perceptual spectral floor | ⬜ Optional | Enable if the voice sounds cold or hollow |
| ↳ Spectral post-filter | ⬜ Optional | Enable if residual intermittent birdies are heard |
| ↳ Voice pitch enhancement | ⬜ Optional | For very weak SSB DX signals — improves intelligibility |
| ↳ Voice leveler | ⬜ Optional | Enable with stations at uneven levels or strong QSB |
| Noise gate | ⬜ Optional | Threshold between the level the indicator reads in the gaps and the level it reads with signal; depth 15–25 dB |
| Voice EQ | ✅ On | Presence +4 dB at 2000 Hz; body +3 dB at 350 Hz if the voice sounds thin |
| Harmonic exciter | ⬜ Optional | Drive 2.0×, mix 25% |
| Restore bass | ⬜ Optional | If the voice sounds thin. Start at 35% and raise it gradually |

### AM (medium wave or shortwave)

| Module | State | Notes |
|--------|-------|-------|
| Impulse suppressor | ✅ On | Frame threshold 20×, micro 10× |
| Bandpass filter pre | ✅ On | AM: 300–5000 Hz (music: up to 10000 Hz) |
| Bandpass filter post | ✅ On | Same as pre |
| ANF | ⬜ Optional | Only if audible heterodynes are present |
| Noise canceller | ✅ On | Learn the profile first (or Adaptive mode) |
| ↳ Perceptual spectral floor | ⬜ Optional | Enable if the voice sounds cold or hollow |
| ↳ Spectral post-filter | ⬜ Optional | Enable if residual birdies remain |
| ↳ Voice pitch enhancement | ⬜ Optional | Also helps on AM: demodulation preserves the voice harmonics |
| ↳ Voice leveler | ⬜ Optional | For music **tick "Level continuously"** (without it the voice gate freezes the gain); useful to even out cyclic fading |
| Noise gate | ⬜ Optional | No longer a nuisance with music (it decides on level, not on voice), but it attenuates quiet passages that fall below the threshold |
| Voice EQ | ⬜ Optional | Presence if the voice sounds dull; body if it sounds thin |
| Harmonic exciter | ⬜ Optional | In moderation |
| Restore bass | ⬜ Optional | On wide AM the fundamental is usually there: check the bandpass low cut first |

### Recommended calibration flow

These on-air techniques help get the most out of the app without degrading the voice:

1. **Enable modules one at a time.** When building a configuration or receiving a new signal,
   toggle each module on and off separately, listening to its effect. Everything applies live, so
   you hear the difference instantly and it's easy to decide what helps and what doesn't.
2. **Calibrate Intensity with the Preview.** Enable "Preview: listen to removed noise" and raise the
   canceller's Intensity while what's removed is **only noise**. As soon as voice starts leaking into
   the preview, step back down: that's the point of maximum cancellation without touching the voice.
3. **Low Intensity + high post-filter (natural voice).** Lower the Intensity to **50–60%** and
   compensate with the **post-filter at 5–8**. This usually gives better cancellation with a more
   natural voice than raising the Intensity alone: low Intensity doesn't dull the voice, and the
   post-filter cleans the noise acting only on the bins the VAD marks as noise. This recipe ships as
   factory presets **"Voz natural — AM"** and **"Voz natural — SSB"**.
4. **ANF Depth: you can raise it now.** The reason to keep it low (it muffled the voice) was a detection flaw fixed in v2.2. Raise it
   if a heterodyne stays audible.
5. **Perceptual floor on SSB.** If you enable the perceptual spectral floor on SSB and don't notice
   the rolloff, lower the "Rolloff start" to ~1500 Hz (see Ch. 7).

---

## Chapter 12 — Spectrum Viewer

**Location:** Spectrum tab

### Description

Shows in real time the energy distribution by frequency (spectrogram) of the pipeline's input and output signals. Lets you see at a glance how much noise is being removed in each frequency band and verify that the voice is not being affected.

The viewer runs at ~15 frames per second. To reduce CPU cost, it pauses automatically when the Spectrum tab is not visible.

### Available curves

| Curve | Color | Description |
|-------|-------|-------------|
| **Input** | Blue | Signal before the noise canceller (after the bandpass filter and the ANF). |
| **Output** | Green | Final processed signal, as it goes to the audio device. |
| **Cancelled** | Orange (filled) | Area between the input and output curves — energy the canceller is subtracting. The larger the orange area, the more noise is being removed. |
| **Noise floor** | Dotted yellow | The spectral profile used by the canceller. Represents "what the background noise sounds like" bin by bin. In **Static profile** mode it appears automatically when a profile exists (learned in this session or loaded from a previous one). In **Adaptive (MCRA)** mode it updates every 500 ms with the real-time estimate. |

Each curve can be shown or hidden independently with the checkboxes in the top bar.

> **Why does the noise floor seem to stop in the treble?** This question comes up as soon as you
> widen the input bandpass: you take it to 5 or 6 kHz and the yellow line still seems to end near
> 4 kHz. **It is not cut off: it is resting on the bottom edge of the graph.** The vertical scale
> goes down to −80 dB, and above a certain frequency the noise falls below that value, so the curve
> is flattened against the frame and blends into it. Measured on a real rig with the bandpass at
> 6 kHz: −69 dB at 4 kHz, −74 dB at 4.5 kHz and **−80 dB at 5 kHz**, which is exactly where it
> stops being distinguishable.
>
> What matters is the underlying cause: **that rolloff is the radio's doing, not the application's.**
> The receiver's IF filter and audio chain already trimmed that region before the signal reaches the
> sound card — measured on real recordings, the raw input drops about 17 dB at 4 kHz, 26 dB at 5 kHz
> and 40 dB at 6 kHz relative to 1 kHz. Widening the bandpass cannot bring back a signal that never
> came in.
>
> **Two practical consequences.** Widening the input bandpass beyond where your receiver reaches
> adds no brightness — it only adds a strip with some residual noise and almost no voice; if you are
> after treble, it comes from the **Aural exciter** or the **presence EQ**. And the canceller's
> **HF floor boost** has the same ceiling: its ramp grows per octave from 2.5 kHz, but above the
> radio's cutoff it is multiplying a floor that is already inaudible. To find where that cutoff is
> on your rig, look at how far the **Input** curve reaches on this same graph.

### S/N indicator

To the right of the checkboxes, the **S/N** indicator shows the full-band signal-to-noise ratio: how many dB above the estimated noise floor the current signal peaks are (smoothed ~1 s). Green = comfortable signal (>15 dB); yellow = workable (6–15 dB); gray = marginal or noise only (with band noise alone it reads close to 0). Requires the canceller enabled with a profile (learned or MCRA-calibrated). Useful for comparing antennas, bands or propagation conditions with an objective number.

### Controls

**Visibility checkboxes (top bar)**

Show or hide each curve without affecting audio processing.

**Learning / clearing the noise floor**

In Static profile mode, the yellow floor is captured from the **⏺ Learn noise** button on the Main tab and stays fixed, showing the active profile — even across processing restarts or application restarts, as long as the profile exists. The **Clear profile** button also clears the spectrum line. In Adaptive mode the line updates by itself, with no intervention.

**Zoom sliders**

| Control | Range | Default | Description |
|---------|-------|---------|-------------|
| **Max Y** | -60 dBFS to 0 dBFS | 0 dBFS | Adjusts the vertical axis ceiling. Lowering it (e.g. -20 dBFS) compresses the scale and makes differences between curves more visible when the signal is weak. The value is saved automatically. |
| **Max X** | 1 kHz to 12 kHz | 12 kHz | Adjusts the right edge of the frequency axis. Reducing it to 3–4 kHz zooms into the vocal zone for better detail. The value is saved automatically. |

Both sliders rescale **the spectrum and the waterfall** at the same time.

**Colour scale:** at the top left of the waterfall there is a bar with the gradient and the dB range it represents (from −80 dB up to the *Max Y* slider value). It lets you read the colours without guessing: moving *Max Y* changes the range and the bar reflects it. In **Difference** mode the bar switches by itself to a fixed −30 · 0 · +30 dB scale (see below).

**Heterodyne markers:** when the **ANF** is enabled, the frequencies where it is cancelling tones appear marked in red along the waterfall's bottom axis. A steady heterodyne shows as a fixed mark; an intermittent one blinks. It is the quick way to confirm the ANF is catching the tone that bothers you — and to discover tones sneaking in unnoticed.

### Waterfall

Below the instantaneous spectrum is the **waterfall**: a time-frequency display with history (~30 seconds). The horizontal axis is frequency (aligned with the spectrum above), the vertical axis is time (the top row is *now*, downward is the past), and color represents the intensity at each frequency (blue = weak / noise floor, up to red = strong). It lets you **see** the evolution over time that the instantaneous spectrum cannot show: signal QSB (fading), heterodynes that come and go, and intermittent interference (QRM).

| Control | Description |
|---------|-------------|
| **"Waterfall" checkbox** | Shows or hides the waterfall. When hidden, the instantaneous spectrum takes the full height. The state is saved automatically. |
| **Input / Output / Difference selector** | Chooses what is drawn: **Input** (before processing — to see the interference as it arrives), **Output** (after processing — to see the result) or **Difference** (what processing removed; see below). |
| **Depth selector (15 / 30 / 60 / 120 s)** | How much history is shown. More depth to follow slow QSB or tell whether a heterodyne is intermittent; less to look at the fine time detail of the last few seconds. **It does not discard what was captured**: the buffer always keeps 120 s and the selector is a zoom, so widening the window reveals history that was already there. The time axis adjusts its ticks automatically. |

**Resizing the split:** the spectrum and the waterfall are separated by a **draggable divider**. By default the tab is split in half, but you can drag the divider up or down with the mouse to give more room to whichever you are watching (more waterfall to track the fading, more spectrum for instantaneous detail).

#### Difference mode

With the selector on **Difference**, the waterfall stops showing the level of a signal and shows **how much processing removes at each frequency, moment by moment** (input minus output, in dB). It is the direct way to answer *"what is the canceller taking away, and where?"* without having to compare two images by eye.

The colour scale is different and **fixed at ±30 dB** — the *Max Y* slider does not affect it, because these numbers are differences, not levels:

| Colour | Meaning |
|--------|---------|
| **Background (near black)** | Nothing happening there: what goes in comes out. |
| **Blue → cyan → green → yellow → red** | Signal is being **removed**, increasingly so (up to 30 dB). It is the same colour ramp as the Input/Output modes, so it reads the same way. |
| **Violet / magenta** | There the chain **amplifies** instead of removing. |

How to read it:

- **The voice band (300–2500 Hz) should stay dark while someone is talking.** If it lights up green or yellow exactly when speech arrives, the canceller is eating voice: lower **Intensity** or raise the **Spectral floor**. Same diagnosis the *Preview* gives, but showing you at which frequencies it happens.
- **Alternating horizontal stripes** = the canceller working to the rhythm of the conversation: removing a lot during pauses and easing off when speech comes in. That is what you want to see.
- **A bright, steady vertical line** = the ANF cancelling a heterodyne, or the post-filter on a steady tone.
- **The whole screen tinted an even violet** = output gain, not cancellation. *Output gain* lifts everything equally and shows up as a constant violet floor; in **Bypass** you will see exactly that and nothing else, which is a good way to confirm you are reading the scale correctly.
- **Note:** the difference covers **the whole chain**, not just the canceller — the output bandpass, voice EQ, exciter and gain show up too. To isolate the canceller, turn the other modules off and look at them one at a time (Chapter 3).

### Practical interpretation

**Visible reduction with clean voice:**
- The orange area covers mostly the background-noise frequencies (uniform distribution across the band).
- The green curve stays below the blue one in noise zones, but the two converge at voice peaks.

**The canceller is suppressing voice (too aggressive):**
- The orange area is large even at voice peaks.
- Reduce **Intensity** or raise the **Spectral floor** in the Advanced Canceller tab.

**The canceller is doing nothing:**
- The blue and green curves overlap completely — no orange area.
- Check that a noise profile has been learned and the **Stationary noise canceller** module is enabled.

**Checking with the "listen to removed noise" preview:**
- Enable the **Preview: listen to removed noise** checkbox (Main tab) and watch the spectrum.
- What you hear should match the orange area. If voice peaks show up in the orange area, the canceller is touching the voice — raise the **Spectral floor**.

---

## Chapter 13 — Presets

**Location:** Presets tab

### Description

A preset stores a complete "snapshot" of the DSP and gain configuration — every module, slider and mode from the Main and Advanced tabs. Audio devices and the window position are **not** part of the preset (they are machine-specific).

Typical use: a "weak SSB DX" preset with an aggressive canceller and pitch enhancement, another "local AM" preset with the gate off and wide filters, switching between them with a double click depending on what you are listening to.

### Operations

| Button | Action |
|--------|--------|
| **Save as new** | Creates a preset with the typed name, capturing the current configuration. |
| **Overwrite selected** | Updates the selected preset with the current configuration. |
| **Load** (or double click) | Applies the preset **on the fly** — without restarting audio. All UI sliders and checkboxes update instantly. |
| **Delete / Rename** | List management. |

Presets are stored as individual `.json` files in the `Presets/` folder next to the executable — they can be backed up or copied between machines.

### Active preset and persistence

The **"Active preset"** label shows the last preset loaded or saved. If any control is changed after loading it, the label adds the **"(modified)"** suffix — indicating that what you hear is the preset plus your tweaks, not the pure preset.

> **New in v1.7 — preset in the title bar:** the active preset's name (with "(modified)" when it applies) also appears in the **window title bar**, visible from any tab and in the Windows taskbar. When you **Overwrite** the preset with the current configuration, the "(modified)" disappears (the config matches what's saved again).

When you close and reopen the application:

- **All values are restored exactly as they were** (via `settings.json`), including any tweaks made after loading the preset.
- The "Active preset" label remembers the name, with "(modified)" if the current values differ from those stored in the preset.
- To return to the pure preset, discarding your tweaks, simply load it again.

---

## Configuration persistence

All settings are saved automatically when the application closes and restored when it reopens. The `settings.json` file is created next to the executable. To return to factory defaults, simply delete that file.

Each Advanced tab has a **"↺ Restore defaults"** button that resets only that tab's controls without touching the rest of the configuration.

**Restoring an individual slider:** **right-click** on any slider to open a context menu with the *"↺ Restore default (value)"* option. It returns that single parameter to its factory value without touching the others.

The **Max Y** and **Max X** sliders of the spectrum viewer are also saved in `settings.json` along with the rest of the configuration.

---

## If something goes wrong — the diagnostic file

Next to the executable, in the same folder as `settings.json`, the application may create a file called **`errores_dsp.log`**. It only appears if something went wrong: **if it is not there, there were no errors.**

Two status-bar warnings refer to it, and it helps to know what they mean:

| Warning | What happened | What to do |
|---------|---------------|------------|
| **⚠ The DSP processor is failing — see errores_dsp.log** | An operation in the processing chain raised an exception. **The application does not crash**: it recovers on its own and carries on with the next audio, but something is not working properly. | Send the file. It contains the exact line that failed. |
| **The adaptive estimator is not completing calibration** | Adaptive mode never finishes calibrating. The warning says **which** of the known causes it is (no audio, canceller disabled, processor error). If it says it is none of them, it is a case that has not been identified yet. | Try the workaround that works — switch to *Static profile* and back to *Adaptive* — and **send the file**: in that case the application dumps its full internal state there. |

The file is capped at a few errors per session, so it does not grow without bound, and it can be deleted with no consequences.

> **Why it exists:** a processing failure used to be invisible. The application recovered on its own and kept running, but with the affected module half working, and from the outside the only symptom was "this is not reducing the noise" — with nothing to explain it. These warnings and this file exist so that next time there is a trail somebody can read.

---

*RadioNoiseKiller — version 2.3*
