# RNG deployment mainline strengthening

本地仓库位于 Alice_Methane 下，原始公开档和旧计算目录在父工程。冻结输入路径及散列见每次运行的 `run_record.json` 和旧脚本输出。完整交付入口为 [STATUS](STATUS.md)，正文证据对应见 [claims_to_evidence](claims_to_evidence.md)。主脚本以供气填埋场的首次事件为结局，输出路径含运行编号。初期并行分析文件和试跑保留为过程版本。

从 Alice_Methane 根目录复跑旧脚本时，为隔离结果指定新的 batch。若要完全新建一份工作副本的主分析，先复现 batch `run_001`，其事件轨迹用于桥接旧模型。已归档的 batch 不宜覆盖。

```powershell
$env:OPENBLAS_NUM_THREADS='1'
python -B -X utf8 rng_mainline_strengthening_v1/src/reproduce_legacy.py backfill --batch run_002
python -B -X utf8 rng_mainline_strengthening_v1/src/reproduce_legacy.py spatial --batch run_002
python -B -X utf8 rng_mainline_strengthening_v1/src/reproduce_legacy.py diagnostics --batch run_002
python -B -X utf8 rng_mainline_strengthening_v1/src/run_main.py --run run_007
python -B -X utf8 rng_mainline_strengthening_v1/src/temporal.py --run run_006
python -B -X utf8 rng_mainline_strengthening_v1/src/make_mainline_figures.py --main run_007 --temporal run_006 --run run_004
python -B -X utf8 rng_mainline_strengthening_v1/src/verify_mainline_outputs.py --main run_007 --temporal run_006 --figures run_004 --run run_004
```

每步须用尚未占用的运行编号。主分析、2020 队列和图形均为确定性计算。30 场既有核验的抽样设计和 seed 是原档信息，本轮没有重抽。对 215 个项目行的事件账本中，`registered_date` 记录原字段，`date_lower` 和 `date_upper` 记录外部证据可支持的范围。空白表示该边界未被证实。来源定位和审核状态在来源表。
