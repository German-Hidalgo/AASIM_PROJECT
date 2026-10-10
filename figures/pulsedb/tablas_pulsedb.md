### Sujetos y segmentos por fuente
| fuente | sujetos | segmentos | seg_mediana | seg_max |
| --- | --- | --- | --- | --- |
| MIMIC | 2423.0 | 3791004.0 | 913.0 | 24941.0 |
| VitalDB | 2938.0 | 1454450.0 | 414.0 | 3297.0 |

### Composición de adultos (fuente / edad; F y M)
| estrato | F | M |
| --- | --- | --- |
| MIMIC / 18-39 | 78 | 112 |
| MIMIC / 40-64 | 419 | 620 |
| MIMIC / 65 o más | 520 | 672 |
| VitalDB / 18-39 | 159 | 142 |
| VitalDB / 40-64 | 720 | 763 |
| VitalDB / 65 o más | 437 | 690 |

### Cuotas ISO 81060-2 (corpus completo)
          rango       n  fraccion_observada  fraccion_minima  cumple
PAS <= 100 mmHg  871534              0.1662             0.05    True
PAS >= 160 mmHg  273041              0.0521             0.05    True
 PAD <= 60 mmHg 2519647              0.4803             0.05    True
PAD >= 100 mmHg   40841              0.0078             0.05   False

### Cuotas ISO tras la censura clínica
          rango       n  fraccion_observada  fraccion_minima  cumple
PAS <= 100 mmHg  778967              0.1532             0.05    True
PAS >= 160 mmHg  271311              0.0534             0.05    True
 PAD <= 60 mmHg 2385908              0.4694             0.05    True
PAD >= 100 mmHg   33197              0.0065             0.05   False


### Retardo ABP (ms) por fuente
| fuente | count | mean | std | min | 5% | 25% | 50% | 75% | 95% | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MIMIC | 1054.0 | 168.0 | 259.0 | -792.0 | -443.0 | 240.0 | 280.0 | 296.0 | 336.0 | 376.0 |
| VitalDB | 988.0 | -25.0 | 410.0 | -776.0 | -552.0 | -336.0 | -176.0 | 464.0 | 496.0 | 528.0 |

### Medianas de los SQI por fuente
| fuente | bsqi | ksqi | psqi | ssqi |
| --- | --- | --- | --- | --- |
| MIMIC | 1.0 | 13.3 | 0.52 | 2.61 |
| VitalDB | 1.0 | 13.66 | 0.5 | 2.78 |

### Rechazo por subgrupo
| dimensión | subgrupo | sujetos | ventanas | rechazo (%) | pSQI mediana |
| --- | --- | --- | --- | --- | --- |
| fuente | MIMIC | 21 | 1054 | 41.7 | 0.524 |
| fuente | VitalDB | 20 | 989 | 49.9 | 0.501 |
| sexo | F | 19 | 883 | 39.9 | 0.525 |
| sexo | M | 22 | 1160 | 50.1 | 0.5 |
| edad | 18-64 | 29 | 1434 | 35.0 | 0.534 |
| edad | 65 o más | 12 | 609 | 70.8 | 0.415 |
| estrato PAS | <= 100 | 29 | 426 | 41.8 | 0.521 |
| estrato PAS | 101-139 | 39 | 1309 | 45.0 | 0.514 |
| estrato PAS | 140-159 | 24 | 199 | 46.7 | 0.509 |
| estrato PAS | >= 160 | 7 | 108 | 66.7 | 0.29 |

### Mayores correlaciones de Spearman (ventanas aceptadas)
| característica | rho_PAS | rho_PAD |
| --- | --- | --- |
| feat_glcm_qrs_homogeneity | 0.372 | 0.176 |
| feat_glcm_qrs_contrast | -0.369 | -0.188 |
| feat_r_amplitude_mv | 0.008 | 0.328 |
| feat_hrv_hf_ms2 | 0.291 | 0.001 |
| feat_hrv_apen | -0.283 | -0.034 |
| feat_qrs_duration_ms | -0.065 | -0.282 |
| feat_s_depth_mv | -0.278 | 0.088 |
| feat_hrv_sd1_ms | 0.244 | -0.07 |
