#!/bin/sh
# Lanjutkan ablasi yang terhenti: varian `full` harus sudah lengkap; varian lain diulang dari awal.
# Pemakaian: sh scripts/resume_ablation.sh [OUT_DIR] [RUNS] [MANIFEST]
# Jangan ubah config/, generator/, placements/, runner/ atau versi Python/paket sebelum menjalankan
# (analysis.ablation menolak pairing bila hash kode atau paket berbeda dari varian `full`).
set -e
OUT=${1:-results/ablation-v1}
RUNS=${2:-5}
MANIFEST=${3:-data/cameras_SYNTHETIC.csv}
ALGS=GA,PSO,GWO,WOA,HHO,SA,Random
COMMON="--manifest $MANIFEST --design fps-fixed-deadline --runs $RUNS --budget 3000 --duration 10000 --drain-time 10000 --algorithms $ALGS"

[ -f $OUT/full/manifest.json ] || { echo "varian full belum ada di $OUT"; exit 1; }
rm -rf $OUT/constant $OUT/none $OUT/no-headroom $OUT/ablation
for v in full constant none no-headroom; do rm -rf $OUT/$v/analysis; done

python3 -B -m runner.run_experiment --output $OUT/constant $COMMON --cloud-mode constant
python3 -B -m runner.run_experiment --output $OUT/none $COMMON --cloud-mode none
python3 -B -m runner.run_experiment --output $OUT/no-headroom $COMMON --alpha 0.5 --beta 0.5 --gamma 0
for v in full constant none no-headroom; do python3 -B -m analysis.constraint_analysis $OUT/$v; done
python3 -B -m analysis.ablation $OUT/ablation full=$OUT/full constant=$OUT/constant none=$OUT/none no-headroom=$OUT/no-headroom
