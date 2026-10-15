# Phase 3: grading and percentile checks

## Stability across seeds (production sim counts 600/3000)

Spot 2023_01_ARI_WAS_d23, state {'qtr': 4, 'clock': 143, 'down': 1, 'togo': 10, 'yl': 75, 'score': [16, 20], 'tos': [3, 2], 'recv2h': True}, chosen `pass_medium_right`. 2.9 s per grade in Python (30 options).

| seed | best | gap | color |
|---|---|---:|---|
| 1 | pa_deep_right | 2.02% | yellow |
| 2 | pa_medium_middle | 2.15% | yellow |
| 3 | pass_deep_middle | 1.62% | yellow |
| 4 | pa_deep_right | 1.47% | yellow |
| 5 | pa_deep_right | 5.07% | red |

gap mean 2.46%, sd 1.33%, colors ['red', 'yellow']

Top options, seed 1:

| option | q | WP r1 | WP r2 |
|---|---:|---:|---:|
| pass_deep_middle | 0.013 | 0.239 |  |
| pa_deep_left | 0.004 | 0.239 |  |
| pa_deep_right | 0.004 | 0.245 | 0.236 |
| pa_deep_middle | 0.002 | 0.234 |  |
| pa_medium_left | 0.007 | 0.246 | 0.230 |
| pass_deep_left | 0.029 | 0.224 |  |

## Percentile for test policies (6 Q4 spots, sims 150/600)

| policy | 2023_01_ARI_WAS | 2023_01_ARI_WAS | 2023_01_ARI_WAS | 2023_01_BUF_NYJ | 2023_01_BUF_NYJ | 2023_01_DET_KC_ | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| always best | 96 | 99 | 78 | 66 | 100 | 98 | 90 |
| league frequency | 23 | 52 | 38 | 15 | 5 | 1 | 22 |
| softmax tau=0.01 | 78 | 92 | 38 | 83 | 75 | 70 | 73 |
| softmax tau=0.05 | 55 | 62 | 38 | 26 | 17 | 52 | 42 |
| always worst | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Coach match smoke test

Best-policy drive on 2023_01_ARI_WAS_d22: traits {pass: +0.83, deep: +0.00, go: +0.76, timeout: +0.00, tempo: +0.00}, nearest coach **Brandon Staley**, reasons []
