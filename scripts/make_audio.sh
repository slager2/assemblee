#!/usr/bin/env bash
# Synthesises the built-in music beds and sound effects (no third-party audio, no licences needed).
# Output: .cache/audio/*.wav (loudness-normalised).
set -euo pipefail
OUT="${ASSEMBLEE_AUDIO:-$(cd "$(dirname "$0")/.." && pwd)/.cache/audio}"
mkdir -p "$OUT"
cd "$OUT"
norm="loudnorm=I=-16:TP=-1.5"
ff() { ffmpeg -v error -y "$@"; }

# dark_drone: low detuned sines + brown noise, slow movement
ff -f lavfi -i "aevalsrc='0.35*sin(2*PI*55*t)*(0.7+0.3*sin(2*PI*0.13*t))+0.2*sin(2*PI*82.4*t+sin(2*PI*0.07*t))+0.08*sin(2*PI*110.3*t)*(0.5+0.5*sin(2*PI*0.5*t))':s=48000:d=180" \
   -f lavfi -i "anoisesrc=color=brown:amplitude=0.25:d=180:r=48000" \
   -filter_complex "[1]lowpass=f=400[n];[0][n]amix=inputs=2:weights=1 0.6,aecho=0.8:0.7:600:0.4,afade=t=in:d=2,$norm[a]" -map "[a]" -ac 2 -ar 48000 dark_drone.wav

# chiptune: 120 bpm square arpeggio + bass + kick
ff -f lavfi -i "aevalsrc='st(0,mod(floor(t*8),16)); st(1, if(lt(ld(0),4), 0, if(lt(ld(0),8), 5, if(lt(ld(0),12), 7, 3)))); st(2, mod(floor(t*8),4)); st(3, ld(1)+if(eq(ld(2),0),12,if(eq(ld(2),1),16,if(eq(ld(2),2),19,24)))); 0.18*sgn(sin(2*PI*261.63*pow(2,ld(3)/12)*t))*exp(-mod(t,0.125)*14) + 0.22*sgn(sin(2*PI*65.4*pow(2,ld(1)/12)*t))*exp(-mod(t,0.25)*6) + 0.25*sin(2*PI*55*t)*exp(-mod(t,0.5)*25)':s=48000:d=180" \
   -af "lowpass=f=6000,afade=t=in:d=0.5,$norm" -ac 2 -ar 48000 chiptune.wav

# epic: 140 bpm kick + saw pulse + pad
ff -f lavfi -i "aevalsrc='st(0,60/140); st(1, mod(floor(t/(ld(0)*8)),4)); st(2, if(eq(ld(1),0),0,if(eq(ld(1),1),-4,if(eq(ld(1),2),-2,-5)))); 0.6*sin(2*PI*(45+90*exp(-mod(t,ld(0))*30))*t)*exp(-mod(t,ld(0))*9) + 0.12*(2*mod(110*pow(2,ld(2)/12)*t,1)-1)*exp(-mod(t,ld(0)/2)*7) + 0.07*sin(2*PI*220*pow(2,ld(2)/12)*t)+0.05*sin(2*PI*277.2*pow(2,ld(2)/12)*t)+0.05*sin(2*PI*329.6*pow(2,ld(2)/12)*t)':s=48000:d=180" \
   -af "lowpass=f=5000,aecho=0.6:0.5:300:0.25,afade=t=in:d=1,$norm" -ac 2 -ar 48000 epic.wav

# warm_pad: slow major-seventh chords, soft and calm (family / memories / emotional)
ff -f lavfi -i "aevalsrc='st(0, mod(floor(t/4),4)); st(1, if(eq(ld(0),0),0,if(eq(ld(0),1),-3,if(eq(ld(0),2),5,-5)))); st(2, 0.5-0.5*cos(2*PI*mod(t,4)/4)); (0.10*sin(2*PI*196*pow(2,ld(1)/12)*t)+0.08*sin(2*PI*246.9*pow(2,ld(1)/12)*t)+0.07*sin(2*PI*293.7*pow(2,ld(1)/12)*t)+0.05*sin(2*PI*370*pow(2,ld(1)/12)*t)+0.12*sin(2*PI*98*pow(2,ld(1)/12)*t))*(0.6+0.4*ld(2))':s=48000:d=180" \
   -af "lowpass=f=2500,aecho=0.8:0.8:900|1300:0.35|0.25,afade=t=in:d=3,$norm" -ac 2 -ar 48000 warm_pad.wav

# sound effects
ff -f lavfi -i "anoisesrc=d=0.45:a=0.8:r=48000" -af "acrusher=bits=4:samples=12,highpass=f=800,afade=t=out:st=0.3:d=0.15,loudnorm=I=-18:TP=-2" -ac 2 -ar 48000 sfx_glitch.wav
ff -f lavfi -i "anoisesrc=d=0.8:color=white:amplitude=1:r=48000" -af "highpass=f=400,lowpass=f=4000,afade=t=in:d=0.4:curve=exp,afade=t=out:st=0.4:d=0.4,loudnorm=I=-18:TP=-2" -ac 2 -ar 48000 sfx_whoosh.wav
ff -f lavfi -i "aevalsrc='0.4*sin(2*PI*if(lt(t,0.12),880,1320)*t)*exp(-mod(t,0.12)*10)':s=48000:d=0.35" -af "loudnorm=I=-18:TP=-2" -ac 2 -ar 48000 sfx_notify.wav
ff -f lavfi -i "aevalsrc='0.9*sin(2*PI*(38+60*exp(-t*8))*t)*exp(-t*2.5)':s=48000:d=1.6" -af "loudnorm=I=-18:TP=-2" -ac 2 -ar 48000 sfx_boom.wav
ff -f lavfi -i "aevalsrc='0.5*sin(2*PI*(1200+2400*t)*t)*exp(-t*6)':s=48000:d=0.5" -af "loudnorm=I=-20:TP=-2" -ac 2 -ar 48000 sfx_rise.wav
ls -1 "$OUT"
