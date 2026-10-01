#!/bin/sh
# Tahap eksplorasi (PROTOCOL.md v2): beban x PR cloud x kelas L1 x 4 algoritma, 3 run, seed terpisah.
# Pemakaian: sh scripts/run_exploration.sh OUT_DIR [MANIFEST]
# Dapat dilanjutkan: kondisi yang sudah selesai (berkas .done) dilewati; sisa parsial dihapus.
set -e
OUT=${1:?output dir}
MANIFEST=${2:-data/cameras_SYNTHETIC.csv}
read PRS L1S ALGS RUNS SEED BUDGET <<EOF2
$(python3 -c "from config import protocol as p; print(' '.join([','.join(map(str,p.CLOUD_PR_MS)), ','.join(p.L1_CLASSES), ','.join(p.EXPLORATION_ALGORITHMS), str(p.EXPLORATION_RUNS), str(p.EXPLORATION_SEED), str(p.BUDGET)]))")
EOF2
mkdir -p $OUT
for L1 in $(echo $L1S | tr ',' ' '); do
  for PR in $(echo $PRS | tr ',' ' '); do
    DIR=$OUT/pr${PR}_${L1}
    [ -f $DIR/.done ] && continue
    rm -rf $DIR
    python3 -B -m runner.run_experiment --output $DIR --manifest $MANIFEST --design fps-fixed-deadline \
      --seed $SEED --runs $RUNS --budget $BUDGET --duration 10000 --drain-time 10000 \
      --algorithms $ALGS --l1-class $L1 --cloud-pr $PR
    python3 -B -m analysis.constraint_analysis $DIR
    touch $DIR/.done
  done
done
rm -rf $OUT/regions
python3 -B -m analysis.regions $OUT/regions $OUT --manifest $MANIFEST
