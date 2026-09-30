#!/bin/sh
# Ablasi komponen pada desain utama (fps-fixed-deadline): skenario, trafik, seed, dan budget identik.
# Pemakaian: sh scripts/run_ablation.sh OUT_DIR [RUNS] [MANIFEST]
set -e
OUT=${1:?output dir}
RUNS=${2:-5}
MANIFEST=${3:-data/cameras_SYNTHETIC.csv}
ALGS=GA,PSO,GWO,WOA,HHO,SA,Random   # baseline (Greedy/Nearest/MinLatency) tidak terpengaruh mode fitness
COMMON="--manifest $MANIFEST --design fps-fixed-deadline --runs $RUNS --budget 3000 --duration 10000 --drain-time 10000 --algorithms $ALGS"

python3 -B -m runner.run_experiment --output $OUT/full $COMMON
python3 -B -m runner.run_experiment --output $OUT/constant $COMMON --cloud-mode constant
python3 -B -m runner.run_experiment --output $OUT/none $COMMON --cloud-mode none
python3 -B -m runner.run_experiment --output $OUT/no-headroom $COMMON --alpha 0.5 --beta 0.5 --gamma 0
for v in full constant none no-headroom; do python3 -B -m analysis.constraint_analysis $OUT/$v; done
python3 -B -m analysis.ablation $OUT/ablation full=$OUT/full constant=$OUT/constant none=$OUT/none no-headroom=$OUT/no-headroom
